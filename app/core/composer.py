from __future__ import annotations
from typing import Optional
"""
Loop 1 composer: Sonnet receives base system prompt + skill file + pre-fetched
transaction data + user message, and composes the structured response card in
a single call. Retrieval is Python-owned (chat_handler); Sonnet never calls tools.
"""

import json
import anthropic
from app.config import get_settings
from app.knowledge.prompts import (
    BASE_SYSTEM_PROMPT, RETRY_INJECTION_TEMPLATE,
    CONVERSATIONAL_SYSTEM_PROMPT, SITUATION_POST_ESCALATION,
)

_SONNET = "claude-sonnet-4-6"
_MAX_HISTORY_TURNS = 10


def _build_system(skill_content: str) -> str:
    return BASE_SYSTEM_PROMPT + "\n\n---\n\n" + skill_content


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)


async def compose_conversational(
    user_message: str,
    situation: str = SITUATION_POST_ESCALATION,
    conversation_history: list[dict] | None = None,
    fallback: str = "You're all set — the team will be in touch soon.",
) -> str:
    """
    Lightweight Sonnet call for any non-resolution turn.
    Situation context tells Sonnet WHY we're in conversational mode so it
    responds appropriately — clarification, scope explanation, no-txn guidance,
    post-escalation warmth, etc.
    """
    client = anthropic.AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)
    system = CONVERSATIONAL_SYSTEM_PROMPT.format(situation=situation)

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})

    response = await client.messages.create(
        model=_SONNET,
        max_tokens=150,
        system=system,
        messages=messages,
    )
    text_block = next((b for b in response.content if b.type == "text"), None)
    return text_block.text.strip() if text_block else fallback


async def compose_response(
    user_id: str,
    category: str,
    skill_content: str,
    user_message: str,
    retrieved_txn: dict,
    conversation_history: list[dict] | None = None,
    violations_text: Optional[str] = None,
) -> dict | None:
    """
    Returns a response card dict, or None on JSON parse failure.
    Transaction data is injected as context; Sonnet makes one call.
    """
    client = anthropic.AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)
    system = _build_system(skill_content)

    txn_context = f"Retrieved transaction data:\n{json.dumps(retrieved_txn, default=str)}"

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-_MAX_HISTORY_TURNS:])

    if violations_text:
        user_content = (
            RETRY_INJECTION_TEMPLATE.format(violations=violations_text)
            + f"\n\n{txn_context}"
            + "\n\nOriginal user message: "
            + user_message
        )
    else:
        user_content = f"{txn_context}\n\nUser message: {user_message}"

    messages.append({"role": "user", "content": user_content})

    msg_chars = sum(len(m.get("content", "")) for m in messages)
    sys_chars = sum(len(s.get("text", s) if isinstance(s, dict) else s) for s in (system if isinstance(system, list) else [system]))
    print(f"compose input: {len(messages)} messages, {msg_chars} chars, {sys_chars} system chars")

    response = await client.messages.create(
        model=_SONNET,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        return None

    try:
        return _extract_json(text_block.text)
    except (json.JSONDecodeError, ValueError):
        print(f"compose JSON parse failed, raw response: {text_block.text[:300]}")
        return None
