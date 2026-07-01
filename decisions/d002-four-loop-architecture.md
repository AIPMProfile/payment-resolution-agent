# Decision: Four-loop architecture with strict domain boundaries

**Date:** 2026-06-25
**Status:** Active
**Category:** Architecture

## Context
Agent systems typically run as a single pipeline: classify, generate, return. This makes it impossible to audit which component made a decision, and policy checks contaminated by LLM non-determinism can't be reproduced.

## Decision
Separate the agent into 4 loops with enforced boundaries:
- **Core loop** (classify + compose) -- the LLM-powered pipeline
- **Verification loop** (policy checks + structural evals) -- deterministic, no LLM calls
- **Lifecycle loop** (chat handler, follow-up cron, auto-close cron) -- event-driven orchestration
- **Learning loop** (feedback, nightly analysis, admin gate, eval gate, drift check) -- improvement with human approval

No cross-boundary writes. Core never writes to eval_queue. Verification never calls the Anthropic API. Learning never auto-applies suggestions.

## Why
Each loop has a different correctness guarantee. Verification must stay deterministic so policy checks are reproducible. Learning must never auto-apply for regulatory compliance. Mixing loops would make the system impossible to audit.

## Alternatives considered
- Single-loop agent with inline checks -- no clear audit trail, policy checks contaminated by LLM non-determinism
- Two loops (agent + admin) -- insufficient separation between policy enforcement and scoring
