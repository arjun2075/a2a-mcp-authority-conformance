"""Semantic authority tests for lossy, fixture-scoped A2A -> MCP translation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semantic_authority import (
    AUTHENTICATED_LEAF_BINDING_FAILURE,
    EXPLICIT_ATTENUATION_BYPASS,
    SEMANTIC_AUTHORITY_WIDENING,
    evaluate_case,
    evaluate_fixture,
)


def load_fixture() -> dict:
    return json.loads(
        (ROOT / "fixtures" / "semantic-authority-widening.json").read_text()
    )


def case_named(document: dict, name: str) -> dict:
    return next(case for case in document["cases"] if case["name"] == name)


def test_c1_and_c2_preserved_directly_passes_with_equal_authority():
    document = load_fixture()
    result = evaluate_case(
        document, case_named(document, "c1-and-c2-preserved-directly")
    )
    assert result["conformant"] is True
    assert result["classification"] is None
    assert (
        result["upstream_authority_size"]
        == result["effective_downstream_authority_size"]
    )
    assert result["directly_represented_constraint_ids"] == ["C1", "C2"]


def test_c2_absent_from_wire_but_equivalently_enforced_passes():
    document = load_fixture()
    result = evaluate_case(
        document,
        case_named(document, "c2-representation-lost-but-equivalently-enforced"),
    )
    assert result["conformant"] is True
    assert result["representation_lost_constraint_ids"] == ["C2"]
    assert result["trusted_downstream_constraint_ids"] == ["POLICY-C2"]
    assert [
        constraint["id"]
        for constraint in result["translated_mcp_request_policy"]["constraints"]
    ] == ["C1"]
    assert (
        result["upstream_authority_size"]
        == result["effective_downstream_authority_size"]
    )


def test_c2_absent_and_unenforced_fails_with_concrete_new_operation():
    document = load_fixture()
    result = evaluate_case(
        document, case_named(document, "c2-lost-without-equivalent-enforcement")
    )
    assert result["conformant"] is False
    assert result["classification"] == SEMANTIC_AUTHORITY_WIDENING
    assert result["expected_witness_demonstrated"] is True
    assert {
        "action": "refund_order",
        "resource": "O-1001",
        "operation_class": "store_credit",
        "amount_usd": "10.00",
    } in result["newly_permitted_operations"]


def test_valid_authentication_does_not_mask_semantic_widening():
    document = load_fixture()
    case = case_named(document, "c2-lost-without-equivalent-enforcement")
    assert case["authenticated_leaf_bound"] is True
    result = evaluate_case(document, case)
    assert result["classification"] == SEMANTIC_AUTHORITY_WIDENING
    assert result["classification"] != AUTHENTICATED_LEAF_BINDING_FAILURE


def test_invalid_authentication_keeps_existing_binding_classification():
    document = load_fixture()
    result = evaluate_case(
        document, case_named(document, "invalid-authenticated-leaf-binding")
    )
    assert result["conformant"] is False
    assert result["classification"] == AUTHENTICATED_LEAF_BINDING_FAILURE
    assert result["newly_permitted_operations"] == []


def test_reordering_constraints_does_not_change_semantics():
    document = load_fixture()
    direct_case = case_named(document, "c1-and-c2-preserved-directly")
    original = evaluate_case(document, direct_case)
    document["upstream_authority"]["constraints"].reverse()
    reordered = evaluate_case(document, direct_case)
    assert reordered["conformant"] == original["conformant"]
    assert reordered["upstream_authority_size"] == original["upstream_authority_size"]
    assert (
        reordered["effective_downstream_authority_size"]
        == original["effective_downstream_authority_size"]
    )
    assert (
        reordered["newly_permitted_operations"]
        == original["newly_permitted_operations"]
    )


def test_adding_stricter_downstream_restriction_remains_conformant():
    document = load_fixture()
    result = evaluate_case(
        document, case_named(document, "stricter-trusted-downstream-restriction")
    )
    assert result["conformant"] is True
    assert (
        result["effective_downstream_authority_size"]
        < result["upstream_authority_size"]
    )


def test_downstream_authority_equal_to_upstream_remains_conformant():
    document = load_fixture()
    result = evaluate_case(
        document,
        case_named(document, "c2-representation-lost-but-equivalently-enforced"),
    )
    assert result["conformant"] is True
    assert (
        result["effective_downstream_authority_size"]
        == result["upstream_authority_size"]
    )


def test_untrusted_equivalent_policy_does_not_count_as_enforcement():
    document = load_fixture()
    case = case_named(document, "c2-representation-lost-but-equivalently-enforced")
    case["downstream_enforcement"][0]["trusted"] = False
    result = evaluate_case(document, case)
    assert result["conformant"] is False
    assert result["classification"] == SEMANTIC_AUTHORITY_WIDENING
    assert result["trusted_downstream_constraint_ids"] == []
    assert result["ignored_untrusted_constraint_ids"] == ["POLICY-C2"]


def test_failure_classes_remain_machine_readably_distinct():
    assert (
        len(
            {
                SEMANTIC_AUTHORITY_WIDENING,
                AUTHENTICATED_LEAF_BINDING_FAILURE,
                EXPLICIT_ATTENUATION_BYPASS,
            }
        )
        == 3
    )


def test_fixture_expectations_all_match():
    result = evaluate_fixture(load_fixture())
    assert result["result"] == "pass"
    assert result["case_count"] == 5
    assert all(case["expectation_matched"] for case in result["cases"])


def test_executable_runner_passes_and_emits_machine_readable_result(tmp_path):
    output_path = tmp_path / "semantic-result.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run_semantic_translation.py"),
            "--output",
            str(output_path),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SEMANTIC TRANSLATION CONFORMANCE PASS" in proc.stdout
    result = json.loads(output_path.read_text())
    assert result["result"] == "pass"
    negative = next(
        case
        for case in result["cases"]
        if case["name"] == "c2-lost-without-equivalent-enforcement"
    )
    assert negative["classification"] == SEMANTIC_AUTHORITY_WIDENING
    assert negative["expected_witness_demonstrated"] is True
