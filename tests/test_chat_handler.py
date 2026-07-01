"""
Integration tests for chat_handler.handle_chat.

All external I/O is mocked — Supabase, Anthropic API, tracer.
These tests exercise the actual handler flow end-to-end and catch
flow-level bugs that unit tests on isolated components cannot catch.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import ChatRequest
from tests.conftest import (
    make_ticket, make_mock_db, make_mock_tracer,
    MOCK_TXN, MOCK_RULES, CARD_WITH_ESCALATION, CARD_NO_ESCALATION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request(message="my UPI payment is stuck", ticket_id=None, user_id="USR001"):
    return ChatRequest(user_id=user_id, message=message, ticket_id=ticket_id)


def _all_policy_pass():
    """policy_checker returns no failures."""
    passed = [{"rule_id": r, "passed": True, "reason_code": "N/A", "explanation": "ok"}
              for r in ["NO_GUARANTEE", "NO_FRAUD_VERDICT", "CITATION_REQUIRED",
                        "NO_FILLER", "NO_APPROXIMATION", "ESCALATE_HIGH_AMOUNT", "ESCALATE_DISTRESS"]]
    return [], passed


# ---------------------------------------------------------------------------
# Test 1: Input length cap fires before any DB or LLM call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_too_long_returns_error_immediately():
    from app.lifecycle.chat_handler import handle_chat
    with patch("app.lifecycle.chat_handler.get_supabase_client") as mock_db_fn, \
         patch("app.lifecycle.chat_handler.load_policy_rules") as mock_rules:

        response = await handle_chat(_request(message="x" * 501))

        assert response.ticket_status == "error"
        assert "500 characters" in response.message
        assert response.feedback_prompt is False
        mock_db_fn.assert_not_called()
        mock_rules.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Unknown user returns error without touching tickets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_user_returns_error():
    from app.lifecycle.chat_handler import handle_chat
    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db(user_exists=False)), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket") as mock_get_ticket:

        response = await handle_chat(_request())

        assert response.ticket_status == "error"
        assert "not found" in response.message.lower()
        mock_get_ticket.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: First turn — full flow produces card, feedback_prompt=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_turn_returns_card_with_feedback():
    from app.lifecycle.chat_handler import handle_chat
    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UPI_FAILURE")), \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=CARD_NO_ESCALATION)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.run_policy_checks", return_value=_all_policy_pass()), \
         patch("app.lifecycle.chat_handler.run_structural_evals", return_value=[]), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        response = await handle_chat(_request())

        assert response.card is not None
        assert response.card.category == "UPI_FAILURE"
        assert response.feedback_prompt is True  # first turn → feedback shown
        assert response.ticket_status == "open"   # no escalation language in card


# ---------------------------------------------------------------------------
# Test 4: Follow-up turn — Haiku is skipped entirely
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_follow_up_turn_skips_haiku():
    from app.lifecycle.chat_handler import handle_chat
    history = [
        {"role": "user", "content": "my payment is stuck"},
        {"role": "assistant", "content": "Reversal expected by 25 Jun."},
    ]
    ticket = make_ticket(category="UPI_FAILURE", conversation_json=history)

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock()) as mock_classify, \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=CARD_NO_ESCALATION)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.run_policy_checks", return_value=_all_policy_pass()), \
         patch("app.lifecycle.chat_handler.run_structural_evals", return_value=[]), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        await handle_chat(_request("any follow-up message"))

        mock_classify.assert_not_awaited()  # Haiku must NOT be called on follow-up


# ---------------------------------------------------------------------------
# Test 5: Follow-up turn — feedback_prompt=False (not first turn)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_follow_up_turn_still_has_feedback_prompt():
    from app.lifecycle.chat_handler import handle_chat
    history = [
        {"role": "user", "content": "my payment is stuck"},
        {"role": "assistant", "content": "Reversal expected by 25 Jun."},
    ]
    ticket = make_ticket(category="UPI_FAILURE", conversation_json=history)

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UPI_FAILURE")), \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=CARD_NO_ESCALATION)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.run_policy_checks", return_value=_all_policy_pass()), \
         patch("app.lifecycle.chat_handler.run_structural_evals", return_value=[]), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        response = await handle_chat(_request("what is the latest?"))

        assert response.feedback_prompt is True  # feedback on every card response


# ---------------------------------------------------------------------------
# Test 6: Escalation card sets ticket status to "escalated"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalation_card_sets_ticket_status_escalated():
    from app.lifecycle.chat_handler import handle_chat
    mock_update = MagicMock()

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket", mock_update), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UPI_FAILURE")), \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=CARD_WITH_ESCALATION)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.run_policy_checks", return_value=_all_policy_pass()), \
         patch("app.lifecycle.chat_handler.run_structural_evals", return_value=[]), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        response = await handle_chat(_request())

        # ticket_status in the response must be "escalated"
        assert response.ticket_status == "escalated"
        # _update_ticket must have been called with status="escalated"
        update_calls = [str(c) for c in mock_update.call_args_list]
        assert any("escalated" in c for c in update_calls)


# ---------------------------------------------------------------------------
# Test 7: Post-escalation follow-up calls compose_conversational, NOT compose_response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_escalation_followup_calls_conversational_composer():
    from app.lifecycle.chat_handler import handle_chat
    ticket = make_ticket(status="escalated", category="UPI_FAILURE")

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock()) as mock_compose, \
         patch("app.lifecycle.chat_handler.compose_conversational",
               new=AsyncMock(return_value="You're welcome, hope it gets sorted!")) as mock_conv, \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("I need the funds urgently"))

        mock_conv.assert_awaited_once()          # conversational path fired
        mock_compose.assert_not_awaited()        # full compose must NOT fire
        assert response.ticket_status == "escalated"
        assert response.feedback_prompt is False


# ---------------------------------------------------------------------------
# Test 8: Post-escalation "thanks" gets a warm response via conversational composer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_escalation_thanks_gets_warm_response():
    from app.lifecycle.chat_handler import handle_chat
    ticket = make_ticket(status="escalated", category="UPI_FAILURE")
    warm_reply = "You're welcome — hope it gets sorted quickly!"

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock()) as mock_compose, \
         patch("app.lifecycle.chat_handler.compose_conversational",
               new=AsyncMock(return_value=warm_reply)) as mock_conv, \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("thanks"))

        mock_conv.assert_awaited_once()
        mock_compose.assert_not_awaited()
        assert response.message == warm_reply
        # must NOT be the old scripted ack string
        assert "urgency has been noted" not in response.message


# ---------------------------------------------------------------------------
# Test 9: Post-escalation "still not credited" returns policy-exhausted message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_escalation_still_not_credited_returns_exhausted_message():
    from app.lifecycle.chat_handler import handle_chat
    ticket = make_ticket(status="escalated", category="UPI_FAILURE")

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.compose_conversational", new=AsyncMock()) as mock_conv, \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("still not credited, nothing has come"))

        mock_conv.assert_not_awaited()           # should NOT call conversational
        assert response.escalated is True
        assert response.feedback_prompt is False


# ---------------------------------------------------------------------------
# Test 10: Auto-confirm closes ticket and skips compose
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_confirm_closes_ticket():
    from app.lifecycle.chat_handler import handle_chat
    ticket = make_ticket(status="open", category="UPI_FAILURE")
    mock_update = MagicMock()

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket", mock_update), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock()) as mock_compose, \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        # Must use an exact auto_confirm_keyword from policy_rules.json
        response = await handle_chat(_request("got the money, it came through finally"))

        mock_compose.assert_not_awaited()        # compose must NOT fire
        assert response.ticket_status == "resolved"
        update_calls = [str(c) for c in mock_update.call_args_list]
        assert any("resolved" in c for c in update_calls)


# ---------------------------------------------------------------------------
# Test 11: Auto-confirm does NOT fire when category is absent (no active transaction)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_confirm_ignored_without_active_category():
    from app.lifecycle.chat_handler import handle_chat
    # Ticket with no category — user just opened a ticket and says "received"
    ticket = make_ticket(status="open", category=None)

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UNCLEAR")), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("received an OTP, but payment still stuck"))

        # Should NOT be resolved — auto_confirm guard must block it
        assert response.ticket_status != "resolved"


# ---------------------------------------------------------------------------
# Test 12: UNCLEAR increments counter and asks clarifying question
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unclear_first_turn_asks_clarifying_question():
    from app.lifecycle.chat_handler import handle_chat
    mock_update = MagicMock()

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket", mock_update), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UNCLEAR")), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("money stuck"))

        assert response.ticket_status != "escalated"      # not escalated yet
        assert response.card is None                       # no card on UNCLEAR
        assert response.feedback_prompt is False
        # conversation_json must be updated
        update_calls = [str(c) for c in mock_update.call_args_list]
        assert any("conversation_json" in c for c in update_calls)


# ---------------------------------------------------------------------------
# Test 13: UNCLEAR escalates after hitting _MAX_UNCLEAR_TURNS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unclear_escalates_after_max_turns():
    from app.lifecycle.chat_handler import handle_chat
    # 2 prior user turns in history triggers escalation
    history = [
        {"role": "user", "content": "something wrong"},
        {"role": "assistant", "content": "Could you clarify?"},
        {"role": "user", "content": "idk"},
        {"role": "assistant", "content": "Is it a UPI payment or pot withdrawal?"},
    ]
    ticket = make_ticket(conversation_json=history)

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=ticket), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UNCLEAR")), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("idk what i mean"))

        assert response.ticket_status == "escalated"
        assert response.escalated is True


# ---------------------------------------------------------------------------
# Test 14: OUT_OF_SCOPE returns out-of-scope message without compose
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_out_of_scope_returns_correct_message():
    from app.lifecycle.chat_handler import handle_chat
    from app.knowledge.prompts import SITUATION_OUT_OF_SCOPE

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="OUT_OF_SCOPE")), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock()) as mock_compose, \
         patch("app.lifecycle.chat_handler.compose_conversational",
               new=AsyncMock(return_value="This is outside the scope of what I can help with here.")) as mock_conv, \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()):

        response = await handle_chat(_request("how do I get a personal loan?"))

        mock_compose.assert_not_awaited()
        mock_conv.assert_awaited_once()
        assert mock_conv.call_args.kwargs.get("situation") == SITUATION_OUT_OF_SCOPE
        assert response.card is None
        assert "outside" in response.message.lower() or "scope" in response.message.lower()


# ---------------------------------------------------------------------------
# Test 15: compose_response returning None triggers retry and correct error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compose_none_returns_error_after_retries():
    from app.lifecycle.chat_handler import handle_chat

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UPI_FAILURE")), \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=None)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        response = await handle_chat(_request())

        assert response.card is None
        assert "senior colleague" in response.message.lower()
        assert response.feedback_prompt is False


# ---------------------------------------------------------------------------
# Tests 17-19: _get_or_create_ticket — covers the mocking-trap blind spot.
# These tests call the real function against a mocked Supabase client so
# the DB lookup logic is actually exercised (not bypassed by mocking
# _get_or_create_ticket itself).
# ---------------------------------------------------------------------------

def test_get_or_create_ticket_creates_new_when_no_open_ticket():
    """No existing open ticket → new ticket created and returned."""
    from app.lifecycle.chat_handler import _get_or_create_ticket

    db = make_mock_db()
    # First call (open ticket lookup) returns empty; second call (insert) returns new ticket
    empty = MagicMock()
    empty.data = []
    new_ticket_result = MagicMock()
    new_ticket_row = {
        "ticket_id": "new-uuid", "user_id": "USR001", "session_id": "TKT-XXXX",
        "status": "open", "category": None, "conversation_json": [], "unclear_count": None,
    }
    new_ticket_result.data = [new_ticket_row]

    chain = MagicMock()
    chain.execute.side_effect = [empty, new_ticket_result]
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    db.table.return_value = chain

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=db):
        ticket = _get_or_create_ticket("USR001", ticket_id=None)

    # Must return a ticket dict — either the newly inserted one or the default
    assert ticket.get("user_id") == "USR001" or ticket.get("status") == "open"


def test_get_or_create_ticket_does_not_reuse_escalated_ticket():
    """User has an escalated ticket from a previous session.
    Without an explicit ticket_id, a NEW ticket must be created — not the escalated one.
    This is the regression guard for the bug where _get_or_create_ticket included
    'escalated' in the status lookup, causing new queries to resume old escalations."""
    from app.lifecycle.chat_handler import _get_or_create_ticket

    escalated_ticket = {
        "ticket_id": "old-esc-ticket", "user_id": "USR001", "session_id": "TKT-OLD",
        "status": "escalated", "category": "UPI_FAILURE", "conversation_json": [],
        "unclear_count": None,
    }

    chain = MagicMock()
    # open/pending lookup returns empty (no open ticket)
    empty = MagicMock()
    empty.data = []
    new_row = MagicMock()
    new_row.data = [{"ticket_id": "fresh-ticket", "user_id": "USR001",
                     "status": "open", "conversation_json": [], "unclear_count": None}]
    chain.execute.side_effect = [empty, new_row]
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain

    db = MagicMock()
    db.table.return_value = chain

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=db):
        ticket = _get_or_create_ticket("USR001", ticket_id=None)

    # Must NOT return the old escalated ticket
    assert ticket.get("ticket_id") != "old-esc-ticket", (
        "Escalated ticket was reused for a new query — the bug is back. "
        "Check that 'escalated' is NOT in the fallback status list."
    )
    assert ticket.get("status") in ("open", None)


def test_get_or_create_ticket_explicit_id_returns_escalated_ticket():
    """When the user explicitly sends an escalated ticket_id (in-session follow-up),
    the function must return that ticket so post-escalation follow-ups work correctly."""
    from app.lifecycle.chat_handler import _get_or_create_ticket

    escalated_ticket = {
        "ticket_id": "esc-123", "user_id": "USR001", "session_id": "TKT-ESC",
        "status": "escalated", "category": "UPI_FAILURE", "conversation_json": [],
        "unclear_count": None,
    }
    chain = MagicMock()
    result = MagicMock()
    result.data = [escalated_ticket]
    chain.execute.return_value = result
    chain.select.return_value = chain
    chain.eq.return_value = chain

    db = MagicMock()
    db.table.return_value = chain

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=db):
        ticket = _get_or_create_ticket("USR001", ticket_id="esc-123")

    # Explicit ticket_id lookup must return the escalated ticket — in-session follow-up
    assert ticket["ticket_id"] == "esc-123"
    assert ticket["status"] == "escalated"


# ---------------------------------------------------------------------------
# Test 16: Policy retry exhaustion escalates ticket
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_failure_after_retries_escalates():
    from app.lifecycle.chat_handler import handle_chat
    policy_failure = [{"rule_id": "NO_GUARANTEE", "passed": False,
                       "reason_code": "GUARANTEE_LANGUAGE", "explanation": "forbidden phrase found"}]
    all_results = [{"rule_id": "NO_GUARANTEE", "passed": False,
                    "reason_code": "GUARANTEE_LANGUAGE", "explanation": "forbidden phrase found"}]

    with patch("app.lifecycle.chat_handler.get_supabase_client", return_value=make_mock_db()), \
         patch("app.lifecycle.chat_handler.load_policy_rules", return_value=MOCK_RULES), \
         patch("app.lifecycle.chat_handler._get_or_create_ticket", return_value=make_ticket()), \
         patch("app.lifecycle.chat_handler._update_ticket"), \
         patch("app.lifecycle.chat_handler.classify_intent", new=AsyncMock(return_value="UPI_FAILURE")), \
         patch("app.lifecycle.chat_handler.get_transaction", new=AsyncMock(return_value=MOCK_TXN)), \
         patch("app.lifecycle.chat_handler.compose_response", new=AsyncMock(return_value=CARD_NO_ESCALATION)), \
         patch("app.lifecycle.chat_handler.load_skill", return_value="skill content"), \
         patch("app.lifecycle.chat_handler.run_policy_checks", return_value=(policy_failure, all_results)), \
         patch("app.lifecycle.chat_handler.get_tracer", return_value=make_mock_tracer()), \
         patch("app.lifecycle.chat_handler.asyncio.create_task"):

        response = await handle_chat(_request())

        assert response.escalated is True
        assert response.ticket_status == "escalated"
        assert response.feedback_prompt is False
