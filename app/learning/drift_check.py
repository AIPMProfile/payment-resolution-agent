from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.learning.eval_gate import eval_gate_check
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def run_drift_check() -> dict:
    result = eval_gate_check()
    status = result.get("status", "pass")

    if status == "pass":
        logger.info("Drift check passed — all evals within baseline thresholds")
        return {"status": "pass", "action": "none"}

    regressions = result.get("hard_regressions", []) + result.get("soft_regressions", [])
    if not regressions:
        return {"status": "pass", "action": "none"}

    regression_summary = "; ".join(
        f"{r['eval_id']}: {r['current_rate']:.0%} (threshold {r['threshold']:.0%})"
        for r in regressions
    )
    failure_pattern = f"DRIFT_DETECTED|{regression_summary}"

    db = get_supabase_client()
    db.table("policy_suggestions").insert({
        "failure_pattern": failure_pattern,
        "affected_layer": "drift_detection",
        "suggested_fix_text": (
            f"Drift detected at {datetime.now(timezone.utc).isoformat()}. "
            f"The following evals dropped below threshold: {regression_summary}. "
            f"Review recent changes to skill files and policy_rules.json."
        ),
        "confidence": "high" if result.get("hard_regressions") else "medium",
        "status": "pending",
    }).execute()

    logger.warning("Drift detected — created policy_suggestion: %s", regression_summary)
    return {
        "status": status,
        "action": "suggestion_created",
        "regressions": regressions,
    }
