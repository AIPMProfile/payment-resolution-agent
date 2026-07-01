"""
Loop 3, Event B: resolution window expiry follow-up.
Runs daily. Finds tickets past deadline with status=open.
Fires stage 2 follow-up: "Did your money arrive?"
Responses written to eval_queue.
"""

import logging
from datetime import datetime, timezone

from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_cron_failure(cron_name: str, error: str) -> None:
    try:
        db = get_supabase_client()
        db.table("eval_queue").insert({
            "ticket_id": None,
            "failure_category": f"cron_failure:{cron_name}",
            "failure_freetext": error,
        }).execute()
    except Exception:
        pass


def run_followup_check() -> None:
    try:
        _run_followup_check_inner()
    except Exception as exc:
        logger.error("followup_cron failed: %s", exc)
        _log_cron_failure("followup", str(exc))


def _run_followup_check_inner() -> None:
    db = get_supabase_client()
    now = _now_iso()

    # Find tickets past resolution_deadline, still open, no followup sent yet
    result = (
        db.table("tickets")
        .select("ticket_id, user_id, category, resolution_deadline")
        .lt("resolution_deadline", now)
        .eq("status", "open")
        .execute()
    )

    tickets = result.data or []
    logger.info("Followup check: %d ticket(s) past deadline", len(tickets))

    for ticket in tickets:
        ticket_id = ticket["ticket_id"]

        # Check if we already sent a followup (resolution_confirmed row exists)
        existing = (
            db.table("eval_queue")
            .select("eval_id")
            .eq("ticket_id", ticket_id)
            .not_.is_("resolution_confirmed", "null")
            .execute()
        )
        if existing.data:
            continue  # already sent

        # Insert stage2 followup row
        db.table("eval_queue").insert({
            "ticket_id": ticket_id,
            "classification": ticket.get("category"),
            "resolution_confirmed": False,
        }).execute()

        # Mark ticket as pending confirmation
        db.table("tickets").update({
            "status": "pending_confirmation",
            "updated_at": _now_iso(),
        }).eq("ticket_id", ticket_id).execute()

        logger.info("Stage 2 followup queued for ticket %s", ticket_id)


def handle_stage2_response(ticket_id: str, answer: str) -> dict:
    db = get_supabase_client()

    if answer == "no":
        db.table("tickets").update({
            "status": "escalated",
            "updated_at": _now_iso(),
        }).eq("ticket_id", ticket_id).execute()

        db.table("eval_queue").update({
            "resolution_confirmed": False,
        }).eq("ticket_id", ticket_id).not_.is_("resolution_confirmed", "null").execute()

        return {"action": "escalated", "message": "Connecting you to a senior colleague immediately."}

    if answer == "yes":
        db.table("tickets").update({
            "status": "awaiting_timeline",
            "updated_at": _now_iso(),
        }).eq("ticket_id", ticket_id).execute()

        db.table("eval_queue").update({
            "resolution_confirmed": True,
        }).eq("ticket_id", ticket_id).not_.is_("resolution_confirmed", "null").execute()

        return {
            "action": "timeline_question",
            "message": "Was our timeline accurate?",
            "options": ["yes_as_expected", "roughly", "no_took_longer"],
        }

    return {"action": "unknown", "message": "Please answer yes or no."}


def handle_stage2_timeline(ticket_id: str, answer: str) -> dict:
    db = get_supabase_client()

    db.table("eval_queue").update({
        "timeline_accurate": answer,
    }).eq("ticket_id", ticket_id).not_.is_("resolution_confirmed", "null").execute()

    db.table("tickets").update({
        "status": "resolved",
        "updated_at": _now_iso(),
    }).eq("ticket_id", ticket_id).execute()

    _check_timeline_pattern(ticket_id, db)

    return {"action": "resolved", "message": "Thank you for the feedback. Ticket closed."}


def _check_timeline_pattern(ticket_id: str, db) -> None:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    t_r = db.table("tickets").select("category").eq("ticket_id", ticket_id).execute()
    if not t_r.data:
        return
    category = t_r.data[0].get("category")
    if not category:
        return

    q_r = (
        db.table("eval_queue")
        .select("timeline_accurate")
        .eq("timeline_accurate", "no_took_longer")
        .gte("created_at", cutoff)
        .execute()
    )

    if len(q_r.data or []) >= 3:
        db.table("policy_suggestions").insert({
            "failure_pattern": f"{category}|Timeline inaccurate 3+ times in 7 days",
            "affected_layer": "policy",
            "suggested_fix_text": f"Review resolution timeline stated in {category} skill file",
            "confidence": "0.9",
            "source_trace_ids": [],
            "status": "pending",
        }).execute()
        logger.info("policy_calibration_issue flagged for category %s", category)
