from __future__ import annotations
"""
Loop 2, Layer 2: structural evaluations that score but do not block.
Results are written to Arize as annotations and stored in eval_queue.
No LLM calls. Returns list of eval result dicts.
"""

import re

VALID_CATEGORIES = {"UPI_FAILURE", "POT_WITHDRAWAL", "OUT_OF_SCOPE"}
VAGUE_NEXT_STEPS = {
    "contact us", "check later", "try again", "visit app",
}
# "reach out" and "wait" are only vague without a timeframe — handled below


def _has_citation(text: str) -> bool:
    return bool(re.search(r"\bTXN\d+\b", text)) or bool(re.search(r"\b[A-Z_]{6,}\b", text))


def run_structural_evals(
    card: dict,
    tool_metadata: dict,
    user_message: str,
    retrieved_transaction: dict | None,
) -> list[dict]:
    """
    Returns list of eval results:
    {eval_id, passed, score (0 or 1), reason}
    """
    print("structural_evals running")
    results = []

    # SCHEMA_COMPLETE — all four card fields present and non-empty
    required = ["category", "reference", "response", "next_step"]
    missing = [f for f in required if not card.get(f, "").strip()]
    results.append({
        "eval_id": "SCHEMA_COMPLETE",
        "passed": len(missing) == 0,
        "score": 0 if missing else 1,
        "reason": f"Missing fields: {missing}" if missing else "ok",
    })

    # CATEGORY_EXACT — category is one of the valid strings
    cat = card.get("category", "")
    results.append({
        "eval_id": "CATEGORY_EXACT",
        "passed": cat in VALID_CATEGORIES,
        "score": 1 if cat in VALID_CATEGORIES else 0,
        "reason": f"Invalid category: {cat!r}" if cat not in VALID_CATEGORIES else "ok",
    })

    # CITATION_FORMAT — TXN ID or rule ID present in reference
    ref = card.get("reference", "")
    has_cit = _has_citation(ref)
    results.append({
        "eval_id": "CITATION_FORMAT",
        "passed": has_cit,
        "score": 1 if has_cit else 0,
        "reason": "No citation in reference field" if not has_cit else "ok",
    })

    # NEXT_STEP_SPECIFIC — next_step not empty or vague
    ns = card.get("next_step", "").strip().lower()
    is_vague = not ns or any(v in ns for v in VAGUE_NEXT_STEPS)
    if not is_vague and len(ns) < 40:
        # Short next_steps with only "wait" or "reach out" and no timeframe are vague
        has_timeframe = bool(re.search(r"\d+\s*(hour|minute|day|business|min|hr)", ns))
        if ("wait" in ns or "reach out" in ns) and not has_timeframe:
            is_vague = True
    results.append({
        "eval_id": "NEXT_STEP_SPECIFIC",
        "passed": not is_vague,
        "score": 0 if is_vague else 1,
        "reason": "Next step is vague or empty" if is_vague else "ok",
    })

    # TOOL_SEQUENCE — classify fired before retrieve, both fired, params include user_id
    classify_ok = tool_metadata.get("classify_fired", False)
    retrieve_ok = tool_metadata.get("retrieve_fired", False)
    params_ok = tool_metadata.get("params_complete", False)
    seq_ok = classify_ok and retrieve_ok and params_ok
    results.append({
        "eval_id": "TOOL_SEQUENCE",
        "passed": seq_ok,
        "score": 1 if seq_ok else 0,
        "reason": (
            "classify_fired=False" if not classify_ok else
            "retrieve not fired" if not retrieve_ok else
            "params incomplete" if not params_ok else "ok"
        ),
    })

    # RETRIEVAL_RELEVANCE — retrieved amount within 10% of amount user mentioned
    amount_mentioned = tool_metadata.get("amount_mentioned")
    retrieved_amount = tool_metadata.get("retrieved_amount")
    if amount_mentioned and retrieved_amount:
        delta = abs(retrieved_amount - amount_mentioned) / max(amount_mentioned, 1)
        rel_ok = delta <= 0.10
        results.append({
            "eval_id": "RETRIEVAL_RELEVANCE",
            "passed": rel_ok,
            "score": 1 if rel_ok else 0,
            "reason": f"Amount delta {delta:.1%} > 10%" if not rel_ok else "ok",
        })
    else:
        results.append({
            "eval_id": "RETRIEVAL_RELEVANCE",
            "passed": True,
            "score": 1,
            "reason": "No amount to compare",
        })

    # LENGTH_LIMIT — response + next_step combined under 500 chars
    combined_len = len(card.get("response", "")) + len(card.get("next_step", ""))
    results.append({
        "eval_id": "LENGTH_LIMIT",
        "passed": combined_len < 500,
        "score": 1 if combined_len < 500 else 0,
        "reason": f"Combined length {combined_len} >= 500" if combined_len >= 500 else "ok",
    })

    # TXN_ID_GROUNDED — if response mentions a TXN ID, it must match the retrieved transaction
    if retrieved_transaction:
        retrieved_txn_id = retrieved_transaction.get("txn_id") or retrieved_transaction.get("transaction_id", "")
        response_text = card.get("response", "") + " " + card.get("reference", "")
        mentioned_ids = re.findall(r"\bTXN\d+\b", response_text, re.IGNORECASE)
        if mentioned_ids and retrieved_txn_id:
            all_match = all(mid.upper() == retrieved_txn_id.upper() for mid in mentioned_ids)
            results.append({
                "eval_id": "TXN_ID_GROUNDED",
                "passed": all_match,
                "score": 1 if all_match else 0,
                "reason": f"Mentioned {set(mentioned_ids)}, retrieved {retrieved_txn_id}" if not all_match else "ok",
            })
        else:
            results.append({
                "eval_id": "TXN_ID_GROUNDED",
                "passed": True,
                "score": 1,
                "reason": "No TXN ID to cross-check",
            })

    # TIMELINE_ACCURATE — if response mentions a reversal/batch date, it must be calculable
    # from initiated_at. Checks presence of a date pattern when a deadline is expected.
    if retrieved_transaction and retrieved_transaction.get("initiated_at"):
        combined_response = card.get("response", "") + " " + card.get("next_step", "")
        has_date_mention = bool(re.search(r"\b\d{1,2}\s+\w+\b|\b\w+\s+\d{1,2}\b|T\+\d", combined_response))
        results.append({
            "eval_id": "TIMELINE_MENTIONED",
            "passed": has_date_mention,
            "score": 1 if has_date_mention else 0,
            "reason": "Response does not mention a specific date or timeline" if not has_date_mention else "ok",
        })

    # --- Subjective evals (code-based heuristics, no LLM) ---

    # EMPATHY_ACKNOWLEDGMENT — when user expresses distress, response must acknowledge it
    _DISTRESS_KEYWORDS = ["urgent", "emergency", "rent", "hospital", "need today", "desperate", "please help"]
    _EMPATHY_MARKERS = [
        "understand", "priority", "prioritise", "prioritize", "prioritised", "prioritized",
        "concern", "appreciate", "sorry", "right away", "immediately",
        "aware", "recogni", "hear you", "seriously",
    ]
    user_lower = user_message.lower()
    has_distress = any(k in user_lower for k in _DISTRESS_KEYWORDS)
    if has_distress:
        resp_lower = (card.get("response", "") + " " + card.get("next_step", "")).lower()
        has_empathy = any(m in resp_lower for m in _EMPATHY_MARKERS)
        results.append({
            "eval_id": "EMPATHY_ACKNOWLEDGMENT",
            "passed": has_empathy,
            "score": 1 if has_empathy else 0,
            "reason": "Distress detected but no empathy marker in response" if not has_empathy else "ok",
        })
    else:
        results.append({
            "eval_id": "EMPATHY_ACKNOWLEDGMENT",
            "passed": True,
            "score": 1,
            "reason": "No distress detected",
        })

    # COHERENCE_CATEGORY_MATCH — response must not reference the wrong category's domain
    _CATEGORY_SIGNALS = {
        "UPI_FAILURE": ["upi", "payment failed", "debited"],
        "POT_WITHDRAWAL": ["pot", "savings pot", "withdrawal", "neft"],
    }
    resp_text = (card.get("response", "") + " " + card.get("next_step", "")).lower()
    wrong_category_mentioned = False
    for other_cat, signals in _CATEGORY_SIGNALS.items():
        if other_cat == cat:
            continue
        if any(s in resp_text for s in signals):
            wrong_category_mentioned = True
            break
    results.append({
        "eval_id": "COHERENCE_CATEGORY_MATCH",
        "passed": not wrong_category_mentioned,
        "score": 0 if wrong_category_mentioned else 1,
        "reason": f"Response references {other_cat} domain but card is {cat}" if wrong_category_mentioned else "ok",
    })

    # TONE_PROFESSIONAL — no ALL CAPS words (>3 chars), no multiple exclamation marks
    _response_raw = card.get("response", "") + " " + card.get("next_step", "")
    has_shouting = bool(re.search(r"\b[A-Z]{4,}\b", _response_raw)) and cat not in ("",)
    # Exclude known acronyms/IDs
    _shouting_words = re.findall(r"\b[A-Z]{4,}\b", _response_raw)
    _allowed_caps = {"NPCI", "NEFT", "UPI", "INR", "RBI", "IMPS", "SLA", "IST", "POT"}
    real_shout = [w for w in _shouting_words if w not in _allowed_caps and not re.match(r"TXN\d+", w)]
    has_multi_excl = "!!" in _response_raw
    tone_ok = not real_shout and not has_multi_excl
    results.append({
        "eval_id": "TONE_PROFESSIONAL",
        "passed": tone_ok,
        "score": 1 if tone_ok else 0,
        "reason": (
            f"ALL CAPS words: {real_shout}" if real_shout
            else "Multiple exclamation marks" if has_multi_excl
            else "ok"
        ),
    })

    return results
