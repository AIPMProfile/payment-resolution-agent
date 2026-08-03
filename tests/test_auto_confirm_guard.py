"""
Auto-confirm must never close a ticket on a denial or a question.

Failure: auto_confirm_keywords contained the bare word "resolved" and the
fragment "received it", and _contains_any does plain substring matching. So
"is this resolved yet?" and "I haven't received it" both closed the user's
ticket while their money was still missing — the exact opposite of intent.

The guard errs toward NOT closing: a ticket held open one cycle longer is
recoverable, a ticket wrongly closed on an out-of-pocket user is not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.lifecycle.chat_handler import _blocks_auto_confirm, _contains_any

_RULES = json.loads(
    (Path(__file__).parents[1] / "app" / "knowledge" / "policy_rules.json").read_text()
)
_KEYWORDS = _RULES["auto_confirm_keywords"]


def _would_close(message: str) -> bool:
    """Mirror the auto-confirm condition in handle_chat."""
    return _contains_any(message, _KEYWORDS) and not _blocks_auto_confirm(message)


# Real phrasings from a user whose money has NOT arrived.
@pytest.mark.parametrize("message", [
    "is this resolved yet?",
    "has this been resolved?",
    "this is not resolved",
    "why is this still not resolved",
    "when will it be resolved",
    "I still have not received it",
    "I haven't received it",
    "not received it yet",
    "still waiting for the money",
    "how long until the money arrived in my account",
])
def test_denial_or_question_never_closes_ticket(message):
    assert not _would_close(message), (
        f"{message!r} would auto-close the ticket — user is still out of pocket"
    )


# Genuine confirmations must still resolve, or the feature is dead.
@pytest.mark.parametrize("message", [
    "got the money, thanks",
    "yes credited",
    "money arrived",
    "money is back",
    "refund received",
    "it came through",
    "it's resolved now",
    "i received it",
])
def test_genuine_confirmation_still_closes_ticket(message):
    assert _would_close(message), f"{message!r} should auto-close but did not"


def test_no_bare_single_word_keywords():
    """
    Single words match inside unrelated sentences. The keyword list is a
    phrase list by design — "resolved" alone is what caused this bug.
    """
    singles = [k for k in _KEYWORDS if " " not in k.strip()]
    assert not singles, (
        f"auto_confirm_keywords must contain phrases, not bare words: {singles}"
    )
