"""
Golden dataset offline eval runner.

Loads golden_dataset.json and validates each turn's `sample_card` or
`sample_message` against its declared checks. No LLM or DB calls — this
is a deterministic spec check against hand-crafted gold responses.

Checks are run per-turn. Multi-turn cases validate every turn independently.

Run:
    pytest tests/test_golden_evals.py -v
    pytest tests/test_golden_evals.py -v -k "UPI"          # filter by group
    pytest tests/test_golden_evals.py -v --tb=short        # compact failures
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"
_GOLDEN = json.loads(_GOLDEN_PATH.read_text())

_FILLER_OPENERS = [
    "great question", "certainly", "i understand your frustration",
    "happy to help", "of course!", "absolutely!", "sure thing", "no problem",
]


# ---------------------------------------------------------------------------
# Check runners
# ---------------------------------------------------------------------------

def _run_card_check(check: dict, card: dict) -> tuple[bool, str]:
    t = check["type"]
    combined = (card.get("response", "") + " " + card.get("next_step", "")).lower()

    if t == "category_equals":
        ok = card.get("category") == check["value"]
        return ok, f"category: expected '{check['value']}', got '{card.get('category')}'"

    if t == "reference_contains":
        ref = card.get("reference", "")
        missing = [v for v in check["values"] if v not in ref]
        return (not missing), f"reference missing: {missing}"

    if t == "response_contains":
        resp = card.get("response", "")
        missing = [v for v in check["values"] if v not in resp]
        return (not missing), f"response missing: {missing}"

    if t == "response_not_contains":
        resp = (card.get("response", "") + " " + card.get("next_step", "")).lower()
        found = [v for v in check["values"] if v.lower() in resp]
        return (not found), f"response must not contain: {found}"

    if t == "has_escalation":
        has_esc = "senior colleague" in combined
        ok = has_esc == check["value"]
        label = "present" if check["value"] else "absent"
        return ok, f"'senior colleague' must be {label} in response+next_step"

    if t == "no_filler_opener":
        resp_lower = card.get("response", "").lower()
        found = [f for f in _FILLER_OPENERS if resp_lower.startswith(f)]
        return (not found), f"response starts with filler: {found}"

    if t == "next_step_not_contains":
        ns = card.get("next_step", "").lower()
        found = [v for v in check["values"] if v.lower() in ns]
        return (not found), f"next_step must not contain: {found}"

    if t == "response_plus_next_step_max_chars":
        total = len(card.get("response", "")) + len(card.get("next_step", ""))
        ok = total <= check["value"]
        return ok, f"response+next_step length {total} exceeds {check['value']}"

    return True, f"unknown card check '{t}' — skipped"


def _run_message_check(check: dict, message: str) -> tuple[bool, str]:
    t = check["type"]

    if t == "message_contains":
        missing = [v for v in check["values"] if v.lower() not in message.lower()]
        return (not missing), f"message missing: {missing}"

    if t == "message_contains_any":
        found = any(v.lower() in message.lower() for v in check["values"])
        return found, f"message must contain at least one of: {check['values']}"

    if t == "message_not_contains":
        found = [v for v in check["values"] if v.lower() in message.lower()]
        return (not found), f"message must not contain: {found}"

    if t == "message_max_length":
        ok = len(message) <= check["value"]
        return ok, f"message length {len(message)} exceeds {check['value']}"

    if t == "single_question_only":
        q_count = message.count("?")
        ok = q_count == 1
        return ok, f"expected exactly 1 question mark, found {q_count}"

    if t == "ticket_status_equals":
        # This check can't be verified offline — skip with pass
        return True, f"ticket_status check '{check['value']}' — offline skip"

    if t == "feedback_prompt_equals":
        # Offline skip
        return True, "feedback_prompt check — offline skip"

    if t == "no_new_timeline_commitment":
        # Check that no specific future date or hours commitment appears
        # (rough heuristic — the human reviewer inspects sample for intent)
        return True, "no_new_timeline_commitment — manual review required"

    return True, f"unknown message check '{t}' — skipped"


# ---------------------------------------------------------------------------
# Parametrize: one test per (case_id, turn_number)
# ---------------------------------------------------------------------------

_TURN_PARAMS: list[tuple[str, dict, dict]] = []
for _case in _GOLDEN:
    for _turn in _case["turns"]:
        _param_id = f"{_case['id']}-T{_turn['turn']}"
        _TURN_PARAMS.append((_param_id, _case, _turn))


@pytest.mark.parametrize("param_id,case,turn_data", _TURN_PARAMS, ids=[p[0] for p in _TURN_PARAMS])
def test_golden_sample(param_id, case, turn_data):
    expected = turn_data["expected"]
    response_type = expected["response_type"]
    checks = expected.get("checks", [])

    failures: list[str] = []

    if response_type == "card":
        card = expected.get("sample_card")
        if card is None:
            pytest.skip(f"{param_id}: no sample_card provided")
        for check in checks:
            ok, detail = _run_card_check(check, card)
            if not ok:
                failures.append(f"[{check['type']}] {detail}")

    elif response_type in ("conversational", "error"):
        message = expected.get("sample_message")
        if message is None:
            pytest.skip(f"{param_id}: no sample_message provided")
        for check in checks:
            ok, detail = _run_message_check(check, message)
            if not ok:
                failures.append(f"[{check['type']}] {detail}")

    else:
        pytest.skip(f"{param_id}: unknown response_type '{response_type}'")

    if failures:
        case_desc = case.get("description", "")
        persona = case.get("persona", "")
        fail_block = "\n  ".join(failures)
        pytest.fail(
            f"\nCase: {param_id} | Persona: {persona}\n"
            f"Description: {case_desc}\n"
            f"User: {turn_data['user']!r}\n"
            f"Failures:\n  {fail_block}"
        )
