"""Fixture-local delegation-chain authority model.

This module is FIXTURE-LOCAL. Neither A2A nor MCP standardizes a delegation
chain, a grant schema, or an attenuation algorithm. This is test scaffolding
built on top of those protocols' generic extension/metadata mechanisms.

Signing here is a deterministic HMAC over canonical JSON -- a test integrity
primitive, NOT a production trust model. Production delegation would need
real asymmetric signatures, key management, revocation, and replay
protection, none of which this fixture provides.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from typing import Any, Mapping, Sequence


class AuthorityError(Exception):
    """Base class for authority verification failures."""


class InvalidAuthoritySignature(AuthorityError):
    pass


class AuthorityViolation(AuthorityError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def hash_grant(grant: Mapping[str, Any]) -> str:
    """Deterministic content hash of a grant, used as the child's `parent` binding."""
    return hashlib.sha256(canonical_json(dict(grant))).hexdigest()


@dataclass(frozen=True)
class SignedGrant:
    grant: dict[str, Any]
    signature: str
    algorithm: str = "HMAC-SHA256"

    def to_dict(self) -> dict[str, Any]:
        return {"grant": self.grant, "signature": self.signature, "algorithm": self.algorithm}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedGrant":
        grant = value.get("grant")
        signature = value.get("signature")
        algorithm = value.get("algorithm", "HMAC-SHA256")
        if not isinstance(grant, dict) or not isinstance(signature, str):
            raise InvalidAuthoritySignature("malformed signed grant")
        return cls(grant=dict(grant), signature=signature, algorithm=str(algorithm))


class AuthoritySigner:
    """Deterministic fixture signer. HMAC is a test integrity primitive, not a production trust model."""

    def __init__(self, key: bytes):
        if not key:
            raise ValueError("signing key must not be empty")
        self._key = key

    def sign(self, grant: Mapping[str, Any]) -> SignedGrant:
        normalized = json.loads(canonical_json(dict(grant)).decode("utf-8"))
        digest = hmac.new(self._key, canonical_json(normalized), hashlib.sha256).hexdigest()
        return SignedGrant(grant=normalized, signature=digest)

    def verify(self, signed: SignedGrant) -> None:
        if signed.algorithm != "HMAC-SHA256":
            raise InvalidAuthoritySignature(f"unsupported signature algorithm: {signed.algorithm}")
        expected = hmac.new(self._key, canonical_json(signed.grant), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signed.signature):
            raise InvalidAuthoritySignature("authority signature verification failed")


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AuthorityViolation("INVALID_ARGUMENT", f"{field} must be a decimal-compatible value") from exc


# NOTE: every scalar in a grant (max_amount_usd, max_uses, ...) is deliberately
# a JSON string, never a JSON number. A2A's Message.metadata is a
# google.protobuf.Struct, whose only numeric kind is `double`; a bare integer
# like `1` survives a real A2A hop as `1.0`. That is harmless to *read* but
# fatal to a byte-exact signature computed before the hop. Keeping every
# signed scalar a string sidesteps this without inventing any normalization
# rule of our own -- this is a real, observed protocol-boundary effect of A2A
# transporting fixture metadata inside a Struct, not a workaround for a bug
# in this fixture's signer.


@dataclass(frozen=True)
class DelegationChain:
    """An ordered list of signed grants: [root_grant, child_delegation, ...].

    fixture-local wire format: a JSON list of `SignedGrant.to_dict()` objects,
    root first. This whole structure -- not just the leaf -- is what must
    cross the A2A boundary and then the MCP boundary unmodified, so that the
    MCP-side PEP can recompute intersection over the *entire* chain rather
    than trusting a single (possibly widened) leaf claim.
    """

    links: tuple[SignedGrant, ...]

    def to_wire(self) -> list[dict[str, Any]]:
        return [link.to_dict() for link in self.links]

    @classmethod
    def from_wire(cls, value: Sequence[Mapping[str, Any]]) -> "DelegationChain":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
            raise InvalidAuthoritySignature("delegation chain must be a non-empty list")
        return cls(links=tuple(SignedGrant.from_dict(item) for item in value))

    @property
    def root(self) -> SignedGrant:
        return self.links[0]

    @property
    def leaf(self) -> SignedGrant:
        return self.links[-1]


