from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from conformance.authority import AuthoritySigner
from conformance.fixture import AgentA, AgentB, ConformanceMCPServer, FakeRefundTool, TraceRecorder, run_scenario
from conformance.protocols import extract_authority_from_a2a


ROOT = Path(__file__).resolve().parents[1]
KEY = b"fixture-only-secret-not-for-production"


def load(name: str) -> dict:
    with (ROOT / "examples" / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


class AuthorityConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signer = AuthoritySigner(KEY)

    def test_valid_trace_is_allowed_and_executes_tool(self) -> None:
        outcome = run_scenario(load("valid_input.json"), self.signer)
        self.assertTrue(outcome.conformant)
        self.assertEqual("allowed", outcome.observed)
        self.assertTrue(outcome.tool_executed)
        self.assertFalse(outcome.response["result"]["isError"])

    def test_invalid_amount_escalation_is_rejected_before_tool(self) -> None:
        outcome = run_scenario(load("invalid_input.json"), self.signer)
        self.assertTrue(outcome.conformant)
        self.assertEqual("authority_rejected", outcome.observed)
        self.assertFalse(outcome.tool_executed)
        self.assertTrue(outcome.response["result"]["isError"])
        self.assertEqual(
            "AMOUNT_SCOPE_ESCALATION",
            outcome.response["result"]["structuredContent"]["code"],
        )

    def test_tampering_with_signed_a2a_authority_is_rejected(self) -> None:
        scenario = load("valid_input.json")
        trace = TraceRecorder("tampered_authority")
        a2a = AgentA(self.signer).issue_and_delegate(scenario["human_grant"], trace)
        signed = extract_authority_from_a2a(a2a)
        tampered = copy.deepcopy(a2a)
        ext = tampered["body"]["message"]["extensions"][0]
        tampered["body"]["message"]["metadata"][ext]["grant"]["allow"]["arguments"]["max_amount"] = "500.00"

        mcp = AgentB().receive_and_compose_mcp(tampered, scenario["requested_action"], trace)
        tool = FakeRefundTool()
        response = ConformanceMCPServer(self.signer, tool).handle(mcp, trace)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            "INVALID_AUTHORITY_SIGNATURE",
            response["result"]["structuredContent"]["code"],
        )
        self.assertEqual(0, tool.call_count)
        self.assertNotEqual(signed.grant["allow"]["arguments"]["max_amount"], "500.00")

    def test_dropped_mcp_authority_is_protocol_rejected(self) -> None:
        scenario = load("valid_input.json")
        trace = TraceRecorder("dropped_mcp_authority")
        a2a = AgentA(self.signer).issue_and_delegate(scenario["human_grant"], trace)
        mcp = AgentB().receive_and_compose_mcp(a2a, scenario["requested_action"], trace)
        meta = mcp["params"]["_meta"]
        meta.pop("org.example.a2a-mcp/delegated-authority")

        tool = FakeRefundTool()
        response = ConformanceMCPServer(self.signer, tool).handle(mcp, trace)
        self.assertEqual(-32602, response["error"]["code"])
        self.assertEqual(0, tool.call_count)

    def test_invalid_resource_scope_is_rejected(self) -> None:
        scenario = load("valid_input.json")
        scenario["name"] = "invalid_resource_scope"
        scenario["expected"] = "authority_rejected"
        scenario["requested_action"]["arguments"]["order_id"] = "ORDER-9999"
        outcome = run_scenario(scenario, self.signer)
        self.assertEqual(
            "RESOURCE_SCOPE_ESCALATION",
            outcome.response["result"]["structuredContent"]["code"],
        )
        self.assertFalse(outcome.tool_executed)


if __name__ == "__main__":
    unittest.main()
