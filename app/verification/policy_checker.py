from __future__ import annotations
from typing import Optional
"""
Loop 2, Layer 1: deterministic policy checks that block responses before delivery.
Every rule traces to a documented failure mode (see inline comments).
No LLM calls. Returns list of failed checks; empty list = all passed.
"""

import re
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from app.knowledge.policy_loader import load_policy_rules

VALID_CATEGORIES = {"UPI_FAILURE", "POT_WITHDRAWAL", "OUT_OF_SCOPE"}


def _lower(text: str) -> str:
    return text.lower()


def _has_phrase(text: str, phrases: list[str]) -> Optional[str]:
    lt = _lower(text)
    for phrase in phrases:
        if phrase in lt:
            return phrase
    return None


def _response_has_escalation(card: dict) -> bool:
    combined = _lower(card.get("response", "") + " " + card.get("next_step", ""))
    return "senior colleague" in combined


def run_policy_checks(
    card: dict,
    retrieved_transaction: dict | None,
    user_message: str,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (failures, all_results).
    Each result: {rule_id, passed, reason_code, explanation}.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "policy_check",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("openinference.span.kind", "GUARDRAIL")
        return _run_checks(card, retrieved_transaction, user_message, span)


def _run_checks(
    card: dict,
    retrieved_transaction: dict | None,
    user_message: str,
    span,
) -> tuple[list[dict], list[dict]]:
    response = card.get("response", "")
    rules = load_policy_rules()
    combined = (response + " " + card.get("next_step", "")).strip()
    results = []

    # --- NO_GUARANTEE ---
    # Failure: early Sonnet drafts said "your money will be refunded within 5 days"
    # Rule: ESCALATION_RULE_GUARANTEE
    forbidden = rules["forbidden_phrases"]
    hit = _has_phrase(combined, forbidden)
    results.append({
        "rule_id": "NO_GUARANTEE",
        "passed": hit is None,
        "reason_code": "GUARANTEE_LANGUAGE",
        "explanation": f'Forbidden phrase: "{hit}"' if hit else "ok",
    })

    # --- NO_FRAUD_VERDICT ---
    # Failure: agent labelled a disputed transaction as "fraud" before investigation
    # Rule: FRAUD_VERDICT_BLOCKED
    fraud_patterns = ["this is fraud", "fraudulent transaction", "you've been defrauded", "is a fraud"]
    hit = _has_phrase(combined, fraud_patterns)
    results.append({
        "rule_id": "NO_FRAUD_VERDICT",
        "passed": hit is None,
        "reason_code": "FRAUD_VERDICT",
        "explanation": f'Fraud verdict found: "{hit}"' if hit else "ok",
    })

    # --- CITATION_REQUIRED ---
    # Failure: responses citing "NPCI rules" without naming the rule ID were challenged
    # Rule: CITATION_REQUIRED
    ref = card.get("reference", "")
    has_txn = bool(re.search(r"\bTXN\d+\b", ref))
    has_rule = bool(re.search(r"\b[A-Z_]{4,}\b", ref))
    citation_ok = has_txn or has_rule
    results.append({
        "rule_id": "CITATION_REQUIRED",
        "passed": citation_ok,
        "reason_code": "MISSING_CITATION",
        "explanation": "No TXN ID or rule ID in reference" if not citation_ok else "ok",
    })

    # --- NO_FILLER ---
    # Failure: responses opening with "Great question!" eroded trust in a support context
    # Rule: FILLER_OPENER_BLOCKED
    filler_openers = rules["filler_openers"]
    response_start = _lower(card.get("response", "")[:80])
    filler_hit = _has_phrase(response_start, filler_openers)
    results.append({
        "rule_id": "NO_FILLER",
        "passed": filler_hit is None,
        "reason_code": "FILLER_OPENER",
        "explanation": f'Filler opener: "{filler_hit}"' if filler_hit else "ok",
    })

    # --- NO_APPROXIMATION ---
    # Failure: "you should probably receive it soon" gave no actionable information
    # Rule: APPROXIMATION_LANGUAGE_BLOCKED
    approx = ["probably", "likely", "should be", "might be", "may be"]
    hit = _has_phrase(combined, approx)
    results.append({
        "rule_id": "NO_APPROXIMATION",
        "passed": hit is None,
        "reason_code": "APPROXIMATION_LANGUAGE",
        "explanation": f'Approximation language: "{hit}"' if hit else "ok",
    })

    # --- ESCALATE_HIGH_AMOUNT ---
    # Failure: agent gave "wait T+5" response on a ₹87,500 disputed transaction
    # Rule: ESCALATION_RULE_AMOUNT
    amount = retrieved_transaction.get("amount", 0) if retrieved_transaction else 0
    threshold = rules["rules"]["ESCALATION_RULE_AMOUNT"]["threshold_inr"]
    if amount > threshold:
        has_escalation = _response_has_escalation(card)
        results.append({
            "rule_id": "ESCALATE_HIGH_AMOUNT",
            "passed": has_escalation,
            "reason_code": "MISSING_ESCALATION",
            "explanation": f"Amount ₹{amount} > ₹{threshold}, no escalation" if not has_escalation else "ok",
        })
    else:
        results.append({
            "rule_id": "ESCALATE_HIGH_AMOUNT",
            "passed": True,
            "reason_code": "N/A",
            "explanation": "Below threshold",
        })

    # --- ESCALATE_DISTRESS ---
    # Failure: user said "urgent, need this for rent today" and got a wait-5-days response
    # Rule: ESCALATION_RULE_DISTRESS
    distress_keywords = rules["rules"]["ESCALATION_RULE_DISTRESS"]["keywords"]
    distress_hit = _has_phrase(_lower(user_message), distress_keywords)
    if distress_hit:
        has_escalation = _response_has_escalation(card)
        results.append({
            "rule_id": "ESCALATE_DISTRESS",
            "passed": has_escalation,
            "reason_code": "MISSING_ESCALATION",
            "explanation": f'Distress keyword "{distress_hit}", no escalation path' if not has_escalation else "ok",
        })
    else:
        results.append({
            "rule_id": "ESCALATE_DISTRESS",
            "passed": True,
            "reason_code": "N/A",
            "explanation": "No distress keyword",
        })

    failures = [r for r in results if not r["passed"]]
    span.set_attribute("input.value", str(card))
    span.set_attribute("output.value", str(results))
    span.set_attribute("policy.rules_checked", len(results))
    span.set_attribute("policy.failures", len(failures))
    span.set_attribute("policy.passed", len(failures) == 0)
    span.set_attribute("policy.failed_rules", ",".join(f["rule_id"] for f in failures))
    return failures, results


def run_policy_checks_text(
    response_text: str,
    user_message: str,
) -> tuple[list[dict], list[dict]]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "policy_check_conversational",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("openinference.span.kind", "GUARDRAIL")

        rules = load_policy_rules()
        combined = response_text.strip()
        results = []

        # NO_GUARANTEE
        # Failure: conversational response said "will definitely be refunded"
        # Rule: ESCALATION_RULE_GUARANTEE
        forbidden = rules["forbidden_phrases"]
        hit = _has_phrase(combined, forbidden)
        results.append({
            "rule_id": "NO_GUARANTEE",
            "passed": hit is None,
            "reason_code": "GUARANTEE_LANGUAGE",
            "explanation": f'Forbidden phrase: "{hit}"' if hit else "ok",
        })

        # NO_FRAUD_VERDICT
        # Failure: escalated follow-up said "looks like a technical failure, not fraud"
        # Rule: FRAUD_VERDICT_BLOCKED
        fraud_patterns = [
            "this is fraud", "fraudulent transaction",
            "you've been defrauded", "is a fraud",
            "not fraud", "looks like a technical failure",
            "not a scam", "looks legitimate",
        ]
        hit = _has_phrase(combined, fraud_patterns)
        results.append({
            "rule_id": "NO_FRAUD_VERDICT",
            "passed": hit is None,
            "reason_code": "FRAUD_VERDICT",
            "explanation": f'Fraud verdict: "{hit}"' if hit else "ok",
        })

        # NO_FILLER
        # Failure: conversational response opened with "Great question!"
        # Rule: FILLER_OPENER_BLOCKED
        filler_openers = rules["filler_openers"]
        response_start = _lower(combined[:80])
        filler_hit = _has_phrase(response_start, filler_openers)
        results.append({
            "rule_id": "NO_FILLER",
            "passed": filler_hit is None,
            "reason_code": "FILLER_OPENER",
            "explanation": f'Filler opener: "{filler_hit}"' if filler_hit else "ok",
        })

        # NO_APPROXIMATION
        # Failure: conversational response said "should probably"
        # Rule: APPROXIMATION_LANGUAGE_BLOCKED
        approx = ["probably", "likely", "should be", "might be", "may be"]
        hit = _has_phrase(combined, approx)
        results.append({
            "rule_id": "NO_APPROXIMATION",
            "passed": hit is None,
            "reason_code": "APPROXIMATION_LANGUAGE",
            "explanation": f'Approximation language: "{hit}"' if hit else "ok",
        })

        # NO_NON_GROUNDED_EMPATHY
        # Failure: agent said "I'd be lying" and "I completely understand"
        # Rule: NON_GROUNDED_EMPATHY_BLOCKED
        non_grounded = [
            "i'd be lying", "i wish i could",
            "i completely understand", "that sounds really stressful",
            "that's stressful", "that must be stressful",
            "i know how you feel", "i want to help you",
        ]
        hit = _has_phrase(combined, non_grounded)
        results.append({
            "rule_id": "NO_NON_GROUNDED_EMPATHY",
            "passed": hit is None,
            "reason_code": "NON_GROUNDED_EMPATHY",
            "explanation": f'Non-grounded empathy: "{hit}"' if hit else "ok",
        })

        failures = [r for r in results if not r["passed"]]
        span.set_attribute("input.value", response_text[:500])
        span.set_attribute("output.value", str(results))
        span.set_attribute("policy.rules_checked", len(results))
        span.set_attribute("policy.passed", len(failures) == 0)
        span.set_attribute("policy.failures", len(failures))
        span.set_attribute("policy.failed_rules", ",".join(f["rule_id"] for f in failures))
        return failures, results


def format_violations(failures: list[dict]) -> str:
    lines = []
    for f in failures:
        lines.append(f"- [{f['rule_id']}] {f['reason_code']}: {f['explanation']}")
    return "\n".join(lines)
