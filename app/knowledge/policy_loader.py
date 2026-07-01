from __future__ import annotations

import json
from datetime import date, timedelta, datetime, timezone
from functools import lru_cache
from pathlib import Path

_POLICY_PATH = Path(__file__).parent / "policy_rules.json"
_SKILLS_PATH = Path(__file__).parents[2] / "skills"


@lru_cache()
def load_policy_rules() -> dict:
    with open(_POLICY_PATH) as f:
        return json.load(f)


def reload_policy_rules() -> dict:
    load_policy_rules.cache_clear()
    return load_policy_rules()


def load_skill(category: str) -> str:
    skill_file = _SKILLS_PATH / f"{category}.md"
    if not skill_file.exists():
        return ""
    return skill_file.read_text(encoding="utf-8")


def update_skill_file(category: str, new_content: str) -> None:
    skill_file = _SKILLS_PATH / f"{category}.md"
    skill_file.write_text(new_content, encoding="utf-8")


def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon–Fri
            added += 1
    return current


def calculate_upi_t5_deadline(initiated_at: datetime) -> date:
    rules = load_policy_rules()
    n = rules["rules"]["NPCI_RULE_UPI_T5"]["reversal_business_days"]
    return add_business_days(initiated_at.date(), n)


def calculate_next_neft_batch(initiated_at: datetime) -> datetime:
    """Return the next NEFT batch datetime after initiated_at (IST-aware)."""
    rules = load_policy_rules()
    neft = rules["rules"]["NEFT_RULE_BATCH_WINDOW"]
    cutoff_h = neft["late_cutoff_hour"]
    cutoff_m = neft["late_cutoff_minute"]

    # Normalise to a naive datetime for arithmetic, then restore tz
    tz = initiated_at.tzinfo
    dt = initiated_at.replace(second=0, microsecond=0)

    if dt.hour >= cutoff_h and dt.minute >= cutoff_m:
        # After 23:00 — next morning's first batch at 00:30
        next_day = (dt + timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)
        return next_day

    # Round up to next :00 or :30
    if dt.minute < 30:
        batch = dt.replace(minute=30)
    else:
        batch = (dt + timedelta(hours=1)).replace(minute=0)

    return batch


def is_neft_escalation_due(initiated_at: datetime, now: datetime | None = None) -> bool:
    rules = load_policy_rules()
    threshold_h = rules["rules"]["NEFT_RULE_ESCALATION_THRESHOLD"]["threshold_hours"]
    if now is None:
        now = datetime.now(timezone.utc)
    elapsed = (now - initiated_at).total_seconds() / 3600
    return elapsed > threshold_h
