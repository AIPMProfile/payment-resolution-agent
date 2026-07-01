from __future__ import annotations

import json
import logging
from pathlib import Path

from app.verification.policy_checker import run_policy_checks
from app.verification.structural_evals import run_structural_evals

logger = logging.getLogger(__name__)

_GOLDEN_PATH = Path(__file__).parents[2] / "tests" / "golden_dataset.json"
_BASELINE_PATH = Path(__file__).parents[2] / "tests" / "eval_baseline.json"


def _load_golden_dataset() -> list[dict]:
    with open(_GOLDEN_PATH) as f:
        return json.load(f)


def load_baseline() -> dict:
    with open(_BASELINE_PATH) as f:
        return json.load(f)


def _run_checks_on_sample(case: dict) -> dict:
    turn = case["turns"][0]
    expected = turn["expected"]

    if expected.get("response_type") != "card":
        return {"skipped": True, "id": case["id"]}

    card = expected.get("sample_card", {})
    if not card:
        return {"skipped": True, "id": case["id"]}

    txn = case.get("transaction")
    user_msg = turn["user"]

    tool_metadata = {
        "classify_fired": True,
        "retrieve_fired": True,
        "params_complete": True,
        "amount_mentioned": txn.get("amount") if txn else None,
        "retrieved_amount": txn.get("amount") if txn else None,
    }

    policy_failures, policy_all = run_policy_checks(card, txn, user_msg)
    structural_results = run_structural_evals(card, tool_metadata, user_msg, txn)

    return {
        "skipped": False,
        "id": case["id"],
        "group": case["group"],
        "policy_results": policy_all,
        "policy_failures": policy_failures,
        "structural_results": structural_results,
    }


def run_golden_eval() -> dict:
    dataset = _load_golden_dataset()
    all_results = []

    for case in dataset:
        result = _run_checks_on_sample(case)
        if not result.get("skipped"):
            all_results.append(result)

    eval_counts: dict[str, dict] = {}

    for result in all_results:
        for check in result["policy_results"]:
            rid = check["rule_id"]
            if rid not in eval_counts:
                eval_counts[rid] = {"passed": 0, "total": 0, "layer": "policy_checks"}
            eval_counts[rid]["total"] += 1
            if check["passed"]:
                eval_counts[rid]["passed"] += 1

        for ev in result["structural_results"]:
            eid = ev["eval_id"]
            if eid not in eval_counts:
                eval_counts[eid] = {"passed": 0, "total": 0, "layer": "structural_evals"}
            eval_counts[eid]["total"] += 1
            if ev["passed"]:
                eval_counts[eid]["passed"] += 1

    pass_rates = {}
    for eid, counts in eval_counts.items():
        pass_rates[eid] = {
            "pass_rate": round(counts["passed"] / counts["total"], 4) if counts["total"] else 1.0,
            "passed": counts["passed"],
            "total": counts["total"],
            "layer": counts["layer"],
        }

    return {
        "cases_evaluated": len(all_results),
        "cases_skipped": len(dataset) - len(all_results),
        "pass_rates": pass_rates,
    }


def compare_to_baseline(current_rates: dict) -> dict:
    baseline = load_baseline()
    regressions = []
    improvements = []

    for layer_key in ["policy_checks", "structural_evals"]:
        layer_baselines = baseline.get(layer_key, {})
        for eval_id, config in layer_baselines.items():
            threshold = config.get("threshold", 0)
            gate = config.get("gate", "soft")
            current = current_rates.get("pass_rates", {}).get(eval_id, {})
            current_rate = current.get("pass_rate", 1.0)
            baseline_rate = config.get("baseline_pass_rate", 1.0)

            if current_rate < threshold:
                regressions.append({
                    "eval_id": eval_id,
                    "gate": gate,
                    "current_rate": current_rate,
                    "threshold": threshold,
                    "baseline_rate": baseline_rate,
                    "delta": round(current_rate - baseline_rate, 4),
                })
            elif current_rate > baseline_rate:
                improvements.append({
                    "eval_id": eval_id,
                    "current_rate": current_rate,
                    "baseline_rate": baseline_rate,
                    "delta": round(current_rate - baseline_rate, 4),
                })

    hard_regressions = [r for r in regressions if r["gate"] == "hard"]

    return {
        "status": "fail" if hard_regressions else ("warn" if regressions else "pass"),
        "hard_regressions": hard_regressions,
        "soft_regressions": [r for r in regressions if r["gate"] == "soft"],
        "improvements": improvements,
    }


def eval_gate_check() -> dict:
    current = run_golden_eval()
    comparison = compare_to_baseline(current)
    return {**current, **comparison}
