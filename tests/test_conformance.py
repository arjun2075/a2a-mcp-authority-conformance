"""End-to-end conformance test: runs the real run_conformance.py runner as a subprocess.

This exercises the full path (Human -> Agent A -> real A2A server (Agent B)
-> real MCP server -> Tool) over actual sockets using the official a2a-sdk
and mcp SDKs -- no handwritten protocol shims.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(*extra_args: str, output_name: str) -> tuple[int, str, dict]:
    output_path = ROOT / "traces" / output_name
    proc = subprocess.run(
        [sys.executable, str(ROOT / "run_conformance.py"), "--output", str(output_path), *extra_args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = json.loads(output_path.read_text()) if output_path.exists() else {}
    return proc.returncode, proc.stdout + proc.stderr, result


def test_secure_mode_passes_and_exits_zero():
    code, output, result = _run(output_name="test_secure_result.json")
    assert code == 0, output
    assert "CONFORMANCE PASS" in output
    assert result["result"] == "pass"
    assert result["valid_decision"] == "allow"
    assert result["invalid_decision"] == "deny"
    assert result["invalid_tool_side_effects"] == 0
    assert result["human_limit"] == 25.0
    assert result["delegated_limit"] == 20.0
    assert result["valid_attempt"] == 18.0
    assert result["invalid_attempt"] == 22.0


def test_vulnerable_mode_is_detected_and_exits_nonzero():
    code, output, result = _run("--simulate-vulnerable", output_name="test_vulnerable_result.json")
    assert code != 0, output
    assert "VULNERABILITY DETECTED" in output
    assert result["result"] == "fail"
    assert result["invalid_decision"] == "allow"  # the forbidden $22 refund was allowed
    assert result["invalid_tool_side_effects"] == 1
