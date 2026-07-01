"""
Loop 3, Event A: orchestrates a full chat turn.
Classify → skill load → compose (with tool) → policy check → structural evals → respond.
"""
from __future__ import annotations
from typing import Optional

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone, timedelta

from app.config import get_settings
from app.db.models import ChatRequest, ChatResponse, ResponseCard
from app.db.supabase_client import get_supabase_client
from app.core.classifier import classify_intent
from app.core.composer import compose_response, compose_conversational
from app.knowledge.prompts import (
    SITUATION_POST_ESCALATION, SITUATION_UNCLEAR, SITUATION_UNCLEAR_ESCALATED,
    SITUATION_OUT_OF_SCOPE, SITUATION_NO_TRANSACTION,
)
from app.core.retriever import get_transaction
from app.knowledge.policy_loader import (
    load_policy_rules,
    load_skill,
    calculate_upi_t5_deadline,
    calculate_next_neft_batch,
)
from app.verification.policy_checker import run_policy_checks, run_policy_checks_text, format_violations
from app.verification.structural_evals import run_structural_evals
from opentelemetry.trace import StatusCode
from app.observability.arize_client import get_tracer, span_attrs

_POLICY_EXHAUSTED_MSG = (
    "I was not able to resolve this accurately. "
    "Connecting you to a specialist. "
    "Your ticket ID is {ticket_id}. Wait under 3 minutes."
)


def _new_ticket_id() -> str:
    return str(uuid.uuid4())


def _new_session_id() -> str:
    return "TKT-" + uuid.uuid4().hex[:8].upper()


def _contains_any(text: str, keywords: list[str]) -> bool:
    lt = text.lower()
    return any(k in lt for k in keywords)


def _get_or_create_ticket(user_id: str, ticket_id: Optional[str]) -> dict:
    db = get_supabase_client()

    if ticket_id:
        r = db.table("tickets").select("*").eq("ticket_id", ticket_id).execute()
        if r.data:
            return r.data[0]

    # No ticket_id means a new conversation — always create a fresh ticket.
    # Follow-ups pass the ticket_id from the previous response, so they
    # hit the explicit lookup above.
    now = datetime.now(timezone.utc).isoformat()
    new_ticket = {
        "ticket_id": _new_ticket_id(),
        "user_id": user_id,
        "session_id": _new_session_id(),
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "conversation_json": [],
    }
    db.table("tickets").insert(new_ticket).execute()
    return new_ticket


def _update_ticket(ticket_id: str, updates: dict) -> None:
    db = get_supabase_client()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("tickets").update(updates).eq("ticket_id", ticket_id).execute()


def _append_conversation(ticket: dict, role: str, content: str) -> list:
    history = ticket.get("conversation_json") or []
    history.append({"role": role, "content": content})
    return history[-20:]  # keep last 20 turns


def _calculate_deadline(category: str, txn: dict) -> Optional[str]:
    initiated_str = txn.get("initiated_at")
    if not initiated_str:
        return None

    initiated_at = datetime.fromisoformat(initiated_str)

    if category == "UPI_FAILURE":
        t5 = calculate_upi_t5_deadline(initiated_at)
        deadline = datetime.combine(t5, datetime.max.time(), tzinfo=timezone.utc)
        return deadline.isoformat()
    elif category == "POT_WITHDRAWAL":
        next_batch = calculate_next_neft_batch(initiated_at)
        return next_batch.isoformat()
    return None


async def _log_trace(ticket_id: str, card: dict, category: str,
                     layer1_results: list, struct_results: list,
                     tool_metadata: dict) -> None:
    try:
        db = get_supabase_client()
        response_text = card.get("response", "") + " " + card.get("next_step", "")
        db.table("eval_queue").insert({
            "ticket_id": ticket_id,
            "response_text": response_text.strip(),
            "classification": category,
            "policy_checks_json": {
                "layer1": layer1_results,
                "struct": struct_results,
                "tool_metadata": tool_metadata,
                "model_id": "claude-sonnet-4-6",
                "classifier_model_id": "claude-haiku-4-5-20251001",
            },
        }).execute()
    except Exception:
        pass  # observability must never break the agent


