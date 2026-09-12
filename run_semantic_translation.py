#!/usr/bin/env python3
"""Run the fixture-local lossy A2A -> MCP semantic authority vectors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from semantic_authority import FixtureFormatError, evaluate_fixture


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run semantic A2A -> MCP translation conformance vectors"
    )
    parser.add_argument(
        "--fixture",
        default=str(ROOT / "fixtures" / "semantic-authority-widening.json"),
    )
    parser.add_argument(
        "--output", default=str(ROOT / "traces" / "semantic-translation-result.json")
    )
    args = parser.parse_args()

    try:
        document = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        result = evaluate_fixture(document)
    except (OSError, json.JSONDecodeError, FixtureFormatError) as exc:
        print(f"FIXTURE ERROR: {exc}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for case in result["cases"]:
        classification = case["classification"] or "NONE"
        print(
            f"[{case['name']}] expected={case['expected']} "
            f"conformant={str(case['conformant']).lower()} classification={classification}"
        )
        for operation in case["newly_permitted_operations"]:
            print(f"  newly permitted: {json.dumps(operation, sort_keys=True)}")
    print(f"\nmachine-readable result: {output_path}")
    print(
        "SEMANTIC TRANSLATION CONFORMANCE PASS"
        if result["result"] == "pass"
        else "SEMANTIC TRANSLATION CONFORMANCE FAIL"
    )
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
