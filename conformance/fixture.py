from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
from typing import Any, Mapping

from .authority import (
    AuthoritySigner,
    AuthorityViolation,
    InvalidAuthoritySignature,
    SignedAuthority,
    assert_request_is_within_authority,
)
from .constants import MCP_AUTH_EXTENSION_ID
from .protocols import (
    ProtocolShapeError,
    build_a2a_request,
    build_mcp_tool_call,
    extract_authority_from_a2a,
    extract_authority_from_mcp,
)


@dataclass
class TraceRecorder:
    scenario: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, boundary: str, event: str, data: Mapping[str, Any]) -> None:
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "time": datetime.now(timezone.utc).isoformat(),
                "boundary": boundary,
                "event": event,
                "data": copy.deepcopy(dict(data)),
            }
        )

    def to_dict(self, result: Mapping[str, Any]) -> dict[str, Any]:
        return {"scenario": self.scenario, "events": self.events, "result": dict(result)}


class FakeRefundTool:
    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    def execute(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        call = dict(arguments)
        self.calls.append(call)
        return {
            "refund_id": f"refund-{self.call_count:03d}",
            "order_id": call["order_id"],
            "amount": call["amount"],
            "currency": call["currency"],
            "status": "accepted",
        }


class AgentA:
    def __init__(self, signer: AuthoritySigner) -> None:
        self.signer = signer

    def issue_and_delegate(self, human_grant: Mapping[str, Any], trace: TraceRecorder) -> dict[str, Any]:
        signed = self.signer.sign(human_grant)
        trace.add("Human -> Agent A", "authority_issued", signed.to_dict())
        request = build_a2a_request(signed)
        trace.add("Agent A -> A2A Agent B", "a2a_send", request)
        return request


class AgentB:
    def receive_and_compose_mcp(
        self,
        a2a_request: Mapping[str, Any],
        requested_action: Mapping[str, Any],
        trace: TraceRecorder,
    ) -> dict[str, Any]:
        signed = extract_authority_from_a2a(a2a_request)
        trace.add(
            "A2A Agent B",
            "authority_received",
            {"grant_id": signed.grant.get("grant_id"), "signature": signed.signature},
        )
        mcp_request = build_mcp_tool_call(
            signed,
            tool_name=str(requested_action["tool"]),
            arguments=requested_action["arguments"],
        )
        trace.add("Agent B -> MCP", "tools_call", mcp_request)
        return mcp_request


class ConformanceMCPServer:
    def __init__(self, signer: AuthoritySigner, tool: FakeRefundTool) -> None:
        self.signer = signer
        self.tool = tool

    def handle(self, request: Mapping[str, Any], trace: TraceRecorder) -> dict[str, Any]:
        request_id = request.get("id")
        try:
            signed = extract_authority_from_mcp(request)
            self.signer.verify(signed)
            params = request["params"]
            assert_request_is_within_authority(
                signed,
                tool_name=params["name"],
                arguments=params.get("arguments", {}),
            )
            trace.add(
                "MCP server",
                "authority_verified",
                {
                    "grant_id": signed.grant.get("grant_id"),
                    "extension": MCP_AUTH_EXTENSION_ID,
                    "decision": "allow",
                },
            )
            output = self.tool.execute(params.get("arguments", {}))
            trace.add("MCP server -> Tool", "tool_executed", output)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": "Refund accepted within delegated authority."}],
                    "structuredContent": output,
                    "isError": False,
                },
            }
        except AuthorityViolation as exc:
            trace.add(
                "MCP server",
                "authority_rejected",
                {"decision": "deny", "code": exc.code, "message": exc.message},
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": f"Authority violation: {exc.message}"}],
                    "structuredContent": {"error": "authority_violation", "code": exc.code},
                    "isError": True,
                },
            }
        except InvalidAuthoritySignature as exc:
            trace.add(
                "MCP server",
                "authority_rejected",
                {"decision": "deny", "code": "INVALID_AUTHORITY_SIGNATURE", "message": str(exc)},
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": "Authority signature invalid."}],
                    "structuredContent": {"error": "authority_violation", "code": "INVALID_AUTHORITY_SIGNATURE"},
                    "isError": True,
                },
            }
        except ProtocolShapeError as exc:
            trace.add(
                "MCP server",
                "protocol_rejected",
                {"decision": "deny", "code": -32602, "message": str(exc)},
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }


@dataclass(frozen=True)
class ScenarioOutcome:
    name: str
    expected: str
    observed: str
    conformant: bool
    tool_executed: bool
    response: dict[str, Any]
    trace: dict[str, Any]


def run_scenario(scenario: Mapping[str, Any], signer: AuthoritySigner) -> ScenarioOutcome:
    name = str(scenario["name"])
    expected = str(scenario["expected"])
    trace = TraceRecorder(name)
    tool = FakeRefundTool()
    agent_a = AgentA(signer)
    agent_b = AgentB()
    server = ConformanceMCPServer(signer, tool)

    a2a_request = agent_a.issue_and_delegate(scenario["human_grant"], trace)
    mcp_request = agent_b.receive_and_compose_mcp(a2a_request, scenario["requested_action"], trace)
    response = server.handle(mcp_request, trace)

    if "error" in response:
        observed = "protocol_rejected"
    elif response["result"].get("isError"):
        observed = "authority_rejected"
    else:
        observed = "allowed"

    conformant = observed == expected
    result = {
        "expected": expected,
        "observed": observed,
        "conformant": conformant,
        "tool_executed": tool.call_count > 0,
    }
    trace.add("Fixture", "assertion", result)
    trace_dict = trace.to_dict(result)
    return ScenarioOutcome(
        name=name,
        expected=expected,
        observed=observed,
        conformant=conformant,
        tool_executed=tool.call_count > 0,
        response=response,
        trace=trace_dict,
    )
