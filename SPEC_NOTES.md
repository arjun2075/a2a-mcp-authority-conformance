# Specification notes

This fixture was aligned on 2026-08-26 to:

- A2A: tested against the A2A v1.x semantics relevant to this fixture; current protocol release at review time: v1.0.1: https://a2a-protocol.org/latest/specification/
- MCP latest protocol revision 2026-07-28: https://modelcontextprotocol.io/specification/latest
- MCP tools: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- MCP schema reference: https://modelcontextprotocol.io/specification/2026-07-28/schema

## Normative observations used by the fixture

1. A2A HTTP+JSON maps Send Message to `POST /message:send`, and `Message` supports `extensions` plus `metadata`.
2. A2A v1.x explicitly says `TASK_STATE_AUTH_REQUIRED` does not define the scope, representation, validity, or revocation semantics of an approval; those semantics are implementation-, credential-, or extension-defined.
3. A2A extension use is opt-in and can carry strongly typed message metadata identified by a URI.
4. MCP 2026-07-28 `tools/call` uses JSON-RPC 2.0 and requires `params._meta` with per-request protocol version and client capabilities.
5. MCP is stateless at protocol level in this revision: servers must not rely on prior requests for context and every request supplies relevant metadata.
6. MCP `_meta` permits third-party namespaced metadata, and client/server capabilities can advertise namespaced extensions.
7. MCP tool servers must validate inputs and implement proper access controls; clients should keep a human in the loop for sensitive operations.

## Fixture interpretation

Neither protocol defines a standard cross-protocol delegated-authority object that says, for example, “refund only ORDER-1001, USD, at most 50.00.” This fixture therefore uses only existing extension points:

- A2A: a fixture-local extension URI in `Message.extensions` and `Message.metadata`.
- MCP: a fixture-local, namespaced extension identifier in `clientCapabilities.extensions` and the signed authority value in `params._meta`.

The authority object is deliberately not proposed as a standard. It exists only to make the conformance property executable.
