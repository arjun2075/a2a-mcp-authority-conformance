# A2A -> MCP Delegated-Authority Conformance Fixture

A minimal runnable fixture that tests one interoperability property:

> A downstream A2A agent and MCP tool invocation must not gain more authority than the human granted upstream.

This is **not** a full A2A implementation, full MCP implementation, authorization framework, or protocol proposal. It is a small reference boundary that emits current wire-shaped A2A and MCP messages and mechanically checks one authority invariant.

## Versions locked for fixture #1

- A2A: tested against the A2A v1.x semantics relevant to this fixture; current protocol release at review time: `v1.0.1` (protocol version header `1.0`)
- MCP: latest revision `2026-07-28`

See `SPEC_NOTES.md` for source links and the exact specification observations used.

## Scenario

The human grants Agent A permission to delegate one bounded refund action:

- tool: `refund_payment`
- resource: `ORDER-1001`
- currency: `USD`
- maximum amount: `50.00`
- approved delegation path includes `agent-a` and `agent-b`
- privilege escalation is forbidden

Agent A signs this authority and sends it to Agent B inside an A2A 1.0 message extension. Agent B composes a current MCP `tools/call` request and carries the unchanged signed authority in namespaced MCP `_meta`. The MCP server verifies the signature and checks the requested tool arguments before the fake tool can run.

### Valid trace

Requested refund: `35.00 USD` for `ORDER-1001` using `refund_payment`.

Expected: allowed. The actual action is a strict attenuation of the human grant because `35.00 <= 50.00` and all exact-match constraints remain unchanged.

### Invalid trace

Requested refund: `75.00 USD` for `ORDER-1001` using `refund_payment`.

Expected: rejected as `AMOUNT_SCOPE_ESCALATION`; the fake tool call count must remain zero.

## Authority invariant

For every downstream tool invocation `R` and upstream signed human grant `G`:

`authority(R) <= authority(G)`

For this fixture, that means all of the following must hold at the MCP enforcement boundary:

1. the signed grant has not been modified;
2. requested tool equals the granted tool;
3. executing delegate is in the approved delegation path;
4. requested order equals the granted order;
5. requested currency equals the granted currency;
6. requested amount is non-negative and no greater than the granted maximum;
7. if authority metadata is dropped at the A2A -> MCP composition boundary, execution is rejected rather than silently continuing.

Any downstream request that violates one of these constraints is an escalation, not an attenuation.

## Architecture

```text
Human approval
    |
    v
Agent A / authority issuer
    |  A2A 1.0 HTTP+JSON POST /message:send
    |  Message.extensions + Message.metadata
    v
Agent B / A2A receiver + MCP client
    |  MCP 2026-07-28 JSON-RPC tools/call
    |  required per-request _meta + fixture extension metadata
    v
MCP server / enforcement point
    |  verify signature + subset/attenuation assertions
    v
Fake refund tool
```

A deterministic HMAC is used only as a fixture integrity primitive so Agent B cannot change the grant without detection. It is not a recommended production credential format.

## Run

Requirements: Python 3.11+; no third-party dependencies.

From the repository root:

```bash
python run_conformance.py
```

Expected summary:

```text
[PASS] valid_attenuated_refund: expected=allowed observed=allowed tool_executed=True
[PASS] invalid_amount_escalation: expected=authority_rejected observed=authority_rejected tool_executed=False

CONFORMANCE PASS
  valid: delegated authority preserved and attenuated (35.00 <= 50.00)
  invalid: escalation detected and tool execution blocked (75.00 > 50.00)
```

Machine-readable traces are written to:

- `traces/valid_input.trace.json`
- `traces/invalid_input.trace.json`

## Tests

Run all mechanical assertions with one command:

```bash
python -m unittest discover -s tests -v
```

The tests cover:

- valid attenuation executes the tool;
- invalid amount escalation is rejected before tool execution;
- tampering with the signed A2A authority is rejected;
- dropping authority at the MCP boundary is rejected as malformed composition;
- changing the authorized resource is rejected.

## Protocol-shape choices

### A2A boundary

The fixture uses the standard A2A 1.0 HTTP+JSON Send Message shape:

- `POST /message:send`
- `Content-Type: application/a2a+json`
- `A2A-Version: 1.0`
- `A2A-Extensions: <fixture extension URI>`
- `message.messageId`, `role`, `parts`, `extensions`, `metadata`

The fixture-local authority object is stored under the same extension URI in message metadata, following A2A's extension model. `examples/agent_b_card.json` shows the corresponding extension declaration.

### MCP boundary

The fixture uses the current MCP `tools/call` shape:

- JSON-RPC `2.0`
- method `tools/call`
- `params.name`
- `params.arguments`
- required `params._meta`
- `io.modelcontextprotocol/protocolVersion = 2026-07-28`
- `io.modelcontextprotocol/clientCapabilities`
- namespaced fixture extension metadata `org.example.a2a-mcp/delegated-authority`

An authorization denial is returned as a tool execution error (`isError: true`); malformed protocol/composition state uses JSON-RPC `-32602`.

## What the fixture proves

It proves that a composition layer **can** preserve a bounded human grant across an A2A -> MCP transition and mechanically prevent an attempted downstream escalation, without implementing either full protocol stack.

It also shows the interoperability gap: neither A2A nor MCP core semantics define this cross-protocol authority object's constraint algebra or automatic propagation rule. A2A provides an extension point and explicitly leaves approval scope semantics open; MCP provides per-request metadata/extensions and requires access controls, but the composition must define, carry, integrity-protect, and enforce the authority relationship.

## Limitations

- The A2A and MCP transports are wire-shape simulators, not network servers.
- The HMAC key lives in the same process for deterministic tests; production systems should use a real trust boundary (for example, asymmetric signatures, token exchange, or an authorization service).
- Only one constraint algebra is tested: exact tool/resource/currency plus a numeric upper bound.
- Revocation, expiry, replay defense, identity binding, multi-hop depth, and user re-approval are not yet modeled.
- This fixture does not claim that the extension identifiers or authority schema should be standardized.

## Publication gate

Do not turn these findings into broad standards claims, an upstream proposal, or a compatibility claim until HO-005 / overlap review is complete.

## Next iteration after fixture #1

The second most valuable case is **lost approval / fresh authority required for a destructive follow-up**: Agent B first performs an allowed read or quote operation, then attempts a destructive `commit_payment` or `refund_payment` action without a distinct human approval for that action. The fixture should prove that prior authority for the read/quote step cannot be silently reused as authority for the destructive step.
