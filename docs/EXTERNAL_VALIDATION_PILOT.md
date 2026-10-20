# External A2A→MCP authorization-preservation pilot — contract v0.1

Tracked under [issue #2](https://github.com/arjun2075/a2a-mcp-authority-conformance/issues/2), following [A2A discussion #2181](https://github.com/a2aproject/A2A/discussions/2181).

## Current status

**Design/validation contract only. No external implementation has been selected,
no external agent has been exercised, and there are no independent pilot results.**
This is neither a standardized A2A/MCP requirement nor a certification tool.

The existing loopback conformance runners and the fixture-local delegation
representation are unchanged. No adapter implementation is supplied in Stage 1.

## Files and interfaces

- `external_validation/contract.py`: conceptual adapter methods:
  `describe_target`, `prepare_case`, `run_case`,
  `collect_observations`, `cleanup`.
- `fixtures/external-validation-v0.1.json`: fixed pilot manifest V1–V7 with
  explicit attempts, expected decisions, and expected sandbox effect counts.
- `schemas/external-manifest-v0.1.schema.json`: manifest JSON Schema.
- `schemas/external-report-v0.1.schema.json`: report JSON Schema.
- `fixtures/external-validation-example-report.json`: **all NOT_EVALUATED**;
  it is an unrun example, not fabricated external results.
- `external_validation/validate.py`: structure and evidence-consistency checks.

Run locally after installing the `[test]` extras:

```bash
python -m external_validation.validate
python -m pytest tests/test_external_validation_contract.py -v
```

## Authorization and execution boundary

An operator must expressly authorize one identified target, and all potentially
state-changing operations must use sandbox, dry-run, or expressly authorized test
resources. Do not probe arbitrary public agents or conduct real financial actions.
`prepare_case` must fail or report `NOT_EVALUATED` if authorization,
instrumentation, feature support, or preconditions are absent.

The adapter must exercise the target's genuine A2A→MCP pathway, not invoke this
repository's model as a substitute for the target. It must never invent a
session principal, tool invocation, effective policy, or side effect.

## Assessment

The pilot separates:
- **Expected authorization outcome** in the manifest (`allow` / `deny`).
- **Observed enforcement decision** and independently recorded side-effect
  count on each attempt.
- **Result status** for each vector (`PASS`, `FAIL`, `NOT_EVALUATED`,
  `INCONCLUSIVE`, `ERROR`).

A negative vector that is correctly denied with zero tool effects is `PASS`.
Absent support or authorization is `NOT_EVALUATED`; insufficient observation is
`INCONCLUSIVE`; harness failures are `ERROR`. A `FAIL` needs a separately
identified and supported failure class, not merely a missing trace or a refused
tool response. A downstream representation change is not automatically a
failure if an equivalent trusted policy keeps the effective authority bounded.

For a `PASS`, the validator requires direct terminal-decision and
complete side-effect evidence tied to every attempt, not just the tool's
response. For V5/V6 it also requires observable translation and effective
downstream-policy evidence. This is a **minimum review gate**, not proof that
the observation or policy attestation is accurate. A reviewer must inspect
the evidence, the collector's access, and the claimed coverage.

Evidence is labeled separately for `basis` (direct observation, tester
interpretation, implementation self-report), `observer` (independent tester,
target operator, implementation), `method` (e.g. sandbox state diff,
instrumented trace, operator log) and `limitations`. An operator-provided log
does not become independently verified by being attached to an external report.
The `complete_effect_coverage` assertion must be justified by actual
instrumentation or a state snapshot covering the protected action. A tool
response alone does not prove an effect or the absence of an effect.

The V5/V6 pairs require the same upstream C1 resource and C2
`operation_class=original_payment_method` restriction. For V5 the omitted C2
has **no** equivalent downstream enforcement; the prohibited `store_credit`
operation must fail closed. For V6 an independently established trusted policy
enforces equivalent C2; the permissible original-payment-method operation
succeeds while the prohibited store-credit operation is denied.

## Pilot reporting constraints

Each target report must capture implementation/version, SDK or wire versions
when observable, adapter version, sanitized configuration or hash, operator
authorization/scope, trace correlation IDs, actual enforcement, effects and
missing observations. The manifest identifier and version are required; a
SHA-256 digest of the manifest may also be supplied.

Never commit credentials, private keys, PII, confidential payloads, or raw
production traces. Reports should reference only sanitized, shareable evidence.

## Next phase

After an operator opts in, create a separate implementation PR containing an
adapter, a target-specific sandbox configuration, verified evidence files, and
a report. Independently review unexpected outcomes before characterizing them
as security flaws. Do not infer normative conformance, maintainer endorsement,
or adoption from this pilot.
