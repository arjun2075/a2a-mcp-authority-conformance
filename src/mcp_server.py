"""Real MCP server (official `mcp` SDK, streamable-http transport).

Exposes one tool, `refund_order(order_id, amount_usd)`. Protocol-defined
behavior used here: MCP `tools/call`, the tool registration decorator, and
the generic per-request `_meta` object. Everything about *what* is stored
under our namespaced `_meta` key, and how it is evaluated, is fixture-local
policy (see src/authority.py's module docstring).

This is the MCP-side policy enforcement point (PEP): it is the last place
that can stop the forbidden tool side effect before it happens.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.server import ToolError
from mcp.server.mcpserver.context import Context

from authority import (
    AuthorityViolation,
    AuthoritySigner,
    DelegationChain,
    InvalidAuthoritySignature,
    assert_request_is_within_authority,
    assert_request_is_within_authority_vulnerable,
    assert_request_is_within_authority_truncation_vulnerable,
)
from constants import MCP_DELEGATION_META_KEY
from refund_tool import RefundLedger

SIGNING_KEY = os.environ.get("FIXTURE_SIGNING_KEY", "fixture-only-secret-not-for-production").encode("utf-8")
VULNERABLE_MODE = os.environ.get("FIXTURE_SIMULATE_VULNERABLE") == "1"
VULNERABLE_TRUNCATION_MODE = os.environ.get("FIXTURE_SIMULATE_VULNERABLE_TRUNCATION") == "1"

if VULNERABLE_MODE and VULNERABLE_TRUNCATION_MODE:
    # The two vulnerable modes model different bugs and would select different
    # checkers. Refusing here keeps mode selection deterministic even when this
    # server is started directly via env vars rather than through
    # run_conformance.py (which rejects the same combination at the CLI).
    raise SystemExit(
        "FIXTURE_SIMULATE_VULNERABLE and FIXTURE_SIMULATE_VULNERABLE_TRUNCATION are mutually "
        "exclusive; set at most one."
    )

signer = AuthoritySigner(SIGNING_KEY)
ledger = RefundLedger()

mcp = MCPServer("a2a-mcp-authority-conformance-refund-server")


@mcp.tool()
def refund_order(order_id: str, amount_usd: str, ctx: Context) -> dict:
    """Refund an order, but only within the effective delegated authority carried in _meta."""
    meta = dict(ctx.request_context.meta) if ctx.request_context.meta else {}
    chain_wire = meta.get(MCP_DELEGATION_META_KEY)
    if chain_wire is None:
        raise ToolError("DENY: request dropped delegation-chain metadata (MISSING_DELEGATION_METADATA)")

    try:
        chain = DelegationChain.from_wire(chain_wire)
        if VULNERABLE_TRUNCATION_MODE:
            checker = assert_request_is_within_authority_truncation_vulnerable
        elif VULNERABLE_MODE:
            checker = assert_request_is_within_authority_vulnerable
        else:
            checker = assert_request_is_within_authority
        ceiling = checker(
            signer,
            chain,
            tool_name="refund_order",
            arguments={"order_id": order_id, "amount_usd": amount_usd},
        )
    except (AuthorityViolation, InvalidAuthoritySignature) as exc:
        code = getattr(exc, "code", exc.__class__.__name__.upper())
        raise ToolError(f"DENY: {exc} ({code})") from exc

    record = ledger.execute(order_id=order_id, amount_usd=amount_usd)
    return {
        "decision": "allow",
        "effective_authority_usd": str(ceiling),
        "refund": record,
    }


def reset_ledger() -> None:
    ledger.calls.clear()


if __name__ == "__main__":
    port = int(os.environ.get("FIXTURE_MCP_PORT", "8931"))
    mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
