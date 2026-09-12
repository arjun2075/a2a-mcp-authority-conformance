# Semantic authority under lossy A2A → MCP translation

This fixture tests one implementation-local invariant at the translation
boundary:

```text
effective_authority(downstream) ⊆ delegated_authority(upstream)
```

It does not compare A2A and MCP fields by name. It compares sets of concrete
protected operations with the same `action`, `resource`,
`operation_class`, and `amount_usd` meanings. The set is drawn from the
finite `operation_universe` declared by the fixture, so the result is
deterministic and reviewable. This is not an algorithm for comparing
arbitrary authorization policies.

## Scenario

The upstream A2A-side policy delegates `refund_order` and carries:

- `C1`: `resource == O-1001`
- `C2`: `operation_class == original_payment_method`

The reference translator preserves a constraint directly only when its
attribute is listed in that case's
`mcp_supported_constraint_attributes`. The negative case supports `resource`
but not `operation_class`, so the generated MCP-side authority representation
carries `C1` and loses the representation of `C2`.

Authentication and leaf binding are valid in that case. With no trusted
downstream replacement for `C2`, the effective downstream authority admits
this concrete operation:

```json
{
  "action": "refund_order",
  "resource": "O-1001",
  "operation_class": "store_credit",
  "amount_usd": "10.00"
}
```

The upstream authority prohibits that operation. The evaluator therefore
returns `SEMANTIC_AUTHORITY_WIDENING`. This classification is distinct from
the existing `LEAF_DELEGATE_MISMATCH` identity/binding failure and
`AMOUNT_SCOPE_ESCALATION` explicit attenuation failure.

The control case has the same wire-level representation loss, but a trusted
downstream policy enforces
`operation_class == original_payment_method`. Its effective downstream set
equals the upstream set, so the translation is conformant. An untrusted
policy entry is deliberately ignored and cannot establish equivalence.

The vectors also cover direct preservation of both constraints, invalid leaf
binding, equal authority, constraint reordering, and a strictly narrower
downstream amount policy.

## Files and execution

- `fixtures/semantic-authority-widening.json` is the executable vector set.
- `fixtures/semantic-authority-widening.schema.json` documents its JSON shape.
- `src/semantic_authority.py` contains the reference translator and evaluator.
- `run_semantic_translation.py` emits a machine-readable result.
- `tests/test_semantic_authority.py` pins the required semantics and failure
  taxonomy.

Run:

```bash
python run_semantic_translation.py
```

A zero exit means every vector matched its expected outcome, including the
expected rejection of the negative vector. The detailed result is written to
`traces/semantic-translation-result.json` by default.

## Protocol and fixture boundary

The generic ability to carry application data across A2A messages and MCP
requests comes from those protocols. `C1`, `C2`, the finite operation universe,
the translator capability declaration, the trust flag, the constraint
operators, and the subset evaluator are all fixture-local. This repository
does not claim that either protocol defines this authorization model or
requires these fields.

## Relationship to HandoffProbe

Public information was checked on 2026-09-12:

- [A2A Discussion #2181](https://github.com/a2aproject/A2A/discussions/2181)
  describes this repository's earlier narrow delegated-attenuation fixture.
- The public [HandoffProbe repository](https://github.com/Heaviside479/handoffprobe)
  describes a separate, broader adversarial security-testing tool for
  properties that cross A2A, MCP, and execution boundaries. Its published
  scope includes delegated authority, identity, tenant continuity, resource
  binding, approval, credentials, replay, cancellation, retries, and audit
  lineage, with secure and intentionally vulnerable synthetic targets.

This fixture owns only the semantic subset invariant and its deterministic
operation-set model. It neither owns HandoffProbe nor imports or duplicates
HandoffProbe's scanner, reporters, attack catalog, or CI action. Based on the
public descriptions, the artifacts are complementary: this repository gives
a small reference conformance case at the A2A→MCP translation boundary, while
HandoffProbe tests a broader collection of adjacent handoff failures. That
comparison is an inference from their documented public scopes, not a claim
of coordination, adoption, endorsement, or compatibility certification.
