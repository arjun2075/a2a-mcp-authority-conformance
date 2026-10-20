"""Stage-1 external pilot schema, classification and evidence provenance checks."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from external_validation.validate import ContractValidationError, validate_pair

ROOT = Path(__file__).resolve().parents[1]


def load_pair():
    return (
        json.loads((ROOT / "fixtures" / "external-validation-v0.1.json").read_text()),
        json.loads((ROOT / "fixtures" / "external-validation-example-report.json").read_text()),
    )


def test_unrun_report_validates_without_claiming_external_validation():
    manifest, report = load_pair()
    validate_pair(manifest, report)
    assert all(r["status"] == "NOT_EVALUATED" for r in report["results"])
    assert report["target"] is None


def test_manifest_covers_all_seven_vectors_with_distinct_controls():
    manifest, _ = load_pair()
    assert [v["id"] for v in manifest["vectors"]] == [f"V{i}" for i in range(1, 8)]
    assert [a["expected_decision"] for a in manifest["vectors"][5]["attempts"]] == ["allow", "deny"]
    assert [a["expected_effect_count"] for a in manifest["vectors"][5]["attempts"]] == [1, 0]


def test_cannot_claim_pass_without_target_authorization():
    manifest, report = load_pair()
    report["results"][0]["status"] = "PASS"
    with pytest.raises(ContractValidationError, match="operator-authorized"):
        validate_pair(manifest, report)


def test_unrun_cannot_claim_failure_or_hidden_attempts():
    manifest, report = load_pair()
    report["results"][4]["attempts"] = [{
        "attempt_id": "store-credit-deny", "observed_decision": "deny",
        "observed_effect_count": 0, "correlation_id": "unverified"
    }]
    with pytest.raises(ContractValidationError, match="NOT_EVALUATED"):
        validate_pair(manifest, report)


def test_duplicate_vector_ids_rejected():
    manifest, report = load_pair()
    report["results"][6]["vector_id"] = "V5"
    with pytest.raises(ContractValidationError, match="exactly one result"):
        validate_pair(manifest, report)


def test_tool_response_cannot_prove_direct_effect():
    manifest, report = load_pair()
    report["results"][0]["status"] = "INCONCLUSIVE"
    report["target"] = {
        "implementation": "consenting-sandbox-example", "version": "0.0.0",
        "operator_authorized": True, "authorization_scope": "sandbox only",
        "environment": "sandbox", "adapter_version": "v0.1"
    }
    report["results"][0]["evidence"] = [{
        "attempt_id": "allowed-18", "kind": "tool_effect",
        "basis": "direct_observation", "observer": "independent_tester",
        "method": "tool_response", "evidence_ref": "sanitized/response.json",
        "limitations": "", "complete_effect_coverage": False
    }]
    with pytest.raises(ContractValidationError, match="tool response cannot directly"):
        validate_pair(manifest, report)


def test_cli_example_validates():
    run = subprocess.run(
        [sys.executable, "-m", "external_validation.validate"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=15
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "no external result certified" in run.stdout
