# Decision: Code evals as release gate, not just monitoring

**Date:** 2026-06-29
**Status:** Active
**Category:** Eval framework

## Context
Without a release gate, prompt and skill changes go live without validation. Monitoring catches regressions after they affect users. A gate catches them before deployment.

## Decision
Implement the eval gate pattern: reference dataset (`golden_dataset.json`) with baseline pass rates (`eval_baseline.json`), explicit thresholds, and a release gate (`test_release_gate.py`) that produces a SHIP or BLOCK decision.

Hard gates (NO_GUARANTEE, ESCALATE_DISTRESS) block the release entirely. Soft gates (CITATION_FORMAT, EMPATHY) warn but don't block.

## Why
The golden dataset + eval baseline pattern catches regressions BEFORE deployment. Failure distribution analysis (are failures clustered on specific categories?) and cross-eval correlation (which inputs fail multiple evals?) direct improvement effort to the highest-impact areas.

## Consequences
- Admin approval in the Learning loop runs the eval gate before applying any suggestion
- Weekly drift check compares current scores to baseline thresholds
- Adding a new eval requires updating both the structural_evals code and the baseline file
