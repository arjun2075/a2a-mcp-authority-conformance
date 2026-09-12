# Semantic authority fixture audit

Audit performed 2026-09-12 against the uncommitted review working tree based
on `origin/main` at `9a43db3144e4a899e198be6f7e1586d57b4de4bb`.

Environment: Python 3.11.16, `a2a-sdk` 1.1.2, `mcp` 2.2.0, pytest 9.1.1.
Ruff 0.16.7 and mypy 2.3.1 were installed only in the local audit virtual
environment; the project does not add them as runtime dependencies.

## Audit 1 — semantic correctness

- Representation loss is not automatically an enforcement failure. The
  `c2-representation-lost-but-equivalently-enforced` case loses `C2` from the
  translated request, applies `POLICY-C2` through trusted downstream
  enforcement, and passes with upstream/downstream authority sizes `2/2`.
- Every passing vector satisfies the subset relation. Direct preservation is
  `2/2`, equivalent trusted enforcement is `2/2`, and stricter downstream
  enforcement is `2/1`.
- The negative case is `2/3` and reports one concrete newly permitted
  operation: a `$10.00` `store_credit` refund of `O-1001`. It is classified
  `SEMANTIC_AUTHORITY_WIDENING`.
- That negative case has valid authenticated-leaf binding. The invalid-binding
  control fails first as the existing `LEAF_DELEGATE_MISMATCH`, with no
  semantic-widening classification.
- Existing complete-chain attenuation remains `AMOUNT_SCOPE_ESCALATION`, and
  existing authenticated-leaf failure remains `LEAF_DELEGATE_MISMATCH`.
  Tests assert that both differ from `SEMANTIC_AUTHORITY_WIDENING`.
- Only fixture-local `equals` and numeric `max` constraints over the declared
  finite operation universe are compared. Neither implementation nor docs
  claim a normative protocol rule or general A2A/MCP policy equivalence.

## Audit 2 — consistency and regression

Commands and observed results:

```text
.venv/bin/python -m pytest tests/ -q
39 passed in 27.48s

(fresh copied snapshot, excluding .git/.venv/caches/traces)
.venv/bin/python -m pytest tests/ -q
39 passed in 27.17s

.venv/bin/python run_conformance.py --output <absolute-path>/audit-secure.json
exit 0; CONFORMANCE PASS

.venv/bin/python run_conformance.py --simulate-vulnerable --output <absolute-path>/audit-vulnerable.json
exit 1; VULNERABILITY DETECTED:

.venv/bin/python run_conformance.py --simulate-vulnerable-truncation --output <absolute-path>/audit-truncation.json
exit 1; VULNERABILITY DETECTED (chain truncation)

.venv/bin/python run_semantic_translation.py --output <absolute-path>/audit-semantic.json
exit 0; SEMANTIC TRANSLATION CONFORMANCE PASS; 5/5 vector expectations matched

Draft202012Validator.check_schema(schema); Draft202012Validator(schema).validate(fixture)
valid

.venv/bin/ruff check src/semantic_authority.py run_semantic_translation.py tests/test_semantic_authority.py
All checks passed!

.venv/bin/ruff format --check src/semantic_authority.py run_semantic_translation.py tests/test_semantic_authority.py
3 files already formatted

.venv/bin/mypy --strict src/semantic_authority.py run_semantic_translation.py
Success: no issues found in 2 source files

.venv/bin/python -m compileall -q src tests run_conformance.py run_semantic_translation.py
exit 0

git diff --check
exit 0
```

The full count is 27 pre-existing tests plus 12 new semantic tests. Existing
runtime modules and existing CLI options were not modified. CI receives one
additive step for the new runner. The schema, vectors, evaluator output,
tests, README, and focused documentation use the same constraint names,
failure classifications, and expected outcomes.
