# Decision: Regulation-backed assurance over blanket phrase bans

**Date:** 2026-06-29
**Status:** Active
**Category:** Policy

## Context
The initial policy banned ALL assurance language to prevent the agent from making promises it couldn't keep. But this is the exact problem users face in the current Jupiter app -- they get no assurance that their money is coming back, creating anxiety and repeat contacts.

## Decision
Allow the agent to use "will be credited", "will be refunded" when grounded in regulation (NPCI rules, NEFT batch schedule). Ban only subjective assurances: "guaranteed", "definitely", "probably", "your money is safe".

## Why
NPCI Circular NPCI/2020-21/UPI/0138 mandates auto-reversal within T+5 business days. This is a regulatory fact, not a promise. The agent cites the regulation as the source of the commitment, distinguishing "your bank is required to reverse this" (fact) from "I guarantee you'll get it back" (subjective promise).

## Alternatives considered
- Keep blanket ban, use only "expected to reverse" -- too weak, doesn't solve the user's anxiety
- Allow all assurance language -- too risky, agent could over-promise on timing

## Consequences
- `policy_rules.json` forbidden_phrases updated to ban subjective language only
- Skill files (`UPI_FAILURE.md`, `POT_WITHDRAWAL.md`) updated with grounded phrasing
- Regression test `test_regression_guarantee_language.py` locks this behavior
- Golden dataset updated with regulation-backed assurance examples
