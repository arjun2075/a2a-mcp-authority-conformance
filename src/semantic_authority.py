"""Fixture-scoped semantic authority comparison for lossy A2A -> MCP translation.

The model intentionally operates over a finite, fixture-declared universe of
protected operations.  It does not claim to compare arbitrary A2A and MCP
authorization languages.  A translation is conformant exactly when the set of
operations permitted after applying MCP-carried constraints and trusted
downstream enforcement is a subset of the operations permitted upstream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

SEMANTIC_AUTHORITY_WIDENING = "SEMANTIC_AUTHORITY_WIDENING"
AUTHENTICATED_LEAF_BINDING_FAILURE = "LEAF_DELEGATE_MISMATCH"
EXPLICIT_ATTENUATION_BYPASS = "AMOUNT_SCOPE_ESCALATION"


class FixtureFormatError(ValueError):
    """Raised when a semantic fixture cannot be evaluated deterministically."""


@dataclass(frozen=True)
class Constraint:
    id: str
    attribute: str
    operator: str
    value: Any

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Constraint:
        required = ("id", "attribute", "operator", "value")
        missing = [key for key in required if key not in value]
        if missing:
            raise FixtureFormatError(f"constraint missing fields: {', '.join(missing)}")
        operator = str(value["operator"])
        if operator not in {"equals", "max"}:
            raise FixtureFormatError(f"unsupported fixture operator: {operator!r}")
        return cls(
            id=str(value["id"]),
            attribute=str(value["attribute"]),
            operator=operator,
            value=value["value"],
        )

    def permits(self, operation: Mapping[str, Any]) -> bool:
        if self.attribute not in operation:
            return False
        actual = operation[self.attribute]
        if self.operator == "equals":
            return bool(actual == self.value)
        try:
            return Decimal(str(actual)) <= Decimal(str(self.value))
        except (InvalidOperation, ValueError) as exc:
            raise FixtureFormatError(
                f"constraint {self.id!r} requires decimal-compatible values"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "attribute": self.attribute,
            "operator": self.operator,
            "value": self.value,
        }


def _constraints(values: Iterable[Mapping[str, Any]]) -> tuple[Constraint, ...]:
    parsed = tuple(Constraint.from_dict(value) for value in values)
    ids = [constraint.id for constraint in parsed]
    if len(ids) != len(set(ids)):
        raise FixtureFormatError(
            "constraint ids must be unique within each constraint list"
        )
    return parsed


def _operation_key(operation: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Canonical, order-insensitive identity for one fixture operation."""
    return tuple(sorted((str(key), repr(value)) for key, value in operation.items()))


def authority(
    operation_universe: Sequence[Mapping[str, Any]],
    action: str,
    constraints: Sequence[Constraint],
) -> dict[tuple[tuple[str, str], ...], dict[str, Any]]:
    """Return concrete operations allowed by an action and constraint conjunction."""
    allowed: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
    for raw_operation in operation_universe:
        operation = dict(raw_operation)
        if operation.get("action") != action:
            continue
        if all(constraint.permits(operation) for constraint in constraints):
            allowed[_operation_key(operation)] = operation
    return allowed


def translate_constraints(
    upstream_constraints: Sequence[Constraint],
    mcp_supported_constraint_attributes: Sequence[str],
) -> tuple[Constraint, ...]:
    """Reference translation: preserve only constraints the fixture says MCP can carry."""
    supported = set(mcp_supported_constraint_attributes)
    return tuple(c for c in upstream_constraints if c.attribute in supported)


