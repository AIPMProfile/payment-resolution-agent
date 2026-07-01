"""
Regression test: guarantee language in response card.

POLICY HISTORY
──────────────
v1 (2026-06-25): Banned all assurance language including "will be refunded",
"will be credited", "will receive". This was overcorrective — it prevented
the agent from assuring users their money would return, which is the #1
complaint about the current Jupiter app support.

v2 (2026-06-29): Policy changed — regulation-backed assurance is now APPROVED.
NPCI rules mandate auto-reversal, so "your bank is required to credit/reverse"
and "will be credited to your account by [date]" are factual statements.
Banned phrases now limited to subjective assurances: "guaranteed", "definitely",
"probably", "likely", "should be", "your money is safe".

Regression test: this test must remain passing on every future change to
policy_rules.json or skills/UPI_FAILURE.md.
"""

from app.verification.policy_checker import run_policy_checks

_VALID_TXN = {"txn_id": "TXN001", "amount": 2340.0, "merchant": "Swiggy", "match_confidence": "high"}


def _run(response_text: str) -> bool:
    """Return True if NO_GUARANTEE passes (no guarantee language found)."""
    card = {
        "category": "UPI_FAILURE",
        "reference": "TXN001 | NPCI_RULE_UPI_T5",
        "response": response_text,
        "next_step": "Check your account on June 25.",
    }
    failures, results = run_policy_checks(
        card=card,
        retrieved_transaction=_VALID_TXN,
        user_message="my swiggy payment is stuck",
    )
    passed_map = {r["rule_id"]: r["passed"] for r in results}
    return passed_map["NO_GUARANTEE"]


# ── Subjective assurances — still banned ──

def test_guaranteed_fails():
    assert _run("The reversal is guaranteed to arrive by June 25.") is False

def test_definitely_fails():
    assert _run("You will definitely receive the money back.") is False

def test_probably_fails():
    assert _run("You will probably get the refund by June 25.") is False

def test_your_money_is_safe_fails():
    assert _run("Don't worry, your money is safe.") is False


# ── Regulation-backed assurance — now approved ──

def test_will_be_credited_with_date_passes():
    """Policy v2: regulation-backed assurance is approved."""
    assert _run("The amount will be credited to your account by June 25 as per NPCI UPI rules.") is True

def test_will_be_refunded_with_regulation_passes():
    """Policy v2: citing NPCI rules makes refund language factual, not a promise."""
    assert _run("Your ₹2340 will be refunded by June 25 under NPCI UPI rules.") is True

def test_bank_required_to_reverse_passes():
    assert _run("Your bank is required to reverse this by June 25 under NPCI UPI rules.") is True

def test_expected_to_reverse_passes():
    assert _run("TXN001 (₹2340 Swiggy) is expected to reverse by June 25 as per NPCI UPI rules.") is True

def test_escalation_response_passes():
    assert _run("TXN001 is past the T+5 deadline. Connecting you with a senior colleague.") is True
