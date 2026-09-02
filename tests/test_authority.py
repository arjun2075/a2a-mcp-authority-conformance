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
    assert_request_is_within_authority_truncation_vulnerable,
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


def test_signature_survives_a_real_protobuf_struct_round_trip(signer):
    """Regression test for the real A2A boundary effect diagnosed during implementation.

    A2A carries fixture metadata in `Message.metadata`, a
    `google.protobuf.Struct`. Struct's only numeric kind is `double`, so a
    bare JSON integer (e.g. `max_uses: 1`) becomes `1.0` after a real
    Struct round trip -- which would invalidate a signature computed over
    the pre-round-trip JSON if any signed scalar were a JSON number. This
    fixture avoids that instability by keeping every signed grant scalar a
    JSON string (see the module-level NOTE above `DelegationChain`). This
    test proves that property against the real `google.protobuf.Struct`
    type, not just against plain-dict serialization.
    """
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.struct_pb2 import Struct

    chain = build_chain(signer)
    wire = chain.to_wire()

    struct = Struct()
    struct.update({"delegation_chain": wire})
    roundtripped_wire = MessageToDict(struct)["delegation_chain"]

    roundtripped_chain = DelegationChain.from_wire(roundtripped_wire)

    # If a signed scalar had been a JSON number, the Struct round trip would
    # have silently changed it (e.g. 1 -> 1.0), and this would raise
    # InvalidAuthoritySignature. It must not.
    assert_request_is_within_authority(
        signer, roundtripped_chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
    )
    for original_link, roundtripped_link in zip(chain.links, roundtripped_chain.links):
        assert original_link.signature == roundtripped_link.signature
        assert original_link.grant == roundtripped_link.grant


# ---------------------------------------------------------------------------
# Chain-truncation resistance (GitHub review follow-up).
#
# Distinct from AMOUNT_SCOPE_ESCALATION: there, the complete chain is present
# and the *amount* is too high. Here, the restrictive agent-a -> agent-b hop
# is OMITTED from the presented evidence, so the chain terminates at agent-a
# while the expected requester is agent-b. The verifier must refuse to treat a
# valid upstream prefix as authority for a principal it never delegated to,
# regardless of the requested amount.
# ---------------------------------------------------------------------------


def build_truncated_chain(signer: AuthoritySigner, human_limit="25.00") -> DelegationChain:
    """Only the human -> agent-a root grant. The agent-a -> agent-b hop is omitted.

    The omitted hop is exactly the restrictive one ($20). If a verifier accepts
    this prefix as agent-b's authority, agent-b's effective ceiling silently
    re-expands from $20 back to the human's $25.
    """
    root = {
        "issuer": "human-approval",
        "delegate": "agent-a",
        "action": "refund_order",
        "resource": ORDER_ID,
        "max_amount_usd": human_limit,
        "max_uses": "1",
    }
    return DelegationChain(links=(signer.sign(root),))


def test_truncated_chain_is_rejected_for_amount_above_delegated_ceiling(signer):
    """Requester agent-b presents only human -> agent-a ($25) and asks for $22."""
    chain = build_truncated_chain(signer)
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )
    # Denied because the chain does not reach agent-b -- NOT because 22 > 20.
    assert exc_info.value.code == "LEAF_DELEGATE_MISMATCH"
    assert "agent-a" in str(exc_info.value)


def test_truncated_chain_is_rejected_even_for_an_amount_within_every_grant(signer):
    """Control: $18 is within both $25 and $20, yet the truncated chain is still denied.

    This proves requester/delegation binding is enforced independently of the
    amount check -- the denial cannot be explained by attenuation.
    """
    chain = build_truncated_chain(signer)
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
        )
    assert exc_info.value.code == "LEAF_DELEGATE_MISMATCH"


def test_truncated_and_complete_chain_denials_are_distinguishable(signer):
    """The two failure modes must not collapse into one code."""
    complete = build_chain(signer)
    truncated = build_truncated_chain(signer)

    with pytest.raises(AuthorityViolation) as complete_exc:
        assert_request_is_within_authority(
            signer, complete, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )
    with pytest.raises(AuthorityViolation) as truncated_exc:
        assert_request_is_within_authority(
            signer, truncated, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )

    assert complete_exc.value.code == "AMOUNT_SCOPE_ESCALATION"
    assert truncated_exc.value.code == "LEAF_DELEGATE_MISMATCH"
    assert complete_exc.value.code != truncated_exc.value.code


def test_vulnerable_truncation_checker_allows_re_expanded_authority(signer):
    """The dedicated chain-truncation vulnerability: prefix accepted as B's authority.

    The bad verifier validates the human -> agent-a grant, sees 22 <= 25, and
    never proves the chain terminates at the requester. Effective authority
    re-expands from the omitted $20 hop back to $25.
    """
    chain = build_truncated_chain(signer)
    ceiling = assert_request_is_within_authority_truncation_vulnerable(
        signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
    )
    assert str(ceiling) == "25.00"


