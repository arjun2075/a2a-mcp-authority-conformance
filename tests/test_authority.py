"""Unit tests for the fixture-local delegation-chain authority model (src/authority.py).

These do not touch A2A or MCP at all -- they test the policy-enforcement
logic in isolation. End-to-end protocol behavior is covered by
tests/test_conformance.py.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from authority import (  # noqa: E402
    AuthorityViolation,
    AuthoritySigner,
    DelegationChain,
    InvalidAuthoritySignature,
    assert_request_is_within_authority,
    assert_request_is_within_authority_vulnerable,
    effective_authority,
    hash_grant,
)

KEY = b"fixture-only-secret-not-for-production"
ORDER_ID = "O-1001"


def build_chain(signer: AuthoritySigner, human_limit="25.00", delegated_limit="20.00") -> DelegationChain:
    root = {
        "issuer": "human-approval",
        "delegate": "agent-a",
        "action": "refund_order",
        "resource": ORDER_ID,
        "max_amount_usd": human_limit,
        "max_uses": "1",
    }
    root_signed = signer.sign(root)
    child = {
        "issuer": "agent-a",
        "delegate": "agent-b",
        "parent": hash_grant(root_signed.grant),
        "action": "refund_order",
        "resource": ORDER_ID,
        "max_amount_usd": delegated_limit,
        "max_uses": "1",
    }
    child_signed = signer.sign(child)
    return DelegationChain(links=(root_signed, child_signed))


@pytest.fixture
def signer() -> AuthoritySigner:
    return AuthoritySigner(KEY)


def test_effective_authority_is_the_minimum_across_the_chain(signer):
    chain = build_chain(signer, human_limit="25.00", delegated_limit="20.00")
    assert effective_authority(chain) == pytest.approx(20.00)


def test_request_within_delegated_authority_is_allowed(signer):
    chain = build_chain(signer)
    ceiling = assert_request_is_within_authority(
        signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
    )
    assert str(ceiling) == "20.00"


def test_request_within_root_but_exceeding_delegated_authority_is_denied(signer):
    """The exact bug this fixture exists to catch: 22 <= 25 but 22 > 20."""
    chain = build_chain(signer)
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )
    assert exc_info.value.code == "AMOUNT_SCOPE_ESCALATION"


def test_vulnerable_checker_incorrectly_allows_the_same_request(signer):
    """Demonstrates the vulnerable path is a real, distinguishable behavior -- not a no-op."""
    chain = build_chain(signer)
    ceiling = assert_request_is_within_authority_vulnerable(
        signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
    )
    assert str(ceiling) == "25.00"  # checked only the human root, not the $20 delegation


def test_child_widening_authority_is_rejected_at_verification_time(signer):
    """A child grant that claims MORE than its parent must fail chain verification itself."""
    root = {
        "issuer": "human-approval",
        "delegate": "agent-a",
        "action": "refund_order",
        "resource": ORDER_ID,
        "max_amount_usd": "20.00",
        "max_uses": "1",
    }
    root_signed = signer.sign(root)
    widened_child = {
        "issuer": "agent-a",
        "delegate": "agent-b",
        "parent": hash_grant(root_signed.grant),
        "action": "refund_order",
        "resource": ORDER_ID,
        "max_amount_usd": "25.00",  # wider than parent's 20.00
        "max_uses": "1",
    }
    child_signed = signer.sign(widened_child)
    chain = DelegationChain(links=(root_signed, child_signed))
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
        )
    assert exc_info.value.code == "AMOUNT_NOT_ATTENUATED"


def test_tampered_signature_is_rejected(signer):
    chain = build_chain(signer)
    tampered_grant = dict(chain.leaf.grant)
    tampered_grant["max_amount_usd"] = "1000.00"
    from dataclasses import replace

    tampered_leaf = replace(chain.leaf, grant=tampered_grant)
    tampered_chain = DelegationChain(links=(chain.root, tampered_leaf))
    with pytest.raises(InvalidAuthoritySignature):
        assert_request_is_within_authority(
            signer, tampered_chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
        )


def test_broken_parent_binding_is_rejected(signer):
    chain = build_chain(signer)
    bad_child_grant = dict(chain.leaf.grant)
    bad_child_grant["parent"] = "0" * 64
    tampered_leaf = signer.sign(bad_child_grant)
    tampered_chain = DelegationChain(links=(chain.root, tampered_leaf))
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, tampered_chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
        )
    assert exc_info.value.code == "PARENT_BINDING_INVALID"


def test_wrong_leaf_delegate_is_rejected(signer):
    chain = build_chain(signer)
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer,
            chain,
            "refund_order",
            {"order_id": ORDER_ID, "amount_usd": "18.00"},
            expected_leaf_delegate="agent-c",
        )
    assert exc_info.value.code == "LEAF_DELEGATE_MISMATCH"


def test_resource_scope_escalation_is_rejected(signer):
    chain = build_chain(signer)
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, chain, "refund_order", {"order_id": "O-9999", "amount_usd": "18.00"}
        )
    assert exc_info.value.code == "RESOURCE_SCOPE_ESCALATION"
