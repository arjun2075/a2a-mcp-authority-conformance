from __future__ import annotations

from typing import Any, Mapping

from .authority import SignedAuthority
from .constants import (
    A2A_AUTH_EXTENSION_URI,
    A2A_CONTENT_TYPE,
    A2A_VERSION,
    MCP_AUTH_EXTENSION_ID,
    MCP_CLIENT_CAPABILITIES_KEY,
    MCP_CLIENT_INFO_KEY,
    MCP_PROTOCOL_VERSION_KEY,
    MCP_VERSION,
)


class ProtocolShapeError(ValueError):
    pass


def build_a2a_request(signed: SignedAuthority, message_id: str = "a2a-msg-001") -> dict[str, Any]:
    """Build a current A2A 1.0 HTTP+JSON SendMessage request envelope."""
    return {
        "http": {
            "method": "POST",
            "path": "/message:send",
            "headers": {
                "Content-Type": A2A_CONTENT_TYPE,
                "A2A-Version": A2A_VERSION,
                "A2A-Extensions": A2A_AUTH_EXTENSION_URI,
            },
        },
        "body": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"text": "Execute the approved refund using no more authority than granted."}],
                "extensions": [A2A_AUTH_EXTENSION_URI],
                "metadata": {A2A_AUTH_EXTENSION_URI: signed.to_dict()},
            }
        },
    }


def extract_authority_from_a2a(envelope: Mapping[str, Any]) -> SignedAuthority:
    http = envelope.get("http", {})
    headers = http.get("headers", {}) if isinstance(http, Mapping) else {}
    body = envelope.get("body", {})
    message = body.get("message", {}) if isinstance(body, Mapping) else {}

    if http.get("method") != "POST" or http.get("path") != "/message:send":
        raise ProtocolShapeError("A2A request must use POST /message:send")
    if headers.get("Content-Type") != A2A_CONTENT_TYPE:
        raise ProtocolShapeError("A2A Content-Type must be application/a2a+json")
    if headers.get("A2A-Version") != A2A_VERSION:
        raise ProtocolShapeError(f"A2A-Version must be {A2A_VERSION}")
    if A2A_AUTH_EXTENSION_URI not in str(headers.get("A2A-Extensions", "")).split(","):
        raise ProtocolShapeError("A2A authority extension was not opted into")
    if message.get("role") != "ROLE_USER":
        raise ProtocolShapeError("A2A client message role must be ROLE_USER")
    if not isinstance(message.get("messageId"), str) or not message["messageId"]:
        raise ProtocolShapeError("A2A messageId is required")
    if A2A_AUTH_EXTENSION_URI not in message.get("extensions", []):
        raise ProtocolShapeError("A2A message does not declare the authority extension")
    metadata = message.get("metadata", {})
    if A2A_AUTH_EXTENSION_URI not in metadata:
        raise ProtocolShapeError("A2A message is missing authority extension metadata")
    return SignedAuthority.from_dict(metadata[A2A_AUTH_EXTENSION_URI])


def build_mcp_tool_call(
    signed: SignedAuthority,
    tool_name: str,
    arguments: Mapping[str, Any],
    request_id: str = "mcp-call-001",
) -> dict[str, Any]:
    """Build a current MCP 2026-07-28 tools/call request with required per-request metadata."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "_meta": {
                MCP_PROTOCOL_VERSION_KEY: MCP_VERSION,
                MCP_CLIENT_INFO_KEY: {"name": "a2a-mcp-conformance-agent-b", "version": "0.1.0"},
                MCP_CLIENT_CAPABILITIES_KEY: {
                    "extensions": {MCP_AUTH_EXTENSION_ID: {}}
                },
                MCP_AUTH_EXTENSION_ID: signed.to_dict(),
            },
            "name": tool_name,
            "arguments": dict(arguments),
        },
    }


def extract_authority_from_mcp(request: Mapping[str, Any]) -> SignedAuthority:
    if request.get("jsonrpc") != "2.0":
        raise ProtocolShapeError("MCP request must use JSON-RPC 2.0")
    if request.get("method") != "tools/call":
        raise ProtocolShapeError("MCP request method must be tools/call")
    if "id" not in request:
        raise ProtocolShapeError("MCP tools/call request must include an id")

    params = request.get("params")
    if not isinstance(params, Mapping):
        raise ProtocolShapeError("MCP tools/call params are required")
    meta = params.get("_meta")
    if not isinstance(meta, Mapping):
        raise ProtocolShapeError("MCP 2026-07-28 requires params._meta")
    if meta.get(MCP_PROTOCOL_VERSION_KEY) != MCP_VERSION:
        raise ProtocolShapeError(f"MCP protocolVersion must be {MCP_VERSION}")
    capabilities = meta.get(MCP_CLIENT_CAPABILITIES_KEY)
    if not isinstance(capabilities, Mapping):
        raise ProtocolShapeError("MCP clientCapabilities is required on every request")
    extensions = capabilities.get("extensions", {})
    if MCP_AUTH_EXTENSION_ID not in extensions:
        raise ProtocolShapeError("MCP client did not declare the fixture authority extension")
    if MCP_AUTH_EXTENSION_ID not in meta:
        raise ProtocolShapeError("MCP request dropped delegated authority metadata")
    return SignedAuthority.from_dict(meta[MCP_AUTH_EXTENSION_ID])
