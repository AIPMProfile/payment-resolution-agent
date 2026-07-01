"""Shared fixtures for chat_handler integration tests."""
from __future__ import annotations
from unittest.mock import MagicMock


def make_ticket(
    ticket_id="tkt-001",
    status="open",
    category=None,
    conversation_json=None,
    unclear_count=None,
):
    return {
        "ticket_id": ticket_id,
        "user_id": "USR001",
        "session_id": "TKT-ABCD1234",
        "status": status,
        "category": category,
        "conversation_json": conversation_json or [],
        "unclear_count": unclear_count,
    }


def make_mock_db(user_exists=True):
    """
    Returns a Supabase mock whose full chain (select/eq/in_/order/limit/insert/update/gte)
    always terminates at .execute() returning a result with .data configured for the
    users table. All other tables return empty data by default.
    """
    db = MagicMock()
    user_result = MagicMock()
    user_result.data = [{"user_id": "USR001"}] if user_exists else []

    chain = MagicMock()
    chain.execute.return_value = user_result
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.gte.return_value = chain
    db.table.return_value = chain
    return db


def make_mock_tracer():
    tracer = MagicMock()
    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)
    tracer.start_as_current_span.return_value = span
    return tracer


MOCK_TXN = {
    "txn_id": "TXN001",
    "user_id": "USR001",
    "merchant": "Swiggy",
    "amount": 2340.00,
    "type": "UPI",
    "status": "FAILED",
    "initiated_at": "2026-06-18T10:23:00+05:30",
    "settled_at": None,
    "match_confidence": "high",
}

MOCK_RULES = {
    # Mirror real policy_rules.json — specific phrases only, never single words
    "auto_confirm_keywords": [
        "yes credited", "got the money", "resolved", "thank you it worked",
        "money arrived", "received it", "it came through", "money is back", "refund received",
    ],
    "still_not_credited_keywords": [
        "still not credited", "still not received", "still pending",
        "money still not there", "still waiting", "not yet credited", "not arrived yet",
    ],
    "forbidden_phrases": ["will be refunded", "guaranteed", "definitely"],
    "filler_openers": ["great question", "certainly", "happy to help"],
    "rules": {
        "ESCALATION_RULE_AMOUNT": {"threshold_inr": 50000},
        "ESCALATION_RULE_DISTRESS": {"keywords": ["urgent", "rent", "emergency", "hospital"]},
    },
}

CARD_WITH_ESCALATION = {
    "category": "UPI_FAILURE",
    "reference": "TXN001 | NPCI_RULE_UPI_T5",
    "response": (
        "₹2,340 debited to Swiggy on 18 Jun. The T+5 deadline has passed. "
        "A senior colleague has been notified and your case details have been shared."
    ),
    "next_step": "A senior colleague will reach out within 4 business hours on your registered contact.",
}

CARD_NO_ESCALATION = {
    "category": "UPI_FAILURE",
    "reference": "TXN001 | NPCI_RULE_UPI_T5",
    "response": "₹2,340 debited to Swiggy on 18 Jun. Reversal expected by 25 Jun 2026 per NPCI_RULE_UPI_T5.",
    "next_step": "Reversal expected by 25 Jun 2026. No action needed from you.",
}
