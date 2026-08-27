# Verification Results

Factual record of a verification pass performed against this repository.
No marketing language; observed values only.

## Environment

- Verification date: 2026-08-26
- Git commit SHA verified: `319647cc8955959c2834c83e0ca49ed8a2551b47`
- Python: 3.11.14
- `a2a-sdk`: **1.1.2** (via `importlib.metadata.version("a2a-sdk")` and `pip freeze`)
- `mcp`: **2.1.1** (via `importlib.metadata.version("mcp")` and `pip freeze`)
- `mcp-types`: 2.1.1 (transitive, via `pip freeze`)

Declared constraints in `pyproject.toml`: `a2a-sdk>=1.1.2,<2`, `mcp>=2.1.1,<3`.
No requirements files or lockfiles are present in this repository. The prior
completion report's claim of `mcp 2.1.1` was checked directly against the
installed environment and is **correct** — no version correction was
required.

## Clean-checkout reproduction

Performed in a fresh `git clone` outside the working tree (`mktemp -d`),
using only the documented README steps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

- Install result: succeeded, no errors.
- `python -m pytest tests/ -v`: **12 passed**, 0 failed.
- `python run_conformance.py` exit code: **0**
- `python run_conformance.py --simulate-vulnerable` exit code: **1** (captured directly, not through a pipe)

## Secure conformance run

Command: `python run_conformance.py`

- `$18.00` request: **ALLOW** — tool executed once, `refund-001`, `amount_usd: "18.00"`.
- `$22.00` request: **DENY** — reason: `AMOUNT_SCOPE_ESCALATION`, "requested amount_usd 22.00 exceeds effective delegated authority 20.00 (root=25.00, leaf=20.00)".
- Invalid-trace tool side effects: **0**.
- Machine-readable result (`traces/result.json`): `"result": "pass"`, `"valid_decision": "allow"`, `"invalid_decision": "deny"`, `"invalid_tool_side_effects": 0`.
- Exit code: **0**.

## Vulnerability-detector run

Command: `python run_conformance.py --simulate-vulnerable`

- `$18.00` request: ALLOW (effective_authority_usd reported as `25.00`, i.e. root-only enforcement).
- `$22.00` request: **ALLOW** — the forbidden refund executed (`refund-002`, `amount_usd: "22.00"`) under intentionally vulnerable root-only enforcement.
- Invalid-trace tool side effects: **1** (the forbidden side effect occurred).
- Machine-readable result: `"result": "fail"`, `"invalid_decision": "allow"`, `"invalid_tool_side_effects": 1`.
- Exit code: **1** (non-zero, captured directly).
- The runner printed `VULNERABILITY DETECTED: $22 request was allowed while only checking the $25 human root grant.`

This demonstrates the conformance test is sensitive to the exact bug class
under test: an implementation that checks only the human root grant and
ignores intermediate delegation attenuation is detected and fails.

## Real SDK usage confirmed

- **A2A**: `src/agent_a.py` uses `a2a.client.ClientFactory` / `create_from_url` / `Client.send_message` over a real `httpx.AsyncClient`, sending a genuine `SendMessageRequest` to Agent B's real HTTP endpoint. `src/agent_b.py` is a real A2A server built from `a2a.server.agent_execution.AgentExecutor`, `a2a.server.request_handlers.DefaultRequestHandlerV2`, `a2a.server.routes.create_agent_card_routes` / `create_jsonrpc_routes`, and `a2a.server.tasks.TaskUpdater`, run under `uvicorn` as a real subprocess.
- **MCP**: `src/agent_b.py`'s executor uses `mcp.client.streamable_http.streamable_http_client` and `mcp.ClientSession.call_tool` to make a genuine `tools/call` over the streamable-HTTP transport against a real MCP server. `src/mcp_server.py` is built from `mcp.server.mcpserver.MCPServer`, registering `refund_order` as a real tool and reading delegation metadata from the real per-request `_meta` via `ctx.request_context.meta`.
- Both servers (`mcp_server`, `agent_b`) are started by `run_conformance.py` as real OS subprocesses (`subprocess.Popen`) bound to dynamically allocated free ports, not invoked as in-process function calls. The only direct (non-network) Python calls in the runtime path are internal policy/helper functions inside `src/authority.py` (signature verification, chain validation, effective-authority computation) — these are policy logic, not substitutes for either protocol boundary.

## Delegation chain verified across both boundaries