async def _log_conversational_trace(
    ticket_id: str, response_text: str, category: str, situation: str
) -> None:
    """Log non-card responses to eval_queue so nightly analysis can improve them."""
    try:
        db = get_supabase_client()
        db.table("eval_queue").insert({
            "ticket_id": ticket_id,
            "response_text": response_text,
            "classification": category,
            "policy_checks_json": {
                "response_type": "conversational",
                "situation": situation,
                "model_id": "claude-sonnet-4-6",
                "classifier_model_id": "claude-haiku-4-5-20251001",
            },
        }).execute()
    except Exception:
        pass


_MAX_MESSAGE_LEN = 500
_MAX_UNCLEAR_TURNS = 2


async def handle_chat(request: ChatRequest) -> ChatResponse:
    if len(request.message) > _MAX_MESSAGE_LEN:
        return ChatResponse(
            ticket_id=request.ticket_id or "NONE",
            ticket_status="error",
            message="Your message is too long. Please keep it under 500 characters.",
            feedback_prompt=False,
        )

    db = get_supabase_client()
    rules = load_policy_rules()

    # Verify user exists
    user_r = db.table("users").select("user_id").eq("user_id", request.user_id).execute()
    if not user_r.data:
        return ChatResponse(
            ticket_id="NONE",
            ticket_status="error",
            message="User not found.",
            feedback_prompt=False,
        )

    ticket = _get_or_create_ticket(request.user_id, request.ticket_id)
    ticket_id = ticket["ticket_id"]
    friendly_id = ticket.get("session_id", ticket_id)

    tracer = get_tracer()

    with tracer.start_as_current_span("chat_turn") as parent:
        parent.set_attribute("openinference.span.kind", "CHAIN")
        parent.set_attribute("input.value", request.message)
        parent.set_status(StatusCode.OK)
        for k, v in span_attrs(request.user_id, ticket_id).items():
            parent.set_attribute(k, v)

        # Auto-confirm: user says money arrived
        if (
            ticket.get("category") in ("UPI_FAILURE", "POT_WITHDRAWAL")
            and _contains_any(request.message, rules["auto_confirm_keywords"])
        ):
            _update_ticket(ticket_id, {"status": "resolved"})
            parent.set_attribute("output.value", "auto_confirmed")
            return ChatResponse(
                ticket_id=ticket_id,
                ticket_status="resolved",
                message="Glad it's sorted. Your ticket is now closed.",
                feedback_prompt=False,
            )

        # Escalated ticket follow-ups
        if ticket["status"] == "escalated":
            if _contains_any(request.message, rules["still_not_credited_keywords"]):
                parent.set_attribute("output.value", "escalated_still_waiting")
                return ChatResponse(
                    ticket_id=ticket_id,
                    ticket_status="escalated",
                    message=_POLICY_EXHAUSTED_MSG.format(ticket_id=friendly_id),
                    escalated=True,
                    feedback_prompt=False,
                )
            history = ticket.get("conversation_json") or []

            if ticket.get("category") == "POT_WITHDRAWAL":
                sla_window = "2 business hours (Mon–Fri, 9am–6pm IST). If raised outside business hours, by 11am IST on the next working day"
            else:
                sla_window = "4 business hours (Mon–Fri, 9am–6pm IST). If raised outside business hours, by 1pm IST on the next working day"

            situation = SITUATION_POST_ESCALATION.format(
                sla_window=sla_window,
            )
            fallback_msg = f"A senior colleague will reach out within {sla_window}. No action needed from your side."
            reply = await compose_conversational(
                request.message,
                situation=situation,
                conversation_history=history,
                fallback=fallback_msg,
            )
            text_failures, text_results = run_policy_checks_text(reply, request.message)
            if text_failures:
                reply = fallback_msg
            new_history = _append_conversation(ticket, "user", request.message)
            new_history = _append_conversation({"conversation_json": new_history}, "assistant", reply)
            _update_ticket(ticket_id, {"conversation_json": new_history})
            asyncio.create_task(_log_conversational_trace(
                ticket_id, reply, ticket.get("category", "UNKNOWN"), "post_escalation"
            ))
            parent.set_attribute("output.value", reply[:200])
            return ChatResponse(
                ticket_id=ticket_id,
                ticket_status="escalated",
                message=reply,
                escalated=False,
                feedback_prompt=False,
            )

        history = ticket.get("conversation_json") or []
        existing_category: Optional[str] = ticket.get("category")
        is_follow_up = bool(
            existing_category and existing_category not in ("OUT_OF_SCOPE", "UNCLEAR")
        )

        # --- Loop 1: Classify ---
        with tracer.start_as_current_span("classify") as cs:
            cs.set_attribute("openinference.span.kind", "CHAIN")
            cs.set_attribute("is_follow_up", is_follow_up)

            if is_follow_up:
                # Ticket has a known category — skip Haiku, answer in context
                category = existing_category
                cs.set_attribute("category", category)
                cs.set_attribute("output.value", category)
                cs.set_attribute("haiku_skipped", True)
            else:
                # New conversation — run Haiku to determine intent
                for k, v in span_attrs(request.user_id, ticket_id, model_id="claude-haiku-4-5-20251001").items():
                    cs.set_attribute(k, v)
                t0 = time.time()
                category = await classify_intent(request.message, conversation_history=history)
                cs.set_attribute("latency_ms", round((time.time() - t0) * 1000))
                cs.set_attribute("category", category)
                cs.set_attribute("output.value", category)
                cs.set_attribute("haiku_skipped", False)

        if category == "UNCLEAR":
            unclear_count = len([t for t in history if t.get("role") == "user"])
            if unclear_count >= _MAX_UNCLEAR_TURNS:
                reply = await compose_conversational(
                    request.message,
                    situation=SITUATION_UNCLEAR_ESCALATED,
                    conversation_history=history,
                    fallback="Let me connect you with a senior colleague who can help you directly.",
                )
                text_failures, text_results = run_policy_checks_text(reply, request.message)
                if text_failures:
                    reply = "Let me connect you with a senior colleague who can help you directly."
                _update_ticket(ticket_id, {"status": "escalated"})
                asyncio.create_task(_log_conversational_trace(
                    ticket_id, reply, "UNCLEAR", "unclear_escalated"
                ))
                return ChatResponse(
                    ticket_id=ticket_id,
                    ticket_status="escalated",
                    message=reply,
                    escalated=True,
                    feedback_prompt=False,
                )
            reply = await compose_conversational(
                request.message,
                situation=SITUATION_UNCLEAR,
                conversation_history=history,
                fallback="Could you tell me — was it a UPI payment or a Savings Pot withdrawal?",
            )
            text_failures, text_results = run_policy_checks_text(reply, request.message)
            if text_failures:
                reply = "Was this a UPI payment that didn't go through, or a Savings Pot withdrawal that hasn't arrived?"
            new_history = _append_conversation(ticket, "user", request.message)
            new_history = _append_conversation({"conversation_json": new_history}, "assistant", reply)
            _update_ticket(ticket_id, {"conversation_json": new_history})
            asyncio.create_task(_log_conversational_trace(
                ticket_id, reply, "UNCLEAR", "unclear_clarify"
            ))
            return ChatResponse(
                ticket_id=ticket_id,
                ticket_status=ticket["status"],
                message=reply,
                feedback_prompt=False,
            )

        if category == "OUT_OF_SCOPE":
            reply = await compose_conversational(
                request.message,
                situation=SITUATION_OUT_OF_SCOPE,
                conversation_history=history,
                fallback="This is outside what I can help with — I handle UPI failures and Pot withdrawals. For other queries, please reach out through the app's support.",
            )
            text_failures, text_results = run_policy_checks_text(reply, request.message)
            if text_failures:
                reply = "I handle UPI payment failures and Savings Pot withdrawals. For other queries, please reach out through the app's support."
            new_history = _append_conversation(ticket, "user", request.message)
            new_history = _append_conversation({"conversation_json": new_history}, "assistant", reply)
            _update_ticket(ticket_id, {"category": "OUT_OF_SCOPE", "conversation_json": new_history})
            asyncio.create_task(_log_conversational_trace(
                ticket_id, reply, "OUT_OF_SCOPE", "out_of_scope"
            ))
            return ChatResponse(
                ticket_id=ticket_id,
                ticket_status=ticket["status"],
                message=reply,
                feedback_prompt=True,
            )

        skill_content = load_skill(category)

        # --- Loop 1: Retrieve (Python-owned, deterministic) ---
        # Extract amount from user message for retrieval relevance eval
        amount_mentioned: Optional[float] = None
        amt_match = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", request.message)
        if not amt_match:
            amt_match = re.search(r"(?:rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", request.message, re.IGNORECASE)
        if not amt_match:
            amt_match = re.search(r"\b(\d[\d,]*(?:\.\d+)?)\b", request.message)
        if amt_match:
            try:
                amount_mentioned = float(amt_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # If user included a TXN ID (e.g. "TXN009 is stuck"), fetch it directly.
        explicit_txn_id: Optional[str] = None
        m = re.search(r"\bTXN\d+\b", request.message, re.IGNORECASE)
        if m:
            explicit_txn_id = m.group(0).upper()

        with tracer.start_as_current_span("get_transaction") as tool_span:
            tool_span.set_attribute("openinference.span.kind", "TOOL")
            tool_span.set_attribute("input.value", json.dumps({
                "user_id": request.user_id,
                "category": category,
                "txn_id": explicit_txn_id,
            }))
            retrieved_txn = await get_transaction(
                user_id=request.user_id,
                category=category,
                amount_mentioned=amount_mentioned,
                txn_id=explicit_txn_id,
            )
            if retrieved_txn is not None:
                tool_span.set_attribute("output.value", json.dumps(retrieved_txn, default=str))

        if retrieved_txn is None:
            reply = await compose_conversational(
                request.message,
                situation=SITUATION_NO_TRANSACTION,
                conversation_history=history,
                fallback="I couldn't find a matching transaction. Could you share the TXN ID from the app? It starts with TXN.",
            )
            text_failures, text_results = run_policy_checks_text(reply, request.message)
            if text_failures:
                reply = "I couldn't find a matching transaction. Could you share the TXN ID from the app? It starts with TXN."
            new_history = _append_conversation(ticket, "user", request.message)
            new_history = _append_conversation({"conversation_json": new_history}, "assistant", reply)
            _update_ticket(ticket_id, {"conversation_json": new_history})
            asyncio.create_task(_log_conversational_trace(
                ticket_id, reply, category, "no_transaction"
            ))
            return ChatResponse(
                ticket_id=ticket_id,
                ticket_status=ticket["status"],
                message=reply,
                feedback_prompt=True,
            )

        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)
        retrieved_txn["_today"] = now_ist.strftime("%d %b %Y")

        if retrieved_txn.get("initiated_at"):
            ist_dt = datetime.fromisoformat(retrieved_txn["initiated_at"]).astimezone(IST)
            retrieved_txn["initiated_at_ist"] = ist_dt.strftime("%d %b %Y, %I:%M %p IST")

        tool_metadata: dict = {
            "classify_fired": True,
            "retrieve_fired": True,
            "params_complete": True,
            "amount_mentioned": amount_mentioned,
            "retrieved_amount": retrieved_txn.get("amount"),
            "category_in_params": category,
        }

        # --- Loop 1: Compose ---
        card = None
        layer1_results: list = []
        layer1_failures: list = []

        for attempt in range(3):
            # --- Loop 1: Compose (Sonnet) ---
            span_name = "compose" if attempt == 0 else "retry_attempt"
            with tracer.start_as_current_span(span_name) as cs:
                cs.set_attribute("openinference.span.kind", "CHAIN")
                cs.set_attribute("input.value", request.message)
                for k, v in span_attrs(request.user_id, ticket_id,
                                       model_id="claude-sonnet-4-6", attempt=attempt).items():
                    cs.set_attribute(k, v)

                violations_text = format_violations(layer1_failures) if layer1_failures else None
                t0 = time.time()

                card = await compose_response(
                    user_id=request.user_id,
                    category=category,
                    skill_content=skill_content,
                    user_message=request.message,
                    retrieved_txn=retrieved_txn,
                    conversation_history=history if history else None,
                    violations_text=violations_text,
                )
                cs.set_attribute("latency_ms", round((time.time() - t0) * 1000))

            if card is None:
                if attempt < 2:
                    continue
                return ChatResponse(
                    ticket_id=ticket_id,
                    ticket_status=ticket["status"],
                    message=(
                        "I wasn't able to prepare a response right now. "
                        "A senior colleague has been flagged to follow up with you."
                    ),
                    feedback_prompt=False,
                )

            # --- Loop 2, Layer 1: Policy check (sibling span, not child of compose) ---
            layer1_failures, layer1_results = run_policy_checks(
                card=card,
                retrieved_transaction=retrieved_txn,
                user_message=request.message,
            )

            if not layer1_failures:
                break

            if attempt == 2:
                _update_ticket(ticket_id, {"status": "escalated"})
                asyncio.create_task(_log_trace(
                    ticket_id, {"response": "policy_retry_exhausted", "next_step": ""},
                    category, layer1_results, [], tool_metadata,
                ))
                return ChatResponse(
                    ticket_id=ticket_id,
                    ticket_status="escalated",
                    message=_POLICY_EXHAUSTED_MSG.format(ticket_id=friendly_id),
                    escalated=True,
                    feedback_prompt=False,
                )

        # --- Core loop stop condition: explicit quality bar ---
        core_stop = {
            "has_4_fields": all(k in card for k in ("category", "reference", "response", "next_step")),
            "category_matches": card.get("category") == category,
            "tool_sequence": tool_metadata.get("classify_fired") and tool_metadata.get("retrieve_fired"),
            "policy_passed": not layer1_failures,
        }
        core_passed = all(core_stop.values())
        parent.set_attribute("core_loop.stop_condition", json.dumps(core_stop))
        parent.set_attribute("core_loop.passed", core_passed)
        if not core_passed:
            logger.warning("Core loop quality bar not met: %s", core_stop)

        # --- Loop 2, Layer 2: Structural evals (score, don't block) ---
        with tracer.start_as_current_span("structural_evals") as se:
            se.set_attribute("openinference.span.kind", "EVALUATOR")
            struct_results = run_structural_evals(
                card=card,
                tool_metadata=tool_metadata,
                user_message=request.message,
                retrieved_transaction=retrieved_txn,
            )
            se.set_attribute("input.value", str(card))
            se.set_attribute("output.value", str(struct_results))
            se.set_attribute("evals.count", len(struct_results))
            se.set_attribute("evals.all_passed", all(r.get("passed") for r in struct_results))

        # Update ticket
        resolution_deadline = _calculate_deadline(category, retrieved_txn or {})
        new_history = _append_conversation(ticket, "user", request.message)
        new_history = _append_conversation(
            {"conversation_json": new_history}, "assistant",
            card.get("response", "") + " " + card.get("next_step", "")
        )

        # If Sonnet's card contains escalation language, mark the ticket escalated
        # so the next follow-up turn triggers _POST_ESCALATION_ACK instead of re-composing
        card_combined = (card.get("response", "") + " " + card.get("next_step", "")).lower()
        new_status = "escalated" if "senior colleague" in card_combined else ticket["status"]

        _update_ticket(ticket_id, {
            "category": category,
            "status": new_status,
            "resolution_deadline": resolution_deadline,
            "conversation_json": new_history,
        })

        # Log trace for nightly analysis
        asyncio.create_task(_log_trace(
            ticket_id, card, category, layer1_results, struct_results, tool_metadata,
        ))

        return ChatResponse(
            ticket_id=ticket_id,
            ticket_status=new_status,
            card=ResponseCard(**card),
            escalated=False,
            feedback_prompt=True,
        )
