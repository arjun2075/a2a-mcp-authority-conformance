"""Validate versioned external pilot manifests and reports (no network calls).

Statuses are not inferred from the presence/absence of an API response.
This checks schema shape and selected hard evidentiary preconditions. Reviewers
must still verify the provenance and completeness of supplied observations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = ROOT / "schemas" / "external-manifest-v0.1.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "external-report-v0.1.schema.json"


class ContractValidationError(ValueError):
    """Invalid manifest/report or a result unsupported by submitted evidence."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(data: dict[str, Any], schema_path: Path) -> None:
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


def validate_pair(manifest: dict[str, Any], report: dict[str, Any]) -> None:
    """Reject inconsistent outcomes and unsupported claims of PASS.

    A PASS requires operator permission, direct terminal-decision and tool-effect
    observations for each attempt, expected decision/effect counts, and evidence
    of effective policy + translation for semantic vectors. This is a minimum
    review threshold, not an automatic certification.
    """
    _validate_schema(manifest, MANIFEST_SCHEMA)
    _validate_schema(report, REPORT_SCHEMA)
    if report["manifest"]["id"] != manifest["manifest_id"] or report["manifest"]["version"] != manifest["schema_version"]:
        raise ContractValidationError("report references a different manifest identity or version")
    specs = {v["id"]: v for v in manifest["vectors"]}
    if len(specs) != len(manifest["vectors"]) or set(specs) != {f"V{i}" for i in range(1, 8)}:
        raise ContractValidationError("manifest must contain exactly one of V1 through V7")
    reported = {r["vector_id"]: r for r in report["results"]}
    if len(reported) != len(report["results"]) or set(reported) != set(specs):
        raise ContractValidationError("report must contain exactly one result per manifest vector")
    for vid, spec in specs.items():
        spec_attempts = {a["id"]: a for a in spec["attempts"]}
        if len(spec_attempts) != len(spec["attempts"]):
            raise ContractValidationError(f"{vid}: duplicate manifest attempt ID")
        result = reported[vid]
        status = result["status"]
        attempted = {a["attempt_id"]: a for a in result["attempts"]}
        if len(attempted) != len(result["attempts"]) or not set(attempted).issubset(spec_attempts):
            raise ContractValidationError(f"{vid}: duplicate or unknown observed attempt ID")
        for evidence in result["evidence"]:
            if evidence["attempt_id"] not in spec_attempts:
                raise ContractValidationError(f"{vid}: evidence references an unknown attempt")
            if evidence["kind"] in {"terminal_decision", "tool_effect"} and evidence["basis"] == "direct_observation" and evidence["method"] == "tool_response":
                raise ContractValidationError(f"{vid}: a tool response cannot directly establish terminal enforcement or effects")
            if evidence["kind"] != "tool_effect" and evidence["complete_effect_coverage"]:
                raise ContractValidationError(f"{vid}: effect coverage may only be asserted for tool_effect evidence")
        if status == "NOT_EVALUATED":
            if result["attempts"] or result["evidence"] or "failure_class" in result:
                raise ContractValidationError(f"{vid}: NOT_EVALUATED cannot contain outcomes or claim failures")
            continue
        if report["target"] is None or report["target"]["operator_authorized"] is not True:
            raise ContractValidationError(f"{vid}: evaluated results require operator-authorized target")
        if status in {"PASS", "FAIL"} and set(attempted) != set(spec_attempts):
            raise ContractValidationError(f"{vid}: evaluated outcome lacks a manifest attempt")
        if status == "FAIL" and "failure_class" not in result:
            raise ContractValidationError(f"{vid}: FAIL requires a supported, named failure class")
        if status != "FAIL" and "failure_class" in result:
            raise ContractValidationError(f"{vid}: failure_class is only applicable to FAIL")
        if status != "PASS":
            continue
        for aid, expected in spec_attempts.items():
            observed = attempted[aid]
            if observed["observed_decision"] != expected["expected_decision"] or observed["observed_effect_count"] != expected["expected_effect_count"]:
                raise ContractValidationError(f"{vid}/{aid}: PASS contradicts observed decision or effects")
            relevant = [e for e in result["evidence"] if e["attempt_id"] == aid and e["basis"] == "direct_observation"]
            if not any(e["kind"] == "terminal_decision" and e["method"] != "tool_response" for e in relevant):
                raise ContractValidationError(f"{vid}/{aid}: PASS lacks directly observed terminal authorization decision")
            if not any(e["kind"] == "tool_effect" and e["method"] in {"sandbox_state_diff", "instrumented_trace", "operator_log"} and e["complete_effect_coverage"] for e in relevant):
                raise ContractValidationError(f"{vid}/{aid}: PASS lacks complete direct side-effect observation")
            if vid in {"V5", "V6"}:
                for kind in ("translation", "effective_policy"):
                    if not any(e["kind"] == kind and e["method"] != "tool_response" for e in relevant):
                        raise ContractValidationError(f"{vid}/{aid}: PASS lacks {kind} evidence")
    # PASS validates sufficient structured support for review, never the truth of claims.


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate authorized A2A→MCP pilot report contract")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures" / "external-validation-v0.1.json")
    parser.add_argument("--report", type=Path, default=ROOT / "fixtures" / "external-validation-example-report.json")
    args = parser.parse_args()
    try:
        validate_pair(_load(args.manifest), _load(args.report))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CONTRACT INVALID: {exc}")
        return 1
    print("CONTRACT VALID (schema/evidence consistency only; no external result certified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
