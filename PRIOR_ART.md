# Prior Art and Non-Novelty Disclaimer

This document summarizes a prior-art review conducted before publishing
this repository. It exists to keep the scope of this artifact's claims
narrow and accurate. **Read this before citing, forking, or building on
this repository for anything beyond what it actually demonstrates.**

## One-paragraph summary

The security property this fixture demonstrates — monotonic authority
attenuation across a delegation chain, enforced against the
**intersection** of the whole chain rather than its root or its leaf
alone — is well-established prior art, over a decade old. It is not
novel. What this repository provides is a small, runnable check that this
already-known pattern can be correctly carried across two specific,
currently popular AI-agent protocols (A2A and MCP) using their *official*
SDKs, with a working positive/negative test pair. That is an integration
and conformance contribution, not a new security primitive, protocol
extension, or research result.

## What already exists (with sources)

| System | What it establishes | Source |
|---|---|---|
| **Macaroons** | Monotonic caveats, cryptographically chained, verified as the conjunction of every caveat in the chain | Birgisson, Politz, Erlingsson, Taly, Vrable, Lentczner, "Macaroons: Cookies with Contextual Caveats for Decentralized Authorization in the Cloud," NDSS 2014 |
| **Biscuit tokens** | Datalog-based caveats appended per hop; verification requires all checks across all blocks to succeed (explicit chain-wide intersection) | biscuitsec.org / Eclipse Biscuit specification, v3.x |
| **ZCAP-LD** | Normative rule that a delegated capability MUST NOT be less restrictive than its parent; verification walks the full capability chain root-to-leaf | W3C Community Group draft specification, `w3c-ccg/zcap-spec` |
| **UCAN** | Per-hop attenuation (`proofs` array) plus mandatory full-chain re-validation at invocation time | UCAN Working Group specification v1.0.0, `ucan.xyz` |
| **RFC 8693 (OAuth Token Exchange)** | Multi-hop actor chains via nested `act` claims — but explicitly instructs implementers to ignore prior actors for access-control decisions (the opposite of intersection enforcement) | IETF RFC 8693, §4.1 |

Capability-security systems (Macaroons, Biscuit, ZCAP-LD, UCAN) already
solve the core problem cryptographically and are protocol-agnostic bearer
formats. None of them, in their own specifications, addresses carrying
that chain across a *specific named pair* of AI-agent wire protocols using
each protocol's own official SDK.

## What is being actively (and inconclusively) discussed right now

Both protocol communities have independently identified this exact class
of gap, without resolving it:

- **A2A**: [GitHub Discussion #1404](https://github.com/a2aproject/A2A/discussions/1404), "SEP: Capability-based authorization" — an open, unmerged, unanswered draft proposing task-scoped, monotonically-narrowing capability tokens. [Discussion #930](https://github.com/a2aproject/A2A/discussions/930) has a maintainer stating plainly that the protocol has no way today to express scoped, narrower on-behalf-of authority.
- **MCP**: [Issue #333](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/333), "MCP currently seems to treat the client as a single entity which introduces a confused deputy problem" — names the exact three-party narrowing problem and was **closed as "not planned."** The MCP specification's own [Security Best Practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices) document explicitly forbids the naive multi-hop case ("MCP servers MUST NOT accept any tokens that were not explicitly issued for the MCP server").
- **AI-agent research (2026)**: Ibrahim & Li (Huawei), ["Overlaying Governance: A Compositional Authorization Framework for Delegation and Scope in Agentic AI"](https://arxiv.org/abs/2606.03518) gives the most rigorous formal treatment found — an explicit chain-intersection predicate with a stated soundness theorem — but no confirmed runnable A2A/MCP-level conformance code was found accompanying it.

## Classification of overlap

| Area | Classification |
|---|---|
| A2A core specification | No material overlap (no delegation/attenuation concept exists in the ratified spec) |
| A2A community proposals | Weak partial overlap (unmerged, unverified) |
| MCP core specification | No material overlap (explicitly forbids naive token passthrough; no chain-attenuation concept) |
| MCP community proposals | Weak partial overlap (the closest one was closed as "not planned") |
| OAuth Token Exchange (RFC 8693), GNAP | Weak partial overlap (chain representation exists; intersection enforcement is explicitly *not* required) |
| Macaroons / Biscuit / ZCAP-LD / UCAN | **Strong partial overlap** — the core security property is essentially the same; no protocol integration with A2A/MCP exists |
| AI-agent research (2026 arXiv papers, open GitHub proposals) | Strong partial overlap on the formal security model; no verified runnable conformance artifact found matching this exact scenario |

"Strong partial overlap" means: the core delegation/attenuation mechanism
already exists and is well understood, but the specific A2A→MCP
integration and this exact enforcement setting do not appear to have a
prior, independently verified, runnable equivalent.

## What this repository does NOT claim

- It does **not** claim the security property (monotonic attenuation,
  intersection-based enforcement) is novel. It is not — Macaroons predates
  it by over a decade.
- It does **not** claim the delegation representation (grant schema,
  signing method, chain format) is novel. It is a simplified, test-only
  reimplementation of patterns already present in existing capability
  systems.
- It does **not** claim to be the first to apply attenuation concepts to
  AI agents. Multiple 2026 papers and open proposals are already exploring
  this.
- It does **not** propose a new A2A extension standard, a new MCP
  standard, or any specification.
- It does **not** claim research contribution or protocol novelty.
- It is **not** a production authorization system. See the Threat Model
  section of `README.md` for what it deliberately does not provide.

## What may be defensibly said about this repository

- As of this review, no publicly available, independently verified,
  executable repository was found that carries a monotonically-attenuated
  delegation chain across the *official* A2A and MCP SDKs specifically,
  with a working positive/negative conformance pair.
- Both A2A's and MCP's own maintainer communities have identified this
  category of gap in their own issue trackers, and neither has adopted a
  resolution as of the versions checked during this review.
- This repository is a small, reviewable reference artifact for engineers
  evaluating whether their own A2A/MCP integration preserves narrowed
  delegated authority — useful precisely because it is runnable against
  real SDKs rather than being a paper design.

## Review scope and limitations

This review is a targeted literature and specification search, not an
exhaustive survey. It should not be treated as a legal or comprehensive
prior-art clearance. If this repository is ever used as the basis for any
broader claim, a deeper and more current review is warranted before doing
so.
