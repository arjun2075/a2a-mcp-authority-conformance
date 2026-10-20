"""Optional adapter API for a consenting, instrumented external A2A→MCP target.

This module deliberately declares an interface only. It does not make network
requests, mint delegation credentials, create authorizations, or claim any A2A
or MCP protocol conformance. Operators supply their own implementation.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class ExternalTargetAdapter(Protocol):
    """One authorized target; methods return JSON-serializable data.

    Caller controls authorization and is responsible for sandbox isolation.
    prepare_case must verify operator permission and prerequisites before
    run_case may submit any operation. collect_observations must preserve
    provenance, not infer effects from success responses.
    """

    def describe_target(self) -> Mapping[str, Any]:
        """Identity, versions, capabilities, and observable evidence sources."""
        ...

    def prepare_case(self, case_spec: Mapping[str, Any]) -> Mapping[str, Any]:
        """Prepared sandbox case, or explicit unsupported/unauthorized reason."""
        ...

    def run_case(self, prepared_case: Mapping[str, Any]) -> str:
        """Run only a previously prepared and operator-authorized case."""
        ...

    def collect_observations(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        """Raw observations with collector, method, and evidence references."""
        ...

    def cleanup(self, run_id: str) -> Mapping[str, Any]:
        """Explain cleaned resources and any residual sandbox effects."""
        ...