def test_secure_and_vulnerable_truncation_checkers_disagree(signer):
    """Same evidence, same request: secure denies, vulnerable allows."""
    chain = build_truncated_chain(signer)
    args = {"order_id": ORDER_ID, "amount_usd": "22.00"}

    with pytest.raises(AuthorityViolation):
        assert_request_is_within_authority(signer, chain, "refund_order", args)

    assert str(assert_request_is_within_authority_truncation_vulnerable(
        signer, chain, "refund_order", args
    )) == "25.00"


# ---------------------------------------------------------------------------
# Regression: the intentionally vulnerable truncation checker must have
# EXACTLY ONE defect -- the missing leaf/requester binding. An earlier draft
# of it also dropped per-hop attenuation and issuer continuity, which would
# have let a reviewer dismiss the demonstration as "that verifier is broken
# in several ways." These tests execute the checker rather than inspecting it.
# ---------------------------------------------------------------------------


def test_vulnerable_truncation_checker_still_rejects_a_widened_child(signer):
    """A child claiming MORE than its parent is rejected even by the vulnerable checker."""
    root = signer.sign(
        {
            "issuer": "human-approval",
            "delegate": "agent-a",
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "25.00",
            "max_uses": "1",
        }
    )
    widened_child = signer.sign(
        {
            "issuer": "agent-a",
            "delegate": "agent-b",
            "parent": hash_grant(root.grant),
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "99.00",  # wider than parent's 25.00
            "max_uses": "1",
        }
    )
    chain = DelegationChain(links=(root, widened_child))
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority_truncation_vulnerable(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )
    assert exc_info.value.code == "AMOUNT_NOT_ATTENUATED"


def test_vulnerable_truncation_checker_still_rejects_issuer_discontinuity(signer):
    """A link whose issuer is not the previous link's delegate is rejected."""
    root = signer.sign(
        {
            "issuer": "human-approval",
            "delegate": "agent-a",
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "25.00",
            "max_uses": "1",
        }
    )
    orphan_child = signer.sign(
        {
            "issuer": "agent-z",  # not agent-a
            "delegate": "agent-b",
            "parent": hash_grant(root.grant),
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "20.00",
            "max_uses": "1",
        }
    )
    chain = DelegationChain(links=(root, orphan_child))
    with pytest.raises(AuthorityViolation) as exc_info:
        assert_request_is_within_authority_truncation_vulnerable(
            signer, chain, "refund_order", {"order_id": ORDER_ID, "amount_usd": "18.00"}
        )
    assert exc_info.value.code == "ISSUER_CHAIN_BROKEN"


def test_vulnerable_truncation_checker_still_rejects_a_tampered_signature(signer):
    """The demonstration must not rest on signature checking being switched off."""
    from dataclasses import replace

    chain = build_truncated_chain(signer)
    tampered = replace(chain.root, grant={**chain.root.grant, "max_amount_usd": "9999.00"})
    with pytest.raises(InvalidAuthoritySignature):
        assert_request_is_within_authority_truncation_vulnerable(
            signer, DelegationChain(links=(tampered,)), "refund_order",
            {"order_id": ORDER_ID, "amount_usd": "22.00"}
        )


def test_vulnerable_truncation_checker_differs_from_secure_only_on_leaf_binding(signer):
    """Both checkers agree on every presented-prefix defect; they differ only on leaf binding."""
    root = signer.sign(
        {
            "issuer": "human-approval",
            "delegate": "agent-a",
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "25.00",
            "max_uses": "1",
        }
    )
    widened = signer.sign(
        {
            "issuer": "agent-a",
            "delegate": "agent-b",
            "parent": hash_grant(root.grant),
            "action": "refund_order",
            "resource": ORDER_ID,
            "max_amount_usd": "99.00",
            "max_uses": "1",
        }
    )
    bad_chain = DelegationChain(links=(root, widened))
    args = {"order_id": ORDER_ID, "amount_usd": "22.00"}

    with pytest.raises(AuthorityViolation) as secure_exc:
        assert_request_is_within_authority(signer, bad_chain, "refund_order", args)
    with pytest.raises(AuthorityViolation) as vuln_exc:
        assert_request_is_within_authority_truncation_vulnerable(signer, bad_chain, "refund_order", args)
    # Same verdict on a malformed presented chain.
    assert secure_exc.value.code == vuln_exc.value.code == "AMOUNT_NOT_ATTENUATED"

    # They diverge ONLY when the chain is well-formed but does not reach the requester.
    truncated = build_truncated_chain(signer)
    with pytest.raises(AuthorityViolation) as secure_trunc:
        assert_request_is_within_authority(signer, truncated, "refund_order", args)
    assert secure_trunc.value.code == "LEAF_DELEGATE_MISMATCH"
    assert str(assert_request_is_within_authority_truncation_vulnerable(
        signer, truncated, "refund_order", args
    )) == "25.00"