def evaluate_case(
    document: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate one translation case and return a machine-readable decision.

    Authentication/requester binding is checked first so a bad identity is not
    mislabeled as a translation failure.  Only enforcement entries explicitly
    marked trusted contribute to effective downstream authority.
    """
    upstream = document.get("upstream_authority")
    universe = document.get("operation_universe")
    if (
        not isinstance(upstream, Mapping)
        or not isinstance(universe, list)
        or not universe
    ):
        raise FixtureFormatError(
            "fixture requires upstream_authority and a non-empty operation_universe"
        )
    action = str(upstream.get("action", ""))
    if not action:
        raise FixtureFormatError("upstream_authority.action must be non-empty")

    upstream_constraints = _constraints(upstream.get("constraints", []))
    supported = case.get("mcp_supported_constraint_attributes", [])
    if not isinstance(supported, list):
        raise FixtureFormatError("mcp_supported_constraint_attributes must be a list")
    direct = translate_constraints(
        upstream_constraints, [str(item) for item in supported]
    )

    enforcement_entries = case.get("downstream_enforcement", [])
    if not isinstance(enforcement_entries, list):
        raise FixtureFormatError("downstream_enforcement must be a list")
    trusted: list[Constraint] = []
    ignored_untrusted: list[str] = []
    for entry in enforcement_entries:
        if not isinstance(entry, Mapping) or "constraint" not in entry:
            raise FixtureFormatError(
                "each downstream enforcement entry requires constraint"
            )
        constraint = Constraint.from_dict(entry["constraint"])
        if entry.get("trusted") is True:
            trusted.append(constraint)
        else:
            ignored_untrusted.append(constraint.id)

    wire_action = str(case.get("mcp_action", action))
    base_result: dict[str, Any] = {
        "name": str(case.get("name", "unnamed")),
        "translated_mcp_request_policy": {
            "action": wire_action,
            "constraints": [constraint.to_dict() for constraint in direct],
        },
        "directly_represented_constraint_ids": [constraint.id for constraint in direct],
        "representation_lost_constraint_ids": [
            constraint.id
            for constraint in upstream_constraints
            if constraint not in direct
        ],
        "trusted_downstream_constraint_ids": [constraint.id for constraint in trusted],
        "ignored_untrusted_constraint_ids": ignored_untrusted,
    }

    if case.get("authenticated_leaf_bound") is not True:
        return {
            **base_result,
            "conformant": False,
            "classification": AUTHENTICATED_LEAF_BINDING_FAILURE,
            "reason": "authenticated requester is not bound to the delegated leaf",
            "newly_permitted_operations": [],
        }

    upstream_allowed = authority(universe, action, upstream_constraints)
    downstream_allowed = authority(universe, wire_action, (*direct, *trusted))
    widened_keys = sorted(set(downstream_allowed).difference(upstream_allowed))
    widened = [downstream_allowed[key] for key in widened_keys]
    conformant = not widened
    result = {
        **base_result,
        "conformant": conformant,
        "classification": None if conformant else SEMANTIC_AUTHORITY_WIDENING,
        "reason": (
            "effective downstream authority is a subset of upstream delegated authority"
            if conformant
            else "loss of upstream semantics permits concrete operations prohibited upstream"
        ),
        "upstream_authority_size": len(upstream_allowed),
        "effective_downstream_authority_size": len(downstream_allowed),
        "newly_permitted_operations": widened,
    }

    expected_witness = case.get("expected_witness_operation")
    if expected_witness is not None:
        result["expected_witness_demonstrated"] = _operation_key(expected_witness) in {
            _operation_key(operation) for operation in widened
        }
    return result


def evaluate_fixture(document: Mapping[str, Any]) -> dict[str, Any]:
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FixtureFormatError("fixture requires a non-empty cases list")
    results = [evaluate_case(document, case) for case in cases]
    expectation_matches = []
    for case, result in zip(cases, results):
        expected = case.get("expected")
        if expected not in {"PASS", "FAIL"}:
            raise FixtureFormatError(
                f"case {result['name']!r} expected must be PASS or FAIL"
            )
        expected_conformant = expected == "PASS"
        match = result["conformant"] is expected_conformant
        if "expected_classification" in case:
            match = (
                match and result["classification"] == case["expected_classification"]
            )
        if case.get("expected_witness_operation") is not None:
            match = match and result.get("expected_witness_demonstrated") is True
        result["expected"] = expected
        result["expectation_matched"] = match
        expectation_matches.append(match)
    return {
        "fixture": str(document.get("fixture", "unnamed")),
        "invariant": "effective_authority(downstream) ⊆ delegated_authority(upstream)",
        "result": "pass" if all(expectation_matches) else "fail",
        "case_count": len(results),
        "cases": results,
    }
