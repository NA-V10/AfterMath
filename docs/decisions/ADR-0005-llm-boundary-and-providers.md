# ADR-0005: LLM boundary and provider-neutral abstraction

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Agents need LLMs to interpret free text and explain results, but numbers, graph facts and authorisation must be trustworthy. The app must work with no API key.

## Decision
LLMs only (a) extract structured fields from untrusted text, whose references are resolved by deterministic tools, and (b) write explanations grounded in tool outputs and verified by a grounding check. Own thin `LLMProvider` protocol with Anthropic, OpenAI-compatible and Deterministic implementations, plus a FallbackChain. Default to Deterministic when no key is set. Details: [AGENT_DESIGN.md](../AGENT_DESIGN.md).

## Consequences
- (+) No vendor lock-in; local models via OpenAI-compatible endpoints; fully offline demo.
- (+) LangChain chat-model abstractions avoided: fewer dependencies and less churn.
- (-) We maintain small adapters ourselves (~150 LOC each).

## Alternatives considered
LangChain model wrappers (heavy, churn); single hard-coded vendor SDK; letting the LLM compute impacts or plans.
