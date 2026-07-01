"""
Loop 3, Event C: ticket auto-close.
Runs daily. Closes tickets where resolution_deadline has passed 48h ago and status is still open.
"""

import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _log_cron_failure(error: str) -> None:
    try:
        db = get_supabase_client()
        db.table("eval_queue").insert({
            "ticket_id": None,
            "failure_category": "cron_failure:autoclose",
            "failure_freetext": error,
        }).execute()
    except Exception:
        pass


def run_autoclose_check() -> None:
    try:
        _run_autoclose_check_inner()
    except Exception as exc:
        logger.error("autoclose_cron failed: %s", exc)
        _log_cron_failure(str(exc))


def _run_autoclose_check_inner() -> None:
    db = get_supabase_client()
    # Auto-close tickets where resolution_deadline passed more than 48h ago
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    result = (
        db.table("tickets")
        .select("ticket_id, user_id, category, resolution_deadline")
        .lt("resolution_deadline", cutoff)
        .in_("status", ["open", "pending_confirmation"])
        .execute()
    )

    tickets = result.data or []
    logger.info("Auto-close check: %d ticket(s) eligible", len(tickets))

    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        db.table("tickets").update({
            "status": "auto_closed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("ticket_id", ticket_id).execute()
        logger.info(
            "Auto-closed ticket %s (category: %s)",
            ticket_id, ticket.get("category"),
        )
