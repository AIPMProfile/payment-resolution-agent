# Decision: Model routing locked by function, not by cost

**Date:** 2026-06-25
**Status:** Active
**Category:** Model routing

## Context
Multi-model agents typically route by cost -- use the cheapest model everywhere, upgrade where quality suffers. This optimizes for cost but not for role separation.

## Decision
Route by function:
- **Haiku** -- classification only. One call per turn. Never composition.
- **Sonnet** -- response composition and nightly analysis suggestions. Never classification or judging.
- **Opus** -- LLM judge only. Never composition.

No routing changes without explicit approval.

## Why
Classification is a structured label task -- Haiku is sufficient and fast. Composition needs nuance and regulatory awareness -- Sonnet handles this. The LLM judge uses Opus to reduce self-evaluation bias (Opus judging Sonnet output, not Sonnet judging itself). Using a cheaper model for the wrong task saves money but costs quality in ways that are hard to detect.

## Consequences
- Model IDs are logged in every `eval_queue` trace for auditability
- Swapping models requires updating CLAUDE.md, AGENTS.md, and test expectations
