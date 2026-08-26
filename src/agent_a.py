"""Agent A: issues the human root grant, signs a child delegation to Agent B,
and sends a genuine A2A SendMessage to Agent B carrying the delegation chain.

Protocol-defined behavior used here: `a2a.client.create_client`, AgentCard
resolution, `Client.send_message`, `SendMessageRequest`, `Message`,
`context_id`.

Fixture-local behavior: the delegation-chain payload placed under
`Message.metadata[A2A_DELEGATION_EXTENSION_URI]`, and the `requested_action`
convenience field alongside it (the concrete refund order/amount Agent A is
asking Agent B to execute -- this is scenario input, not part of the chain
itself, and Agent B independently re-derives/attenuates its own request).
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from a2a.client import ClientConfig, ClientFactory
import a2a.types as a2a_types

from authority import AuthoritySigner, DelegationChain, SignedGrant, hash_grant
from constants import A2A_DELEGATION_EXTENSION_URI


def issue_delegation_chain(
    signer: AuthoritySigner,
    order_id: str,
    human_limit_usd: str,
    delegated_limit_usd: str,
) -> DelegationChain:
    """Build and sign the two-hop chain: human-approval -> agent-a -> agent-b."""
    root_grant = {
        "issuer": "human-approval",
        "delegate": "agent-a",
        "action": "refund_order",
        "resource": order_id,
        "max_amount_usd": human_limit_usd,
        "max_uses": "1",
    }
    root_signed = signer.sign(root_grant)

    child_grant = {
        "issuer": "agent-a",
        "delegate": "agent-b",
        "parent": hash_grant(root_signed.grant),
        "action": "refund_order",
        "resource": order_id,
        "max_amount_usd": delegated_limit_usd,
        "max_uses": "1",
    }
    child_signed = signer.sign(child_grant)

    return DelegationChain(links=(root_signed, child_signed))


async def send_delegated_refund_request(
    agent_b_url: str,
    chain: DelegationChain,
    order_id: str,
    requested_amount_usd: str,
) -> dict[str, Any]:
    """Send a real A2A message to Agent B, carrying the delegation chain as metadata."""
    async with httpx.AsyncClient() as httpx_client:
        factory = ClientFactory(ClientConfig(httpx_client=httpx_client, streaming=False))
        client = await factory.create_from_url(agent_b_url)

        message = a2a_types.Message(
            message_id=str(uuid.uuid4()),
            context_id=str(uuid.uuid4()),
            role=a2a_types.Role.ROLE_USER,
            parts=[
                a2a_types.Part(
                    text="Execute the delegated refund using no more authority than the attached chain grants."
                )
            ],
            extensions=[A2A_DELEGATION_EXTENSION_URI],
        )
        message.metadata.update(
            {
                A2A_DELEGATION_EXTENSION_URI: chain.to_wire(),
                "requested_action": {"order_id": order_id, "amount_usd": requested_amount_usd},
            }
        )

        request = a2a_types.SendMessageRequest(message=message)

        events = []
        async for event in client.send_message(request):
            events.append(event)
        await client.close()

        final = events[-1] if events else None
        outcome: dict[str, Any] = {"raw_events": len(events)}
        if final is not None and final.HasField("task"):
            task = final.task
            outcome["state"] = task.status.state
            reply_texts = [part.text for part in task.status.message.parts if part.text]
            if not reply_texts:
                for h in task.history:
                    if h.role == a2a_types.Role.ROLE_AGENT:
                        reply_texts.extend(part.text for part in h.parts if part.text)
            outcome["reply_text"] = "; ".join(reply_texts)
        elif final is not None and final.HasField("message"):
            outcome["reply_text"] = "; ".join(p.text for p in final.message.parts if p.text)
            outcome["state"] = None
        else:
            outcome["reply_text"] = ""
            outcome["state"] = None
        return outcome
