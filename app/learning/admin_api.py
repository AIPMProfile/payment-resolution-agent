from __future__ import annotations
from typing import Optional
"""
Loop 4, Part C: human expert review gate.
Protected endpoints for viewing suggestions, approving/rejecting, and metrics.
Approval atomically updates both the skill file and logs to policy_versions.
"""

import difflib
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter

from fastapi import HTTPException

from app.db.models import AdminSuggestion, ApproveRequest, RejectRequest, MetricsResponse
from app.db.supabase_client import get_supabase_client
from app.knowledge.policy_loader import load_skill, update_skill_file, reload_policy_rules
from app.learning.eval_gate import eval_gate_check

logger = logging.getLogger(__name__)


def _next_version(db, category: str) -> int:
    r = (
        db.table("policy_versions")
        .select("version_number")
        .eq("affected_category", category)
        .order("version_number", desc=True)
        .limit(1)
        .execute()
    )
    return (r.data[0]["version_number"] + 1) if r.data else 1


def _unified_diff(old: str, new: str, label: str) -> str:
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = (new or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"{label} (current)",
        tofile=f"{label} (proposed)",
    )
    return "".join(diff)


def _parse_category(failure_pattern: str) -> Optional[str]:
    """Category is encoded as 'CATEGORY|rest of pattern' in failure_pattern."""
    if "|" in failure_pattern:
        return failure_pattern.split("|", 1)[0]
    return None


