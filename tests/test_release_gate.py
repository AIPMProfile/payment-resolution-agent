"""
Release gate: Calibre Labs eval framework implementation.

Pattern: Prompt Change -> Run Eval Suite on reference dataset -> Compare to baseline + thresholds -> Gate Decision (ship or block)

Reads eval_baseline.json for thresholds. Runs policy_checker and structural_evals
against golden_dataset.json sample cards. Reports:
  1. Pass rate per eval with baseline comparison
  2. Failure distribution by input type (category, persona)
  3. Cross-eval correlation (rows failing multiple evals)
  4. Gate decision: ship or block

Run:
    pytest tests/test_release_gate.py -v
    pytest tests/test_release_gate.py -v -s   # see full report
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from app.verification.policy_checker import run_policy_checks
from app.verification.structural_evals import run_structural_evals

_GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"
_BASELINE_PATH = Path(__file__).parent / "eval_baseline.json"

_GOLDEN = json.loads(_GOLDEN_PATH.read_text())
_BASELINE = json.loads(_BASELINE_PATH.read_text())


def _build_eval_inputs() -> list[dict]:
    """Extract card-type turns from golden dataset for eval runs."""
    inputs = []
    for case in _GOLDEN:
        for turn in case["turns"]:
            expected = turn["expected"]
            if expected["response_type"] != "card":
                continue
            card = expected.get("sample_card")
            if not card:
                continue
            inputs.append({
                "case_id": case["id"],
                "persona": case.get("persona", "unknown"),
                "category": case.get("category", card.get("category", "UNKNOWN")),
                "user_message": turn["user"],
                "card": card,
                "turn": turn["turn"],
            })
    return inputs


def _run_all_evals(inputs: list[dict]) -> dict:
    """Run policy_checker + structural_evals on all inputs. Returns results keyed by eval_id."""
    eval_results: dict[str, list[dict]] = defaultdict(list)
    row_results: list[dict] = []

    for inp in inputs:
        card = inp["card"]
        user_msg = inp["user_message"]
        category = inp["category"]

        retrieved_txn = None
        if card.get("reference"):
            import re
            txn_match = re.search(r"TXN\d+", card["reference"])
            if txn_match:
                retrieved_txn = {
                    "txn_id": txn_match.group(0),
                    "amount": 1000,
                    "status": "failed",
                    "initiated_at": "2026-06-20T10:00:00+00:00",
                }

        tool_metadata = {
            "classify_fired": True,
            "retrieve_fired": True,
            "params_complete": True,
            "amount_mentioned": None,
            "retrieved_amount": retrieved_txn.get("amount") if retrieved_txn else None,
            "category_in_params": category,
        }

        _, policy_results = run_policy_checks(card, retrieved_txn, user_msg)
        struct_results = run_structural_evals(card, tool_metadata, user_msg, retrieved_txn)

        failed_evals = []

        for r in policy_results:
            eval_results[r["rule_id"]].append({
                "passed": r["passed"],
                "case_id": inp["case_id"],
                "persona": inp["persona"],
                "category": category,
            })
            if not r["passed"]:
                failed_evals.append(r["rule_id"])

        for r in struct_results:
            eval_results[r["eval_id"]].append({
                "passed": r["passed"],
                "case_id": inp["case_id"],
                "persona": inp["persona"],
                "category": category,
            })
            if not r["passed"]:
                failed_evals.append(r["eval_id"])

        row_results.append({
            "case_id": inp["case_id"],
            "persona": inp["persona"],
            "category": category,
            "failed_evals": failed_evals,
        })

    return {"eval_results": eval_results, "row_results": row_results}


def _compute_pass_rates(eval_results: dict) -> dict[str, float]:
    rates = {}
    for eval_id, results in eval_results.items():
        if not results:
            rates[eval_id] = 1.0
            continue
        passed = sum(1 for r in results if r["passed"])
        rates[eval_id] = passed / len(results)
    return rates


def _failure_distribution(eval_results: dict) -> dict[str, dict[str, list[str]]]:
    """Group failures by category and persona for each eval."""
    dist: dict[str, dict[str, list[str]]] = {}
    for eval_id, results in eval_results.items():
        failures = [r for r in results if not r["passed"]]
        if not failures:
            continue
        by_category: dict[str, int] = defaultdict(int)
        by_persona: dict[str, int] = defaultdict(int)
        for f in failures:
            by_category[f["category"]] += 1
            by_persona[f["persona"]] += 1
        dist[eval_id] = {
            "by_category": dict(by_category),
            "by_persona": dict(by_persona),
            "failed_cases": [f["case_id"] for f in failures],
        }
    return dist


def _cross_eval_correlation(row_results: list[dict]) -> list[dict]:
    """Find rows that fail multiple evals — these are the most problematic inputs."""
    multi_fail = []
    for row in row_results:
        if len(row["failed_evals"]) > 1:
            multi_fail.append({
                "case_id": row["case_id"],
                "persona": row["persona"],
                "category": row["category"],
                "failed_evals": row["failed_evals"],
                "count": len(row["failed_evals"]),
            })
    return sorted(multi_fail, key=lambda x: x["count"], reverse=True)


def _gate_decision(pass_rates: dict[str, float], baseline: dict) -> tuple[str, list[str]]:
    """Compare pass rates against baseline thresholds. Returns ('ship'|'block', [reasons])."""
    blockers = []

    all_baselines = {}
    all_baselines.update(baseline.get("policy_checks", {}))
    all_baselines.update(baseline.get("structural_evals", {}))

    for eval_id, config in all_baselines.items():
        threshold = config["threshold"]
        gate = config["gate"]
        actual = pass_rates.get(eval_id)
        if actual is None:
            continue
        if actual < threshold:
            blockers.append(
                f"{eval_id}: {actual:.1%} < {threshold:.1%} threshold ({gate} gate)"
            )

    agg = baseline.get("aggregate_thresholds", {})
    if agg.get("overall_pass_rate"):
        all_rates = list(pass_rates.values())
        overall = sum(all_rates) / len(all_rates) if all_rates else 0
        if overall < agg["overall_pass_rate"]["threshold"]:
            blockers.append(
                f"Overall pass rate: {overall:.1%} < {agg['overall_pass_rate']['threshold']:.1%}"
            )

    decision = "block" if blockers else "ship"
    return decision, blockers


class TestReleaseGate:
    """Release gate suite — runs all evals against golden dataset and gates on thresholds."""

    @pytest.fixture(scope="class")
    def eval_data(self):
        inputs = _build_eval_inputs()
        assert len(inputs) > 0, "No card-type golden samples found"
        return _run_all_evals(inputs)

    @pytest.fixture(scope="class")
    def pass_rates(self, eval_data):
        return _compute_pass_rates(eval_data["eval_results"])

    def test_hard_gates_pass(self, eval_data, pass_rates):
        """All hard-gate evals must meet their threshold — zero tolerance."""
        all_baselines = {}
        all_baselines.update(_BASELINE.get("policy_checks", {}))
        all_baselines.update(_BASELINE.get("structural_evals", {}))

        hard_failures = []
        for eval_id, config in all_baselines.items():
            if config["gate"] != "hard":
                continue
            actual = pass_rates.get(eval_id)
            if actual is not None and actual < config["threshold"]:
                hard_failures.append(
                    f"{eval_id}: {actual:.1%} < {config['threshold']:.1%}"
                )

        assert not hard_failures, (
            f"Hard gate failures (blocking release):\n" +
            "\n".join(f"  - {f}" for f in hard_failures)
        )

    def test_soft_gates_within_tolerance(self, eval_data, pass_rates):
        """Soft-gate evals should meet thresholds — warns but doesn't block."""
        all_baselines = {}
        all_baselines.update(_BASELINE.get("policy_checks", {}))
        all_baselines.update(_BASELINE.get("structural_evals", {}))

        soft_warnings = []
        for eval_id, config in all_baselines.items():
            if config["gate"] != "soft":
                continue
            actual = pass_rates.get(eval_id)
            if actual is not None and actual < config["threshold"]:
                soft_warnings.append(
                    f"{eval_id}: {actual:.1%} < {config['threshold']:.1%}"
                )

        if soft_warnings:
            pytest.xfail(
                f"Soft gate warnings (non-blocking):\n" +
                "\n".join(f"  - {w}" for w in soft_warnings)
            )

    def test_overall_pass_rate(self, pass_rates):
        """Aggregate pass rate must exceed the overall threshold."""
        all_rates = list(pass_rates.values())
        overall = sum(all_rates) / len(all_rates) if all_rates else 0
        threshold = _BASELINE["aggregate_thresholds"]["overall_pass_rate"]["threshold"]
        assert overall >= threshold, (
            f"Overall pass rate {overall:.1%} < {threshold:.1%} threshold"
        )

    def test_no_cross_eval_hotspots(self, eval_data):
        """No single golden case should fail more than 2 evals simultaneously."""
        correlations = _cross_eval_correlation(eval_data["row_results"])
        hotspots = [c for c in correlations if c["count"] > 2]
        assert not hotspots, (
            f"Cross-eval hotspots (cases failing >2 evals):\n" +
            "\n".join(
                f"  - {h['case_id']} ({h['persona']}): {h['failed_evals']}"
                for h in hotspots
            )
        )

    def test_failure_distribution_not_clustered(self, eval_data):
        """Failures should not cluster on a single category or persona."""
        dist = _failure_distribution(eval_data["eval_results"])
        clustered = []
        for eval_id, info in dist.items():
            total_failures = len(info["failed_cases"])
            if total_failures < 2:
                continue
            for cat, count in info.get("by_category", {}).items():
                if count == total_failures and total_failures > 1:
                    clustered.append(f"{eval_id}: all {count} failures in {cat}")
            for persona, count in info.get("by_persona", {}).items():
                if count == total_failures and total_failures > 1:
                    clustered.append(f"{eval_id}: all {count} failures from persona '{persona}'")

        if clustered:
            pytest.xfail(
                f"Clustered failures (investigate input coverage):\n" +
                "\n".join(f"  - {c}" for c in clustered)
            )

    def test_gate_decision(self, pass_rates):
        """Final gate decision: ship or block."""
        decision, reasons = _gate_decision(pass_rates, _BASELINE)
        if decision == "block":
            pytest.fail(
                f"RELEASE BLOCKED:\n" +
                "\n".join(f"  - {r}" for r in reasons)
            )

    def test_print_report(self, eval_data, pass_rates, capsys):
        """Print the full eval report for human review (always passes)."""
        all_baselines = {}
        all_baselines.update(_BASELINE.get("policy_checks", {}))
        all_baselines.update(_BASELINE.get("structural_evals", {}))

        lines = ["\n=== RELEASE GATE REPORT ===\n"]
        lines.append(f"Golden dataset cards evaluated: {len(eval_data['row_results'])}")
        lines.append("")

        lines.append("--- Pass Rates vs Baseline ---")
        for eval_id, rate in sorted(pass_rates.items()):
            config = all_baselines.get(eval_id, {})
            baseline_rate = config.get("baseline_pass_rate", "N/A")
            threshold = config.get("threshold", "N/A")
            gate = config.get("gate", "?")
            status = "PASS" if isinstance(threshold, float) and rate >= threshold else "FAIL"
            bl_str = f"{baseline_rate:.0%}" if isinstance(baseline_rate, float) else baseline_rate
            th_str = f"{threshold:.0%}" if isinstance(threshold, float) else threshold
            lines.append(f"  {eval_id:30s}  {rate:.0%}  (baseline: {bl_str}, threshold: {th_str}, {gate}) [{status}]")

        dist = _failure_distribution(eval_data["eval_results"])
        if dist:
            lines.append("\n--- Failure Distribution ---")
            for eval_id, info in dist.items():
                lines.append(f"  {eval_id}:")
                lines.append(f"    By category: {info['by_category']}")
                lines.append(f"    By persona:  {info['by_persona']}")
                lines.append(f"    Cases:       {info['failed_cases']}")

        correlations = _cross_eval_correlation(eval_data["row_results"])
        if correlations:
            lines.append("\n--- Cross-Eval Correlation ---")
            for c in correlations:
                lines.append(f"  {c['case_id']} ({c['persona']}): {c['failed_evals']}")

        decision, reasons = _gate_decision(pass_rates, _BASELINE)
        lines.append(f"\n--- Gate Decision: {decision.upper()} ---")
        if reasons:
            for r in reasons:
                lines.append(f"  - {r}")

        report = "\n".join(lines)
        print(report)
