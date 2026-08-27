#!/usr/bin/env python3
"""Conformance runner: Human -> Agent A -> A2A Agent B -> MCP -> Tool.

Starts a real MCP server (streamable-http) and a real A2A server (Agent B,
JSON-RPC over HTTP) as subprocesses, then drives Agent A as a real A2A
client against Agent B, which in turn is a real MCP client against the MCP
server. No handwritten protocol shims: every hop is the official `a2a-sdk`
or `mcp` SDK talking over a real socket.

Scenario: "Refund Cap Must Survive A2A -> MCP" (see README.md). This is a
conformance fixture, not a standards proposal -- see README.md and
PRIOR_ART.md for the non-novelty disclaimer and prior-art analysis.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from authority import AuthoritySigner  # noqa: E402
from agent_a import issue_delegation_chain, send_delegated_refund_request  # noqa: E402

DEFAULT_SIGNING_KEY = "fixture-only-secret-not-for-production"
ORDER_ID = "O-1001"
HUMAN_LIMIT_USD = "25.00"
DELEGATED_LIMIT_USD = "20.00"
VALID_ATTEMPT_USD = "18.00"
INVALID_ATTEMPT_USD = "22.00"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise RuntimeError(f"server on port {port} did not become ready in {timeout}s")


class ManagedServer:
    def __init__(self, module: str, port: int, env: dict[str, str]):
        self.port = port
        full_env = {**os.environ, **env, "PYTHONPATH": str(SRC)}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(SRC),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self) -> None:
        try:
            _wait_for_port(self.port)
        except RuntimeError:
            self.stop()
            raise

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()


def sdk_versions() -> dict[str, str]:
    import importlib.metadata as im

    versions = {"a2a": "unknown", "mcp": "unknown"}
    try:
        versions["a2a"] = im.version("a2a-sdk")
    except im.PackageNotFoundError:
        pass
    try:
        versions["mcp"] = im.version("mcp")
    except im.PackageNotFoundError:
        pass
    try:
        import mcp.types as mt

        versions["mcp_wire_protocol"] = mt.LATEST_PROTOCOL_VERSION
    except Exception:
        pass
    try:
        from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

        versions["a2a_wire_protocol"] = PROTOCOL_VERSION_CURRENT
    except Exception:
        pass
    return versions


async def run_attempt(agent_b_url: str, signer, requested_amount_usd: str) -> dict:
    chain = issue_delegation_chain(signer, ORDER_ID, HUMAN_LIMIT_USD, DELEGATED_LIMIT_USD)
    result = await send_delegated_refund_request(agent_b_url, chain, ORDER_ID, requested_amount_usd)
    decision = "deny" if result.get("reply_text", "").upper().startswith("DENY") else "allow"
    if result.get("state") == 4:  # TASK_STATE_FAILED
        decision = "deny"
    return {"decision": decision, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the A2A -> MCP delegated-authority conformance scenario")
    parser.add_argument(
        "--simulate-vulnerable",
        action="store_true",
        help="Run the MCP server in intentionally vulnerable mode (checks only the human root grant).",
    )
    parser.add_argument("--output", default=str(ROOT / "traces" / "result.json"))
    args = parser.parse_args()

    signing_key = os.environ.get("FIXTURE_SIGNING_KEY", DEFAULT_SIGNING_KEY)
    signer = AuthoritySigner(signing_key.encode("utf-8"))

    mcp_port = _free_port()
    a2a_port = _free_port()
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
    agent_b_url = f"http://127.0.0.1:{a2a_port}/"

    mcp_env = {"FIXTURE_SIGNING_KEY": signing_key, "FIXTURE_MCP_PORT": str(mcp_port)}
    if args.simulate_vulnerable:
        mcp_env["FIXTURE_SIMULATE_VULNERABLE"] = "1"

    mcp_server = ManagedServer("mcp_server", mcp_port, mcp_env)
    try:
        mcp_server.wait_ready()
    except RuntimeError as exc:
        print(f"FATAL: MCP server failed to start: {exc}")
        out, _ = mcp_server.proc.communicate()
        print(out.decode("utf-8", "replace"))
        return 2

    agent_b_env = {"FIXTURE_MCP_SERVER_URL": mcp_url, "FIXTURE_A2A_PORT": str(a2a_port)}
    agent_b_server = ManagedServer("agent_b", a2a_port, agent_b_env)
    try:
        agent_b_server.wait_ready()
    except RuntimeError as exc:
        print(f"FATAL: Agent B (A2A server) failed to start: {exc}")
        out, _ = agent_b_server.proc.communicate()
        print(out.decode("utf-8", "replace"))
        mcp_server.stop()
        return 2

    time.sleep(0.3)  # let uvicorn finish binding before the first request

    try:
        valid = asyncio.run(run_attempt(agent_b_url, signer, VALID_ATTEMPT_USD))
        invalid = asyncio.run(run_attempt(agent_b_url, signer, INVALID_ATTEMPT_USD))
    finally:
        agent_b_server.stop()
        mcp_server.stop()

    print(f"[valid $18 attempt]   decision={valid['decision']:5s} reply={valid.get('reply_text', '')!r}")
    print(f"[invalid $22 attempt] decision={invalid['decision']:5s} reply={invalid.get('reply_text', '')!r}")

    invalid_tool_side_effects = 1 if (args.simulate_vulnerable and invalid["decision"] == "allow") else 0
    if not args.simulate_vulnerable and invalid["decision"] == "allow":
        invalid_tool_side_effects = 1  # secure impl allowing $22 would itself be a bug worth surfacing

    valid_ok = valid["decision"] == "allow"
    invalid_ok = invalid["decision"] == "deny"
    overall_pass = valid_ok and invalid_ok

    result = {
        "scenario": "refund-cap-survives-a2a-mcp",
        "protocols": sdk_versions(),
        "human_limit": float(HUMAN_LIMIT_USD),
        "delegated_limit": float(DELEGATED_LIMIT_USD),
        "valid_attempt": float(VALID_ATTEMPT_USD),
        "invalid_attempt": float(INVALID_ATTEMPT_USD),
        "valid_decision": valid["decision"],
        "invalid_decision": invalid["decision"],
        "invalid_tool_side_effects": 0 if invalid_ok else 1,
        "simulated_vulnerable": args.simulate_vulnerable,
        "result": "pass" if overall_pass else "fail",
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"\nmachine-readable result: {output_path.relative_to(ROOT)}")
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.simulate_vulnerable:
        if invalid["decision"] == "allow":
            print("\nVULNERABILITY DETECTED: $22 request was allowed while only checking the $25 human root grant.")
            print("This is the expected outcome for --simulate-vulnerable: it proves the negative test can catch it.")
            return 1
        print("\nUNEXPECTED: vulnerable mode did not allow the forbidden $22 request.")
        return 1

    if not overall_pass:
        print("\nCONFORMANCE FAIL")
        if not valid_ok:
            print("  - $18 request (within delegated $20 authority) was not allowed")
        if not invalid_ok:
            print("  - $22 request (exceeds delegated $20 authority) was not denied")
        return 1

    print("\nCONFORMANCE PASS")
    print(f"  valid:   ${VALID_ATTEMPT_USD} <= delegated ${DELEGATED_LIMIT_USD} -> ALLOW, tool executed")
    print(
        f"  invalid: ${INVALID_ATTEMPT_USD} <= human root ${HUMAN_LIMIT_USD} but "
        f"> delegated ${DELEGATED_LIMIT_USD} -> DENY, tool NOT executed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
