# How to Write Eval Criteria for This Agent

## The formula

Every criterion is a binary question (1 = pass, 0 = fail) with a concrete PASS and FAIL example. The **score** comes from running many cases — 50 golden dataset cases scored on 18 criteria gives 900 data points. The average is the score.

Write criteria from failures you have seen, not from imagination.

## Hard vs Soft gates

**Hard gates** (threshold usually 1.00) block deployment:
- NO_GUARANTEE, NO_FRAUD_VERDICT, ESCALATE_DISTRESS — regulatory and safety
- SCHEMA_COMPLETE, TOOL_SEQUENCE, TXN_ID_GROUNDED — architectural invariants

**Soft gates** (threshold 0.85-0.90) warn but don't block:
- CITATION_FORMAT, EMPATHY_ACKNOWLEDGMENT, LENGTH_LIMIT — quality signals
- A soft gate trending down is an early warning; a hard gate failure is a stop-ship

## Adding a new criterion

1. Document the failure that motivated it (what went wrong, when, impact)
2. Write the binary question with PASS/FAIL examples
3. Decide: hard gate or soft gate?
4. Add to `app/verification/policy_checker.py` (hard) or `structural_evals.py` (soft)
5. Add inline comment: `# Failure: <what happened> | Rule: <rule_id>`
6. Update `tests/eval_baseline.json` with baseline_pass_rate and threshold
7. Run `pytest tests/test_golden_evals.py -v` to establish baseline

## Scoring flow

```
Golden dataset (50 cases, 65 turns)
    ↓
Each turn scored on 18 binary criteria
    ↓
Per-criterion pass rate (0.00 to 1.00)
    ↓
Compare to threshold in eval_baseline.json
    ↓
Release gate: SHIP (all hard gates pass) or BLOCK (any hard gate fails)
```

## Files involved

| File | Purpose |
|---|---|
| `evals/*.md` | PM-readable criteria (this folder) |
| `app/verification/policy_checker.py` | Hard gate implementation |
| `app/verification/structural_evals.py` | Soft gate implementation |
| `tests/eval_baseline.json` | Baseline pass rates and thresholds |
| `tests/golden_dataset.json` | 50 reference cases with expected outputs |
| `tests/test_release_gate.py` | SHIP/BLOCK decision logic |
| `tests/test_golden_evals.py` | Runs golden dataset through all checks |