def verify_chain(signer: AuthoritySigner, chain: DelegationChain, expected_leaf_delegate: str) -> None:
    """Verify every link's signature, parent binding, issuer/delegate continuity, and monotonic attenuation.

    Enforces (per the mission's enforcement rule, section 5):
      - valid signatures on every link
      - correct parent binding (child.parent == hash(parent grant))
      - correct issuer/delegate chain (child.issuer == parent.delegate)
      - correct action/resource carried through unchanged
      - non-increasing max_amount_usd
      - non-increasing max_uses
      - leaf delegate == expected_leaf_delegate
    """
    if not chain.links:
        raise AuthorityViolation("EMPTY_CHAIN", "delegation chain must contain at least a root grant")

    root_grant = chain.root.grant
    if root_grant.get("issuer") != "human-approval":
        raise AuthorityViolation("ROOT_ISSUER_INVALID", "root grant must be issued by human-approval")

    previous = chain.root
    signer.verify(previous)

    action = previous.grant.get("action")
    resource = previous.grant.get("resource")

    for index, link in enumerate(chain.links[1:], start=1):
        signer.verify(link)
        grant = link.grant

        expected_parent_hash = hash_grant(previous.grant)
        if grant.get("parent") != expected_parent_hash:
            raise AuthorityViolation(
                "PARENT_BINDING_INVALID",
                f"link {index} parent hash does not match link {index - 1}'s grant content",
            )

        if grant.get("issuer") != previous.grant.get("delegate"):
            raise AuthorityViolation(
                "ISSUER_CHAIN_BROKEN",
                f"link {index} issuer {grant.get('issuer')!r} must equal link {index - 1}'s delegate "
                f"{previous.grant.get('delegate')!r}",
            )

        if grant.get("action") != action:
            raise AuthorityViolation("ACTION_SCOPE_ESCALATION", f"link {index} changed action from {action!r}")

        if grant.get("resource") != resource:
            raise AuthorityViolation("RESOURCE_SCOPE_ESCALATION", f"link {index} changed resource from {resource!r}")

        prev_amount = _decimal(previous.grant.get("max_amount_usd"), "max_amount_usd")
        this_amount = _decimal(grant.get("max_amount_usd"), "max_amount_usd")
        if this_amount > prev_amount:
            raise AuthorityViolation(
                "AMOUNT_NOT_ATTENUATED",
                f"link {index} max_amount_usd {this_amount} exceeds parent's {prev_amount}; "
                "a delegation may only narrow, never widen, authority",
            )

        prev_uses = int(previous.grant.get("max_uses", 0))
        this_uses = int(grant.get("max_uses", 0))
        if this_uses > prev_uses:
            raise AuthorityViolation(
                "USES_NOT_ATTENUATED",
                f"link {index} max_uses {this_uses} exceeds parent's {prev_uses}",
            )

        previous = link

    if chain.leaf.grant.get("delegate") != expected_leaf_delegate:
        raise AuthorityViolation(
            "LEAF_DELEGATE_MISMATCH",
            f"delegation chain leaf delegate {chain.leaf.grant.get('delegate')!r} != "
            f"expected {expected_leaf_delegate!r}",
        )


def effective_authority(chain: DelegationChain) -> Decimal:
    """The effective max_amount_usd is the intersection (minimum) across every link in the chain.

    This is deliberately NOT just the leaf's claimed limit and NOT just the
    root's limit -- it is min() over the whole chain, so that neither a
    widened leaf claim nor a stale root ceiling can be used to authorize
    more than the narrowest link actually granted.
    """
    return min(_decimal(link.grant.get("max_amount_usd"), "max_amount_usd") for link in chain.links)


def assert_request_is_within_authority(
    signer: AuthoritySigner,
    chain: DelegationChain,
    tool_name: str,
    arguments: Mapping[str, Any],
    expected_action: str = "refund_order",
    expected_leaf_delegate: str = "agent-b",
) -> Decimal:
    """Full policy-enforcement-point check. Returns the effective authority ceiling on success."""
    verify_chain(signer, chain, expected_leaf_delegate)

    root_grant = chain.root.grant
    if root_grant.get("action") != expected_action:
        raise AuthorityViolation("ACTION_NOT_AUTHORIZED", f"tool {tool_name!r} is outside authorized action")
    if tool_name != "refund_order":
        raise AuthorityViolation("TOOL_NOT_AUTHORIZED", f"tool {tool_name!r} is not refund_order")

    required_keys = {"order_id", "amount_usd"}
    missing = sorted(required_keys.difference(arguments))
    if missing:
        raise AuthorityViolation("MISSING_ARGUMENT", f"missing required arguments: {', '.join(missing)}")

    if arguments["order_id"] != root_grant.get("resource"):
        raise AuthorityViolation(
            "RESOURCE_SCOPE_ESCALATION",
            f"order_id {arguments['order_id']!r} is outside authorized resource {root_grant.get('resource')!r}",
        )

    amount = _decimal(arguments["amount_usd"], "amount_usd")
    if amount < 0:
        raise AuthorityViolation("INVALID_ARGUMENT", "amount_usd must be non-negative")

    ceiling = effective_authority(chain)
    if amount > ceiling:
        raise AuthorityViolation(
            "AMOUNT_SCOPE_ESCALATION",
            f"requested amount_usd {amount} exceeds effective delegated authority {ceiling} "
            f"(root={_decimal(chain.root.grant.get('max_amount_usd'), 'x')}, "
            f"leaf={_decimal(chain.leaf.grant.get('max_amount_usd'), 'x')})",
        )

    return ceiling


def assert_request_is_within_authority_vulnerable(
    signer: AuthoritySigner,
    chain: DelegationChain,
    tool_name: str,
    arguments: Mapping[str, Any],
    expected_action: str = "refund_order",
    expected_leaf_delegate: str = "agent-b",
) -> Decimal:
    """INTENTIONALLY VULNERABLE variant used only by --simulate-vulnerable.

    This checks only the human ROOT grant's max_amount_usd and ignores every
    intermediate delegation's attenuation. It exists solely so the
    conformance runner's negative test can demonstrate that it is capable of
    detecting this exact class of bug (see mission section 8).
    """
    if not chain.links:
        raise AuthorityViolation("EMPTY_CHAIN", "delegation chain must contain at least a root grant")

    root = chain.root
    signer.verify(root)
    root_grant = root.grant

    if root_grant.get("action") != expected_action or tool_name != "refund_order":
        raise AuthorityViolation("TOOL_NOT_AUTHORIZED", f"tool {tool_name!r} is not refund_order")

    if arguments["order_id"] != root_grant.get("resource"):
        raise AuthorityViolation("RESOURCE_SCOPE_ESCALATION", "order_id outside authorized resource")

    amount = _decimal(arguments["amount_usd"], "amount_usd")
    root_ceiling = _decimal(root_grant.get("max_amount_usd"), "max_amount_usd")
    if amount > root_ceiling:
        raise AuthorityViolation(
            "AMOUNT_SCOPE_ESCALATION",
            f"requested amount_usd {amount} exceeds human root maximum {root_ceiling}",
        )
    # VULNERABILITY: intermediate delegation (chain.leaf) is never consulted.
    return root_ceiling
