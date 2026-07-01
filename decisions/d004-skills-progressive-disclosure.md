# Decision: Skills as progressive disclosure, not monolithic prompts

**Date:** 2026-06-25
**Status:** Active
**Category:** Architecture

## Context
Most agent systems embed all resolution knowledge in the system prompt. This means every call carries every category's rules, increasing cost and creating category contamination risk (UPI rules leaking into POT responses).

## Decision
Resolution knowledge lives in per-category skill files (`skills/*.md`), loaded after classification. The base system prompt contains only structural rules (format, forbidden phrases, grounding). Skills are never inlined into `prompts.py`.

## Why
Loading only the relevant skill reduces context window usage and prevents category contamination. Skills can be versioned independently via the `policy_versions` table, and the admin approval flow updates skills atomically with `policy_rules.json`.

## Consequences
- Adding a new category requires: new classifier label, new skill file, new tests
- Skill files follow a strict 5-section format (What happened, What you know, What you do not know, Resolution rules, What to never say)
- `policy_rules.json` and skill files must always be updated together -- never one without the other