async def annotate_trace(ticket_id: str, label: str, note: Optional[str] = None) -> dict:
    if label not in ("pass", "fail"):
        raise HTTPException(400, "label must be 'pass' or 'fail'")

    db = get_supabase_client()
    r = (
        db.table("eval_queue")
        .select("eval_id")
        .eq("ticket_id", ticket_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "No eval_queue row found for this ticket_id")

    eval_id = str(r.data[0]["eval_id"])
    db.table("eval_queue").update({
        "human_review_label": label,
        "human_review_note": note,
        "human_reviewed_at": datetime.now(timezone.utc).isoformat(),
        "human_reviewed_by": "admin",
    }).eq("eval_id", eval_id).execute()

    return {"eval_id": eval_id, "label": label}


async def get_pending_suggestions() -> list[AdminSuggestion]:
    db = get_supabase_client()
    r = (
        db.table("policy_suggestions")
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )

    suggestions = []
    for row in (r.data or []):
        category = _parse_category(row.get("failure_pattern", ""))
        diff = None
        if category and row.get("suggested_fix_text"):
            current = load_skill(category)
            diff = _unified_diff(current, row["suggested_fix_text"], category)

        suggestions.append(AdminSuggestion(
            id=str(row["suggestion_id"]),
            failure_pattern=row["failure_pattern"],
            affected_layer=row["affected_layer"],
            affected_category=category,
            suggested_fix_text=row["suggested_fix_text"],
            confidence=float(row.get("confidence") or 0),
            source_trace_ids=row.get("source_trace_ids") or [],
            status=row["status"],
            created_at=str(row["created_at"]),
            diff=diff,
        ))
    return suggestions


async def approve_suggestion(suggestion_id: str, req: ApproveRequest) -> dict:
    db = get_supabase_client()

    r = db.table("policy_suggestions").select("*").eq("suggestion_id", suggestion_id).execute()
    if not r.data:
        raise HTTPException(404, "Suggestion not found")

    suggestion = r.data[0]
    if suggestion["status"] != "pending":
        raise HTTPException(400, f"Suggestion is already {suggestion['status']}")

    category = _parse_category(suggestion.get("failure_pattern", ""))
    new_content = suggestion["suggested_fix_text"]
    old_content = load_skill(category) if category else None

    before_eval = eval_gate_check()

    if category and new_content:
        update_skill_file(category, new_content)
        reload_policy_rules()
        logger.info("Skill file updated: %s by %s", category, req.reviewer)

    after_eval = eval_gate_check()

    if after_eval.get("hard_regressions"):
        if old_content and category:
            update_skill_file(category, old_content)
            reload_policy_rules()
        raise HTTPException(
            422,
            {
                "error": "Eval gate failed — hard regressions detected, change reverted",
                "regressions": after_eval["hard_regressions"],
                "before_status": before_eval.get("status"),
                "after_status": after_eval.get("status"),
            },
        )

    version = _next_version(db, category or "GENERAL")
    db.table("policy_versions").insert({
        "version_number": version,
        "affected_category": category or "GENERAL",
        "old_content": old_content,
        "new_content": new_content,
        "change_reason": f"Approved by {req.reviewer}",
        "suggested_by": req.reviewer,
        "suggestion_id": suggestion_id,
    }).execute()

    db.table("policy_suggestions").update({
        "status": "approved",
        "reviewed_by": req.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("suggestion_id", suggestion_id).execute()

    return {
        "status": "approved",
        "version": version,
        "category": category,
        "eval_gate": {
            "before": before_eval.get("status"),
            "after": after_eval.get("status"),
            "regressions": after_eval.get("soft_regressions", []),
            "improvements": after_eval.get("improvements", []),
        },
    }


async def reject_suggestion(suggestion_id: str, req: RejectRequest) -> dict:
    db = get_supabase_client()

    r = db.table("policy_suggestions").select("suggestion_id, status").eq("suggestion_id", suggestion_id).execute()
    if not r.data:
        raise HTTPException(404, "Suggestion not found")
    if r.data[0]["status"] != "pending":
        raise HTTPException(400, f"Suggestion is already {r.data[0]['status']}")

    db.table("policy_suggestions").update({
        "status": "rejected",
        "reviewed_by": req.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "rejection_reason": req.reason,
    }).eq("suggestion_id", suggestion_id).execute()

    return {"status": "rejected"}


async def rollback_to_version(version_id: str, reviewer: str) -> dict:
    db = get_supabase_client()
    r = db.table("policy_versions").select("*").eq("version_id", version_id).execute()
    if not r.data:
        raise HTTPException(404, "Version not found")

    pv = r.data[0]
    category = pv["affected_category"]
    old_content = pv.get("old_content")

    if old_content and category:
        update_skill_file(category, old_content)
        reload_policy_rules()
        logger.info("Rolled back %s to version before %s by %s", category, version_id, reviewer)

    return {"status": "rolled_back", "category": category}


async def get_eval_gate_status() -> dict:
    return eval_gate_check()


async def get_metrics() -> MetricsResponse:
    db = get_supabase_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    # Policy pass rate from eval_queue policy_checks_json
    traces_r = (
        db.table("eval_queue")
        .select("policy_checks_json")
        .not_.is_("policy_checks_json", "null")
        .gte("created_at", cutoff)
        .execute()
    )
    total_checks = pass_checks = 0
    for row in (traces_r.data or []):
        layer1 = (row.get("policy_checks_json") or {}).get("layer1", [])
        for result in layer1:
            total_checks += 1
            if result.get("passed"):
                pass_checks += 1
    policy_pass_rate = (pass_checks / total_checks) if total_checks else 1.0

    # Helpful score distribution
    fb_r = (
        db.table("eval_queue")
        .select("helpful_score")
        .not_.is_("helpful_score", "null")
        .gte("created_at", cutoff)
        .execute()
    )
    scores = [row["helpful_score"] for row in (fb_r.data or []) if row.get("helpful_score")]
    helpful_dist = {str(k): v for k, v in Counter(scores).items()}

    # Timeline accuracy rate
    tl_r = (
        db.table("eval_queue")
        .select("timeline_accurate")
        .not_.is_("timeline_accurate", "null")
        .gte("created_at", cutoff)
        .execute()
    )
    tl_rows = tl_r.data or []
    accurate = sum(1 for r in tl_rows if r.get("timeline_accurate") in ("yes_as_expected", "roughly"))
    tl_rate = (accurate / len(tl_rows)) if tl_rows else 1.0

    # Escalation rate
    esc_r = (
        db.table("tickets")
        .select("status")
        .eq("status", "escalated")
        .gte("created_at", cutoff)
        .execute()
    )
    all_r = (
        db.table("tickets")
        .select("status")
        .gte("created_at", cutoff)
        .execute()
    )
    esc_count = len(esc_r.data or [])
    total_tickets = len(all_r.data or [])
    esc_rate = (esc_count / total_tickets) if total_tickets else 0.0

    # Cron failure counts
    cron_r = (
        db.table("eval_queue")
        .select("failure_category")
        .like("failure_category", "cron_failure:%")
        .gte("created_at", cutoff)
        .execute()
    )
    cron_failures = Counter(
        r["failure_category"].replace("cron_failure:", "") for r in (cron_r.data or [])
    )

    return MetricsResponse(
        policy_pass_rate=round(policy_pass_rate, 4),
        helpful_score_distribution=helpful_dist,
        timeline_accuracy_rate=round(tl_rate, 4),
        escalation_rate=round(esc_rate, 4),
        cron_failure_counts=dict(cron_failures),
        period="last_24h",
    )
