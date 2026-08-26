# A2A → MCP Delegated-Authority Conformance Fixture

A single executable conformance scenario. It proves that a **narrowed
delegated authority** survives a real, multi-hop agent-to-agent and
agent-to-tool composition:

```text
Human  →  Agent A  →  A2A  →  Agent B  →  MCP  →  refund_order tool
```

using the **official A2A and MCP SDKs** over real sockets — not handwritten
HTTP/JSON-RPC shims.

This is a conformance test, not a framework, not a new protocol, and not a
standardization proposal. See [HO-005 gate status](#ho-005-gate-status)
below.

## The scenario: "Refund Cap Must Survive A2A → MCP"

```text
Human authorizes Agent A:      refund order O-1001, max $25.00
Agent A delegates to Agent B:  refund order O-1001, max $20.00
Effective Agent B authority:   min($25.00, $20.00) = $20.00
```

| Attempt | Amount | Against human root ($25) | Against delegated authority ($20) | Decision |
|---|---|---|---|---|
| Valid   | $18.00 | within  | within  | **ALLOW** — tool executes exactly once |
| Invalid | $22.00 | within  | **exceeds** | **DENY** — tool must not execute |

The invalid case is deliberately designed so that `$22 <= $25` is true. A
broken implementation that checks only the human root grant would
incorrectly allow it. The correct effective authority is the **intersection
across the whole delegation chain**, not just its root or just its leaf.

## Protocol-defined behavior vs. fixture-local behavior

This distinction matters and is enforced throughout the code:

**Protocol-defined** (real A2A / MCP semantics, used as-is):
- A2A: `AgentCard`, `AgentExecutor`, `SendMessageRequest`/`Message`,
  `contextId`/`taskId`, the JSON-RPC transport, and the generic
  `AgentExtension` / `Message.metadata` mechanism.
- MCP: `ClientSession`, the streamable-HTTP transport, `tools/call`, tool
  registration, and the generic per-request `_meta` object.

**Fixture-local** (this repo's own test scaffolding, NOT part of either
protocol):
- The delegation-chain JSON schema (`grant`, `signature`, `algorithm`;
  `issuer`, `delegate`, `parent`, `action`, `resource`, `max_amount_usd`,
  `max_uses`).
- The HMAC-SHA256 signing method (a deterministic test integrity primitive
  — **not production cryptography**: no asymmetric keys, no key management,
  no revocation, no replay protection).
- The attenuation rule (each link may only narrow, never widen, its
  parent's authority) and the effective-authority algorithm
  (`min()` across the whole chain).
- The two carrier keys used to place the chain on the wire:
  - A2A: `https://example.org/a2a/extensions/delegation-chain/v1`, an
    `AgentExtension` URI, with the payload under
    `Message.metadata[<that URI>]`.
  - MCP: `io.example.a2a-mcp-conformance/delegation-chain`, a namespaced
    key under `CallToolRequestParams._meta`.

**This repository does not claim that A2A or MCP standardize this
delegation representation.** It tests whether an implementation *built on
top of* their existing, protocol-legal extension/metadata mechanisms can
preserve and enforce a narrowed delegated authority across both boundaries.

**This fixture tests whether narrowed delegated authority can be preserved
and enforced across A2A and MCP protocol boundaries.**

## SDKs used (exact versions)

Installed and verified against, from a clean virtualenv on Python 3.11:

| Package | Version | Role |
|---|---|---|
| [`a2a-sdk`](https://pypi.org/project/a2a-sdk/) | **1.1.2** | Official A2A SDK — client (`a2a.client`) and server (`a2a.server`) |
| [`mcp`](https://pypi.org/project/mcp/) | **2.1.1** | Official MCP SDK — client (`mcp.client`) and server (`mcp.server.mcpserver`) |
| `httpx` | 0.28.1 | HTTP transport for the A2A client |
| `uvicorn` | 0.52.4 | ASGI server hosting Agent B's A2A endpoint |
| `starlette` | 1.6.0 | Routing for Agent B's A2A endpoint (via `a2a-sdk`'s route builders) |

The A2A and MCP wire-protocol versions actually negotiated at runtime are
read from the SDKs at runtime (not hard-coded) and reported in every run's
JSON result under `protocols.a2a_wire_protocol` / `protocols.mcp_wire_protocol`
— observed as `1.0` and `2026-07-28` respectively with the pinned SDK
versions above. `a2a-sdk` 1.x represents A2A messages as protobuf-generated
Python types (`a2a.types`, backed by `a2a_pb2`); this fixture uses that
representation directly rather than the legacy JSON-only 0.x surface.

## Architecture

```text
Human (test driver in run_conformance.py)
  │  issues + signs: root grant (human-approval → agent-a, ≤ $25.00)
  │                  child grant (agent-a → agent-b, ≤ $20.00)
  ▼
Agent A (src/agent_a.py)
  │  a2a.client.ClientFactory → real A2A SendMessage (JSON-RPC over HTTP)
  │  delegation chain carried in Message.metadata["https://.../delegation-chain/v1"]
  ▼
Agent B — a real A2A server (src/agent_b.py, uvicorn + a2a-sdk routes)
  │  AgentExecutor.execute() receives the A2A message
  │  mcp.ClientSession → real MCP tools/call over streamable-HTTP
  │  same delegation chain forwarded, unmodified, in
  │  CallToolRequestParams._meta["io.example.a2a-mcp-conformance/delegation-chain"]
  ▼
MCP server (src/mcp_server.py, mcp.server.mcpserver.MCPServer)
  │  refund_order(order_id, amount_usd) tool
  │  policy enforcement point: src/authority.py verifies the whole chain
  │  (signatures, parent binding, issuer/delegate continuity, monotonic
  │  attenuation, leaf delegate) and computes effective authority = min(chain)
  ▼
Tool side effect (src/refund_tool.py::RefundLedger)
  only reached if amount_usd <= effective authority
```

Every hop above is a real network call over a real socket (HTTP/1.1,
loopback) driven by the official SDK on both ends — `run_conformance.py`
starts the MCP server and Agent B's A2A server as subprocesses bound to
free ports, then drives Agent A as a client against Agent B.

## Repository layout

```text
a2a-mcp-authority-conformance/
├── README.md
├── pyproject.toml
├── src/
│   ├── authority.py      # fixture-local delegation-chain model + PEP (protocol-agnostic)
│   ├── constants.py       # namespaced metadata keys (fixture-local)
│   ├── agent_a.py         # real A2A client: issues chain, sends A2A message
│   ├── agent_b.py         # real A2A server + real MCP client
│   ├── mcp_server.py       # real MCP server exposing refund_order
│   └── refund_tool.py      # the tool-side side-effect ledger
├── tests/
│   ├── test_authority.py    # unit tests for the policy-enforcement logic
│   └── test_conformance.py  # end-to-end test driving the real server processes
├── run_conformance.py       # orchestrates the full scenario, emits JSON result
└── .github/workflows/conformance.yml
```

## How to run (from a clean checkout)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"

# unit + end-to-end tests
python -m pytest tests/ -v

# secure implementation
python run_conformance.py
# -> exit 0, prints "CONFORMANCE PASS"

# vulnerability detector: intentionally-broken variant that checks
# only the human root grant and ignores the agent-a -> agent-b attenuation
python run_conformance.py --simulate-vulnerable
# -> exit 1 (non-zero), prints "VULNERABILITY DETECTED"
```

Both commands write a machine-readable result to `traces/result.json`
(path configurable via `--output`), for example:

```json
{
  "scenario": "refund-cap-survives-a2a-mcp",
  "protocols": {
    "a2a": "1.1.2",
    "a2a_wire_protocol": "1.0",
    "mcp": "2.1.1",
    "mcp_wire_protocol": "2026-07-28"
  },
  "human_limit": 25.0,
  "delegated_limit": 20.0,
  "valid_attempt": 18.0,
  "invalid_attempt": 22.0,
  "valid_decision": "allow",
  "invalid_decision": "deny",
  "invalid_tool_side_effects": 0,
  "result": "pass"
}
```

## Enforcement rule (src/authority.py)

The MCP-side policy enforcement point (`assert_request_is_within_authority`)
verifies, for every request:

- valid HMAC signature on every link in the chain
- correct parent binding (`child.parent == hash(parent.grant)`)
- correct issuer/delegate chain (`child.issuer == parent.delegate`)
- correct action and resource, unchanged across every link
- non-increasing `max_amount_usd` at every hop
- non-increasing `max_uses` at every hop
- leaf delegate equals the expected caller (`agent-b`)
- `requested amount <= effective authority`, where effective authority is
  `min()` over every link's `max_amount_usd` — **not** the leaf's claim and
  **not** the root's ceiling alone.

`assert_request_is_within_authority_vulnerable` is the intentionally broken
counterpart used only by `--simulate-vulnerable`: it verifies only the
human root grant and never consults the agent-a → agent-b delegation at
all, so a widened downstream request that still fits under the root limit
is (incorrectly) allowed. It exists solely to demonstrate that the negative
test in `run_conformance.py` can actually detect this class of bug — see
the vulnerability-detector output below.

Signing is a deterministic HMAC-SHA256 over canonical JSON. **This is a test
integrity primitive, not a production trust model.** A production system
would need real asymmetric signatures, key management, revocation, and
replay protection — none of which this fixture provides or claims to
provide.

## Observed results (this checkout)

### Secure implementation

```text
[valid $18 attempt]   decision=allow reply='{"decision": "allow", "effective_authority_usd": "20.00", "refund": {"order_id": "O-1001", "amount_usd": "18.00", "refund_id": "refund-001"}}'
[invalid $22 attempt] decision=deny  reply='Error executing tool refund_order: DENY: requested amount_usd 22.00 exceeds effective delegated authority 20.00 (root=25.00, leaf=20.00) (AMOUNT_SCOPE_ESCALATION)'

CONFORMANCE PASS
  valid:   $18.00 <= delegated $20.00 -> ALLOW, tool executed
  invalid: $22.00 <= human root $25.00 but > delegated $20.00 -> DENY, tool NOT executed
```

Exit code: `0`.

### Vulnerable mode (`--simulate-vulnerable`)

```text
[valid $18 attempt]   decision=allow reply='{"decision": "allow", "effective_authority_usd": "25.00", ...}'
[invalid $22 attempt] decision=allow reply='{"decision": "allow", "effective_authority_usd": "25.00", "refund": {"order_id": "O-1001", "amount_usd": "22.00", "refund_id": "refund-002"}}'

VULNERABILITY DETECTED: $22 request was allowed while only checking the $25 human root grant.
This is the expected outcome for --simulate-vulnerable: it proves the negative test can catch it.
```

Exit code: `1`.

## CI

`.github/workflows/conformance.yml` runs on every push/PR across Python
3.11–3.13 and asserts:

1. `python -m pytest tests/ -v` passes (unit tests for the authority model
   plus an end-to-end test that drives the real server processes).
2. `python run_conformance.py` exits `0` with `CONFORMANCE PASS`.
3. `python run_conformance.py --simulate-vulnerable` exits non-zero — CI
   fails if the vulnerable variant is incorrectly accepted as passing.

## Deviations from the originally sketched layout

- `a2a-sdk` 1.x represents protocol messages as protobuf-generated types
  rather than plain JSON dicts. `SendMessageConfiguration`,
  `AgentCapabilities.extensions`, etc. are all protobuf messages. This
  fixture uses them directly (no re-wrapping) — see the comment in
  `src/authority.py` explaining why every signed grant scalar is a JSON
  *string*: `Message.metadata` is a `google.protobuf.Struct`, whose only
  numeric type is `double`, so a bare JSON integer would silently become
  `1.0` after crossing the real A2A hop and invalidate its own HMAC
  signature. This is a real, observed protocol-boundary effect, not a
  workaround for a fixture bug.
- Agent B is implemented as a single-turn `AgentExecutor` that completes
  the task in one `execute()` call (no multi-turn / `input-required` flow),
  since the scenario itself is a single request-response per attempt.
- The MCP server surfaces authority denials via `mcp.server.mcpserver.server.ToolError`,
  which the SDK converts into a clean `isError: true` `CallToolResult`
  rather than a raw exception traceback reaching the client.

## Known limitations

- HMAC-SHA256 signing is a test-only integrity primitive; there is no key
  rotation, revocation, or replay protection.
- The MCP and A2A servers run as local subprocesses on loopback for the
  duration of one conformance run; this is a fixture harness, not a
  deployable service.
- Only the two scenario amounts ($18 valid, $22 invalid) are exercised by
  the end-to-end path; broader boundary/fuzz coverage of the authority
  model lives in `tests/test_authority.py` as fast, non-networked unit
  tests.

## HO-005 gate status

No standardization or publication proposal is made by this repository.
No new A2A extension standard, no new MCP standard, and no specification
are proposed or submitted upstream. This is one executable conformance
scenario testing whether an implementation *built on top of* A2A's and
MCP's existing extension/metadata mechanisms can preserve a narrowed
delegated authority across both boundaries. Overlap analysis with HO-005
is still required before any broader claim, generalization, or upstream
submission.
