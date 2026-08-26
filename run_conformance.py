#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from conformance.authority import AuthoritySigner
from conformance.fixture import run_scenario


ROOT = Path(__file__).resolve().parent
DEFAULT_SIGNING_KEY = b"fixture-only-secret-not-for-production"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run A2A -> MCP delegated-authority conformance scenarios")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "traces"),
        help="directory for machine-readable JSON traces",
    )
    args = parser.parse_args()

    signing_key = os.environ.get("FIXTURE_SIGNING_KEY", "").encode("utf-8") or DEFAULT_SIGNING_KEY
    signer = AuthoritySigner(signing_key)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_paths = [ROOT / "examples" / "valid_input.json", ROOT / "examples" / "invalid_input.json"]
    outcomes = []
    for path in scenario_paths:
        scenario = load_json(path)
        outcome = run_scenario(scenario, signer)
        outcomes.append(outcome)
        trace_path = output_dir / f"{path.stem}.trace.json"
        with trace_path.open("w", encoding="utf-8") as fh:
            json.dump(outcome.trace, fh, indent=2, sort_keys=True)
            fh.write("\n")

        status = "PASS" if outcome.conformant else "FAIL"
        detail = f"expected={outcome.expected} observed={outcome.observed} tool_executed={outcome.tool_executed}"
        print(f"[{status}] {outcome.name}: {detail}")
        print(f"       trace={trace_path.relative_to(ROOT)}")

    valid = next(item for item in outcomes if item.name == "valid_attenuated_refund")
    invalid = next(item for item in outcomes if item.name == "invalid_amount_escalation")

    mechanical_assertions = [
        (valid.conformant, "valid trace outcome must match expected allowed"),
        (valid.observed == "allowed", "valid trace must be allowed"),
        (valid.tool_executed, "valid trace must execute the tool exactly after authorization"),
        (invalid.conformant, "invalid trace outcome must match expected rejection"),
        (invalid.observed == "authority_rejected", "invalid trace must be rejected as an authority violation"),
        (not invalid.tool_executed, "invalid trace must not execute the tool"),
        (
            invalid.response.get("result", {}).get("structuredContent", {}).get("code") == "AMOUNT_SCOPE_ESCALATION",
            "invalid trace must be mechanically classified as AMOUNT_SCOPE_ESCALATION",
        ),
    ]

    failed = [message for ok, message in mechanical_assertions if not ok]
    if failed:
        print("\nCONFORMANCE FAIL")
        for message in failed:
            print(f"  - {message}")
        return 1

    print("\nCONFORMANCE PASS")
    print("  valid: delegated authority preserved and attenuated (35.00 <= 50.00)")
    print("  invalid: escalation detected and tool execution blocked (75.00 > 50.00)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
