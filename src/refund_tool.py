"""The tool-side side-effect target. A real side effect counter, not a mock assertion."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RefundLedger:
    """Records every refund actually executed. This is the ground truth for side effects."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, order_id: str, amount_usd: str) -> dict[str, Any]:
        record = {"order_id": order_id, "amount_usd": amount_usd, "refund_id": f"refund-{len(self.calls) + 1:03d}"}
        self.calls.append(record)
        return record

    @property
    def call_count(self) -> int:
        return len(self.calls)
