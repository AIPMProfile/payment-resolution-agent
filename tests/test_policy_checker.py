"""Unit tests for all 7 Layer 1 policy rules."""

import pytest
from app.verification.policy_checker import run_policy_checks

_TXN_2340 = {"txn_id": "TXN001", "amount": 2340.00, "merchant": "Swiggy", "match_confidence": "high"}
_TXN_90K = {"txn_id": "TXN005", "amount": 90000.00, "merchant": "HDFC", "match_confidence": "high"}


def _check(card, txn=_TXN_2340, user_msg="my swiggy payment is stuck"):
    failures, results = run_policy_checks(card=card, retrieved_transaction=txn, user_message=user_msg)
    return failures, {r["rule_id"]: r["passed"] for r in results}


# ── NO_GUARANTEE ──

def test_guarantee_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "Your reversal is guaranteed to arrive within 5 days.", "next_step": "Wait."}
    failures, passed = _check(card)
    assert any(f["rule_id"] == "NO_GUARANTEE" for f in failures)


def test_no_guarantee_passes():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "TXN001 is expected to reverse by June 25 per NPCI_RULE_UPI_T5.",
            "next_step": "Check your account on June 25."}
    failures, passed = _check(card)
    assert passed["NO_GUARANTEE"] is True


# ── NO_FRAUD_VERDICT ──

def test_fraud_verdict_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN001",
            "response": "This is fraud and you should report it.", "next_step": "Call bank."}
    failures, _ = _check(card)
    assert any(f["rule_id"] == "NO_FRAUD_VERDICT" for f in failures)


def test_flagged_for_review_ok():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "TXN001 has been flagged for review.", "next_step": "Wait 24h."}
    failures, passed = _check(card)
    assert passed["NO_FRAUD_VERDICT"] is True


# ── CITATION_REQUIRED ──

def test_missing_citation_blocked():
    card = {"category": "UPI_FAILURE", "reference": "",
            "response": "Your UPI payment failed.", "next_step": "Wait 5 days."}
    failures, _ = _check(card)
    assert any(f["rule_id"] == "CITATION_REQUIRED" for f in failures)


def test_citation_txn_id_passes():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "TXN001 reversal expected by June 25.", "next_step": "Check June 25."}
    failures, passed = _check(card)
    assert passed["CITATION_REQUIRED"] is True


# ── NO_FILLER ──

def test_filler_opener_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "Great question! TXN001 should reverse soon.", "next_step": "Wait."}
    failures, _ = _check(card)
    assert any(f["rule_id"] == "NO_FILLER" for f in failures)


def test_no_filler_passes():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "TXN001 (₹2340 Swiggy) is expected to reverse by June 25 per NPCI_RULE_UPI_T5.",
            "next_step": "Check your account on June 25."}
    failures, passed = _check(card)
    assert passed["NO_FILLER"] is True


# ── NO_APPROXIMATION ──

def test_approximation_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN001",
            "response": "The money should be back soon probably.", "next_step": "Likely by end of week."}
    failures, _ = _check(card)
    assert any(f["rule_id"] == "NO_APPROXIMATION" for f in failures)


# ── ESCALATE_HIGH_AMOUNT ──

def test_high_amount_no_escalation_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN005 | NPCI_RULE_UPI_T5",
            "response": "TXN005 reversal expected by June 25.", "next_step": "Check account."}
    failures, _ = _check(card, txn=_TXN_90K)
    assert any(f["rule_id"] == "ESCALATE_HIGH_AMOUNT" for f in failures)


def test_high_amount_with_escalation_passes():
    card = {"category": "UPI_FAILURE", "reference": "TXN005 | ESCALATION_RULE_AMOUNT",
            "response": "TXN005 (₹90000) requires review. Connecting you with a senior colleague.",
            "next_step": "A senior colleague will contact you within 3 minutes."}
    failures, passed = _check(card, txn=_TXN_90K)
    assert passed["ESCALATE_HIGH_AMOUNT"] is True


# ── ESCALATE_DISTRESS ──

def test_distress_keyword_no_escalation_blocked():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | NPCI_RULE_UPI_T5",
            "response": "TXN001 reversal expected by June 25.",
            "next_step": "Wait until June 25."}
    failures, _ = _check(card, user_msg="my rent payment is stuck, this is urgent")
    assert any(f["rule_id"] == "ESCALATE_DISTRESS" for f in failures)


def test_distress_with_escalation_passes():
    card = {"category": "UPI_FAILURE", "reference": "TXN001 | ESCALATION_RULE_DISTRESS",
            "response": "TXN001 reversal is expected by June 25. Given the urgency, I am connecting you with a senior colleague.",
            "next_step": "A senior colleague will assist you within 3 minutes."}
    failures, passed = _check(card, user_msg="urgent, I need this for rent today")
    assert passed["ESCALATE_DISTRESS"] is True
