from __future__ import annotations
from typing import Optional
"""
Loop 4, Part A: user feedback collection.
Writes feedback to eval_queue in Supabase.
Tone classified by keyword matching, not LLM.
"""

import logging
from app.db.models import FeedbackRequest, FeedbackResponse
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_EMOTIONAL_KEYWORDS = [
    "robot", "talking to a robot", "not human", "automated", "useless",
    "frustrated", "angry", "worst", "terrible",
]

_FAILURE_TYPE_MAP = {
    "Too generic, not specific to my case": "retrieval_failure",
    "Confusing, hard to understand": "communication_clarity",
    "Wrong information": "policy_calibration",
    "Did not tell me what to do next": "communication_clarity",
}


def _classify_emotional_mismatch(free_text: Optional[str]) -> bool:
    if not free_text:
        return False
    lt = free_text.lower()
    return any(k in lt for k in _EMOTIONAL_KEYWORDS)


async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    db = get_supabase_client()

    failure_category = None
    if req.failure_reason == "Other" and _classify_emotional_mismatch(req.free_text):
        failure_category = "emotional_mismatch"
    elif req.failure_reason:
        failure_category = _FAILURE_TYPE_MAP.get(req.failure_reason, "communication_clarity")

    try:
        # Update the existing eval_queue row for this ticket, or insert a new feedback row
        existing = (
            db.table("eval_queue")
            .select("eval_id")
            .eq("ticket_id", req.ticket_id)
            .not_.is_("response_text", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if existing.data:
            db.table("eval_queue").update({
                "helpful_score": req.helpful_score,
                "failure_category": failure_category,
                "failure_freetext": req.free_text,
            }).eq("eval_id", existing.data[0]["eval_id"]).execute()
        else:
            db.table("eval_queue").insert({
                "ticket_id": req.ticket_id,
                "helpful_score": req.helpful_score,
                "failure_category": failure_category,
                "failure_freetext": req.free_text,
            }).execute()

        return FeedbackResponse(success=True)
    except Exception as exc:
        logger.error("Feedback write failed: %s", exc)
        return FeedbackResponse(success=False)
