"""Namespacing constants for fixture-local metadata carried over real protocols.

Everything here is FIXTURE-LOCAL, not protocol-defined:
  - A2A_DELEGATION_EXTENSION_URI is an A2A AgentExtension URI (A2A's generic
    extension mechanism; the URI and its payload shape are ours).
  - MCP_DELEGATION_META_KEY is a namespaced key placed under MCP's generic
    per-request `_meta` object (MCP's generic metadata mechanism; the key
    and its payload shape are ours).
"""
from __future__ import annotations

# A2A: carried as an AgentExtension URI in AgentCard.capabilities.extensions,
# and as a key in Message.metadata (a google.protobuf.Struct).
A2A_DELEGATION_EXTENSION_URI = "https://example.org/a2a/extensions/delegation-chain/v1"

# MCP: carried as a namespaced key inside CallToolRequestParams._meta.
# Reverse-domain namespaced per MCP's _meta convention; the exact namespace
# is not load-bearing, only that it is a valid reverse-domain-style key.
MCP_DELEGATION_META_KEY = "io.example.a2a-mcp-conformance/delegation-chain"

REFUND_ORDER_ID = "O-1001"
HUMAN_LIMIT_USD = "25.00"
DELEGATED_LIMIT_USD = "20.00"