- Agent A (`src/agent_a.py::issue_delegation_chain`) signs a two-link chain: root grant (`issuer=human-approval`, `delegate=agent-a`, `max_amount_usd=25.00`) and child grant (`issuer=agent-a`, `delegate=agent-b`, `parent=hash(root)`, `max_amount_usd=20.00`).
- Agent A attaches the full chain (`chain.to_wire()`) to the outgoing A2A `Message.metadata` under the fixture-local extension URI.
- Agent B's `execute()` reads that exact object out of the received A2A message's metadata (`delegation_chain_wire = metadata.get(A2A_DELEGATION_EXTENSION_URI)`) and forwards it, unmodified, into the MCP `_meta` object of its outgoing `tools/call`. No new or broader grant is constructed at Agent B.
- The MCP server (`src/mcp_server.py`) reconstructs the chain from `_meta` via `DelegationChain.from_wire` and re-verifies it in full (`authority.assert_request_is_within_authority`) rather than trusting any single link.
- `effective_authority()` computes `min()` over every link's `max_amount_usd` — confirmed as `min($25.00, $20.00) = $20.00` in the secure run's `effective_authority_usd: "20.00"` output. The secure path does not authorize against `$25` alone.

## Security assertions confirmed present (`src/authority.py::verify_chain` / `assert_request_is_within_authority`)

- Signature integrity: `signer.verify()` on every link.
- Parent binding: `grant["parent"] == hash_grant(previous.grant)`.
- Issuer/delegate sequence: `grant["issuer"] == previous.grant["delegate"]`.
- Action and resource: unchanged across every link (`ACTION_SCOPE_ESCALATION`, `RESOURCE_SCOPE_ESCALATION`).
- Non-increasing `max_amount_usd` (`AMOUNT_NOT_ATTENUATED`).
- Non-increasing `max_uses` (`USES_NOT_ATTENUATED`).
- Leaf delegate equals `agent-b` (`LEAF_DELEGATE_MISMATCH`).
- Requested amount `<=` effective delegated amount (`AMOUNT_SCOPE_ESCALATION`).

## Protobuf metadata / signature regression

Confirmed and now covered by a dedicated test:
`tests/test_authority.py::test_signature_survives_a_real_protobuf_struct_round_trip`.

This test round-trips a signed grant through a real
`google.protobuf.struct_pb2.Struct` (via `google.protobuf.json_format.MessageToDict`,
the same conversion path used in production) and asserts the signature
still verifies and every grant field is byte-identical afterward. A
manual sanity check (not part of the committed test suite) confirmed the
test is not vacuous: substituting a JSON integer for `max_uses` instead of
the fixture's JSON string reproduces the original bug (`1` becomes `1.0`
after the Struct round trip) and causes `InvalidAuthoritySignature`,
proving this test would catch a regression of the original fix. Every
signed grant scalar remains a JSON string, as documented in the
module-level comment above `DelegationChain` in `src/authority.py`; this
was preserved, not altered.

## README accuracy

Confirmed `README.md`:
- Distinguishes protocol-defined behavior (A2A messaging, A2A metadata/extensions, MCP `tools/call`, MCP metadata transport) from fixture-local behavior (delegation-chain schema, grant format, signing method, authority intersection, attenuation rules, policy enforcement) in dedicated sections.
- States verbatim: "This repository does not claim that A2A or MCP standardize this delegation representation."
- States verbatim: "This fixture tests whether narrowed delegated authority can be preserved and enforced across A2A and MCP protocol boundaries."
- Reports SDK versions (`a2a-sdk` 1.1.2, `mcp` 2.1.1, plus `httpx`/`uvicorn`/`starlette`) matching the versions verified above.

## CI logic

`.github/workflows/conformance.yml` (Python 3.11–3.13 matrix):
1. Installs dependencies via `pip install -e ".[test]"`.
2. Runs `python -m pytest tests/ -v`.
3. Runs `python run_conformance.py` as a plain step — a non-zero exit here fails the job.
4. Runs `python run_conformance.py --simulate-vulnerable` inside an `if`/`else` shell guard that explicitly fails the job (`exit 1`) if the vulnerable run exits zero, and succeeds only if it exits non-zero.

The CI job as a whole passes only when the secure implementation passes
AND the intentionally vulnerable implementation is correctly detected as
non-conformant. No changes to CI were required.

## Summary of corrections made during this verification pass

- Added one focused regression test for the protobuf `Struct` round-trip
  signature-stability property (`tests/test_authority.py`).
- Tightened two sentences in `README.md` to match the required exact
  phrasing on non-standardization and fixture purpose.
- No version numbers were changed — `mcp 2.1.1` was verified as accurate,
  not corrected.
