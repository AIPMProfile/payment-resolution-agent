from __future__ import annotations

import anthropic
from app.config import get_settings
from app.knowledge.prompts import CLASSIFIER_SYSTEM_PROMPT

_HAIKU = "claude-haiku-4-5-20251001"
_VALID = {"UPI_FAILURE", "POT_WITHDRAWAL", "OUT_OF_SCOPE", "UNCLEAR"}


async def classify_intent(
    user_message: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Classify user message into exactly one category using Haiku.
    conversation_history is the prior turns so Haiku has context for follow-ups.
    Returns one of: UPI_FAILURE, POT_WITHDRAWAL, OUT_OF_SCOPE, UNCLEAR.
    """
    client = anthropic.AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)

    messages: list[dict] = []
    if conversation_history:
        for turn in conversation_history[-4:]:  # last 2 exchanges
            messages.append({
                "role": turn["role"],
                "content": str(turn["content"])[:400],
            })
    messages.append({"role": "user", "content": user_message})

    response = await client.messages.create(
        model=_HAIKU,
        max_tokens=20,
        system=CLASSIFIER_SYSTEM_PROMPT,
        messages=messages,
    )

    raw = response.content[0].text.strip().upper()

    if raw not in _VALID:
        return "OUT_OF_SCOPE"
    return raw
