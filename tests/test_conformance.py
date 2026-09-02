"""End-to-end conformance test: runs the real run_conformance.py runner as a subprocess.

This exercises the full path (Human -> Agent A -> real A2A server (Agent B)
-> real MCP server -> Tool) over actual sockets using the official a2a-sdk
and mcp SDKs -- no handwritten protocol shims.
"""
from __future__ import annotations

import json
import os
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


def test_secure_mode_denies_truncated_chain_on_requester_binding():
    """End-to-end: a chain terminating at agent-a is not agent-b's authority.

    Both the $22 and the $18 truncated-chain attempts must be denied with
    LEAF_DELEGATE_MISMATCH -- proving the denial comes from chain/requester
    binding, not from the amount check.
    """
    code, output, result = _run(output_name="test_truncated_result.json")
    assert code == 0, output
    truncated = result["truncated_chain"]

    assert truncated["requester"] == "agent-b"
    assert truncated["presented_chain_leaf_delegate"] == "agent-a"
    assert truncated["presented_chain_links"] == 1
    assert truncated["omitted_hop"] == "agent-a -> agent-b"

    # $22: above the omitted hop's $20, below the presented root's $25.
    assert truncated["invalid_attempt"] == 22.0
    assert truncated["invalid_decision"] == "deny"
    assert truncated["invalid_reason"] == "LEAF_DELEGATE_MISMATCH"
    assert truncated["invalid_tool_executed"] is False

    # $18 control: within BOTH $25 and $20, still denied.
    assert truncated["control_attempt"] == 18.0
    assert truncated["control_decision"] == "deny"
    assert truncated["control_reason"] == "LEAF_DELEGATE_MISMATCH"
    assert truncated["control_tool_executed"] is False

    # No refund side effect on any secure denial: the only ledger record in a
    # secure run is the single legitimate $18 complete-chain refund.
    assert output.count("refund_id") == 1
    assert '"amount_usd": "18.00"' in output
    assert '"amount_usd": "22.00"' not in output


def test_truncation_and_attenuation_denials_remain_distinct():
    """The complete-chain $22 denial must stay AMOUNT_SCOPE_ESCALATION, not collapse."""
    code, output, result = _run(output_name="test_distinct_result.json")
    assert code == 0, output
    assert result["invalid_reason"] == "AMOUNT_SCOPE_ESCALATION"
    assert result["truncated_chain"]["invalid_reason"] == "LEAF_DELEGATE_MISMATCH"
    assert result["invalid_reason"] != result["truncated_chain"]["invalid_reason"]


def test_vulnerable_truncation_mode_allows_re_expanded_authority():
    """The dedicated chain-truncation vulnerability, end-to-end.

    The bad verifier accepts the valid human -> agent-a prefix as agent-b's
    authority, so $22 executes even though agent-b's real ceiling was $20.
    """
    code, output, result = _run(
        "--simulate-vulnerable-truncation", output_name="test_vuln_truncation_result.json"
    )
    assert code != 0, output
    assert "VULNERABILITY DETECTED (chain truncation)" in output
    truncated = result["truncated_chain"]
    assert truncated["invalid_decision"] == "allow"
    assert truncated["invalid_tool_executed"] is True
    assert result["simulated_vulnerable_truncation"] is True

    # Ground truth of the re-expansion: the tool really ran, refunding the
    # forbidden $22 at a $25 ceiling -- i.e. agent-b's real $20 cap was lost
    # purely because the restrictive hop was omitted from the evidence.
    assert '"amount_usd": "22.00"' in output
    assert '"effective_authority_usd": "25.00"' in output
    assert "refund_id" in output


# ---------------------------------------------------------------------------
# Regression: the two vulnerable modes model different bugs and must never be
# active simultaneously. A previous draft silently ran one mode while the
# result JSON reported BOTH as true -- an ambiguous, misleading state. These
# tests pin the explicit-failure behavior at both layers (CLI and server).
# ---------------------------------------------------------------------------


def test_both_vulnerable_cli_flags_are_rejected_with_argparse_exit_code():
    """--simulate-vulnerable + --simulate-vulnerable-truncation must fail explicitly."""
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run_conformance.py"),
            "--simulate-vulnerable",
            "--simulate-vulnerable-truncation",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    # argparse's parser.error() exits 2 -- a configuration error, distinct from
    # both conformance pass (0) and vulnerability-detected (1).
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "mutually exclusive" in (proc.stdout + proc.stderr)
    # It must fail before running any scenario.
    assert "CONFORMANCE" not in proc.stdout
    assert "VULNERABILITY DETECTED" not in proc.stdout


def test_both_vulnerable_env_flags_are_rejected_by_the_mcp_server():
    """Directly launching the MCP server with both env flags must fail before serving."""
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "FIXTURE_SIMULATE_VULNERABLE": "1",
        "FIXTURE_SIMULATE_VULNERABLE_TRUNCATION": "1",
        "FIXTURE_MCP_PORT": "0",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_server"],
        cwd=str(ROOT / "src"),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "mutually exclusive" in (proc.stdout + proc.stderr)


def test_single_vulnerable_env_flag_still_starts_the_server():
    """Control: the guard must reject only the ambiguous combination, not one flag alone.

    Started with a real port and terminated after startup -- proving the guard
    does not fire when exactly one mode is selected.
    """
    import socket
    import time

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "FIXTURE_SIMULATE_VULNERABLE_TRUNCATION": "1",
        "FIXTURE_MCP_PORT": str(port),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server"],
        cwd=str(ROOT / "src"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        started = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(("127.0.0.1", port))
                    started = True
                    break
                except OSError:
                    time.sleep(0.1)
        assert started, "server with a single vulnerable flag should have started: " + (
            proc.stdout.read() if proc.poll() is not None and proc.stdout else ""
        )
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
