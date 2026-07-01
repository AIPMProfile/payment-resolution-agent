"""
Execute the get_transaction tool call against Supabase.
Returns the transaction dict with a match_confidence field, or None if not found.
"""
from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone, timedelta
from app.db.supabase_client import get_supabase_client


def _thirty_days_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _match_confidence(txn: dict, amount_mentioned: Optional[float], merchant_mentioned: Optional[str]) -> str:
    if amount_mentioned is not None:
        delta = abs(txn["amount"] - amount_mentioned) / max(amount_mentioned, 1)
        if delta > 0.10:
            return "uncertain"
    if merchant_mentioned:
        m = merchant_mentioned.lower()
        t = txn["merchant"].lower()
        if m not in t and t not in m:
            return "uncertain"
    return "high"


async def get_transaction(
    user_id: str,
    category: str,
    amount_mentioned: Optional[float] = None,
    merchant_mentioned: Optional[str] = None,
    txn_id: Optional[str] = None,
) -> dict | None:
    db = get_supabase_client()

    # Direct lookup when user provided an explicit TXN ID.
    # user_id filter prevents a user from fetching another user's transaction.
    if txn_id:
        result = (
            db.table("transactions")
            .select("*")
            .eq("txn_id", txn_id.upper())
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None
        txn = result.data[0]
        txn["match_confidence"] = "high"
        return txn

    cutoff = _thirty_days_ago()

    if category == "UPI_FAILURE":
        result = (
            db.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .eq("type", "UPI")
            .eq("status", "FAILED")
            .gte("initiated_at", cutoff)
            .order("initiated_at", desc=True)
            .execute()
        )
    elif category == "POT_WITHDRAWAL":
        result = (
            db.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .eq("type", "POT_WITHDRAWAL")
            .eq("status", "PENDING")
            .gte("initiated_at", cutoff)
            .order("initiated_at", desc=True)
            .execute()
        )
    else:
        return None

    if not result.data:
        return None

    # If amount provided, prefer the closest match; otherwise use most recent
    txn = result.data[0]
    if amount_mentioned and len(result.data) > 1:
        txn = min(result.data, key=lambda t: abs(t["amount"] - amount_mentioned))

    txn["match_confidence"] = _match_confidence(txn, amount_mentioned, merchant_mentioned)
    return txn
