from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from typing import Any, Mapping


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


@dataclass(frozen=True)
class SignedAuthority:
    grant: dict[str, Any]
    signature: str
    algorithm: str = "HMAC-SHA256"

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant": self.grant,
            "signature": self.signature,
            "algorithm": self.algorithm,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedAuthority":
        grant = value.get("grant")
        signature = value.get("signature")
        algorithm = value.get("algorithm", "HMAC-SHA256")
        if not isinstance(grant, dict) or not isinstance(signature, str):
            raise InvalidAuthoritySignature("malformed signed authority")
        return cls(grant=dict(grant), signature=signature, algorithm=str(algorithm))


class AuthoritySigner:
    """Deterministic fixture signer. HMAC is a test integrity primitive, not a production trust model."""

    def __init__(self, key: bytes):
        if not key:
            raise ValueError("signing key must not be empty")
        self._key = key

    def sign(self, grant: Mapping[str, Any]) -> SignedAuthority:
        normalized = json.loads(canonical_json(dict(grant)).decode("utf-8"))
        digest = hmac.new(self._key, canonical_json(normalized), hashlib.sha256).hexdigest()
        return SignedAuthority(grant=normalized, signature=digest)

    def verify(self, signed: SignedAuthority) -> None:
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


def assert_request_is_within_authority(
    signed: SignedAuthority,
    tool_name: str,
    arguments: Mapping[str, Any],
    expected_delegate: str = "agent-b",
) -> None:
    """Enforce monotonic authority: the downstream request may only narrow the signed human grant."""
    grant = signed.grant
    allow = grant.get("allow", {})
    constraints = allow.get("arguments", {}) if isinstance(allow, dict) else {}
    delegation = grant.get("delegation", {})

    if grant.get("no_privilege_escalation") is not True:
        raise AuthorityViolation("GRANT_POLICY_INVALID", "grant must explicitly forbid privilege escalation")

    if allow.get("tool") != tool_name:
        raise AuthorityViolation(
            "TOOL_NOT_AUTHORIZED",
            f"tool {tool_name!r} is outside authorized tool {allow.get('tool')!r}",
        )

    allowed_agents = delegation.get("permitted_agents", []) if isinstance(delegation, dict) else []
    if expected_delegate not in allowed_agents:
        raise AuthorityViolation(
            "DELEGATE_NOT_AUTHORIZED",
            f"delegate {expected_delegate!r} is not in the human-approved delegation path",
        )

    required_keys = {"order_id", "currency", "amount"}
    missing = sorted(required_keys.difference(arguments))
    if missing:
        raise AuthorityViolation("MISSING_ARGUMENT", f"missing required arguments: {', '.join(missing)}")

    if arguments["order_id"] != constraints.get("order_id"):
        raise AuthorityViolation(
            "RESOURCE_SCOPE_ESCALATION",
            f"order_id {arguments['order_id']!r} is outside authorized resource {constraints.get('order_id')!r}",
        )

    if arguments["currency"] != constraints.get("currency"):
        raise AuthorityViolation(
            "CURRENCY_SCOPE_ESCALATION",
            f"currency {arguments['currency']!r} differs from authorized currency {constraints.get('currency')!r}",
        )

    amount = _decimal(arguments["amount"], "amount")
    max_amount = _decimal(constraints.get("max_amount"), "max_amount")
    if amount < 0:
        raise AuthorityViolation("INVALID_ARGUMENT", "amount must be non-negative")
    if amount > max_amount:
        raise AuthorityViolation(
            "AMOUNT_SCOPE_ESCALATION",
            f"requested amount {amount} exceeds human-approved maximum {max_amount}",
        )
