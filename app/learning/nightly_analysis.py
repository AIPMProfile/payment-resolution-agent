from __future__ import annotations
from typing import Optional
"""
Loop 4, Part B: nightly engine analysis.
1. Read last 24h traces from eval_queue (Supabase).
2. Run code-based evals on all traces.
3. Run Opus judge on flagged traces (helpful_score=1, free text).
4. Cluster failures. If same pattern 3+ times, run Sonnet to generate suggestion.
5. Write suggestions to policy_suggestions.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import anthropic

from app.config import get_settings
from app.db.supabase_client import get_supabase_client
from app.knowledge.prompts import OPUS_JUDGE_PROMPT, SUGGESTION_PROMPT
from app.verification.policy_checker import run_policy_checks
from app.verification.structural_evals import run_structural_evals

logger = logging.getLogger(__name__)

_OPUS = "claude-opus-4-8"
_SONNET = "claude-sonnet-4-6"


def _last_24h_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def _load_traces(db) -> list[dict]:
    """Load eval_queue rows that have policy_checks_json (i.e. agent turn traces)."""
    cutoff = _last_24h_cutoff()
    r = (
        db.table("eval_queue")
        .select("*")
        .not_.is_("policy_checks_json", "null")
        .gte("created_at", cutoff)
        .execute()
    )
    return r.data or []


def _load_flagged_feedback(db) -> list[dict]:
    """Load feedback rows with score=1 or free text."""
    cutoff = _last_24h_cutoff()
    r = (
        db.table("eval_queue")
        .select("*")
        .gte("created_at", cutoff)
        .execute()
    )
    return [
        row for row in (r.data or [])
        if row.get("helpful_score") == 1
        or row.get("failure_freetext")
        or row.get("human_review_label") == "fail"
    ]


def _load_already_processed_ids(db) -> set[str]:
    """Return eval_ids already checkpointed during today's nightly run."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = (
        db.table("eval_queue")
        .select("failure_category, failure_freetext")
        .eq("failure_category", "nightly_checkpoint")
        .gte("created_at", today)
        .execute()
    )
    ids: set[str] = set()
    for row in (r.data or []):
        eid = row.get("failure_freetext")
        if eid:
            ids.add(eid)
    return ids


def _checkpoint_trace(db, eval_id: str) -> None:
    try:
        db.table("eval_queue").insert({
            "ticket_id": None,
            "failure_category": "nightly_checkpoint",
            "failure_freetext": eval_id,
        }).execute()
    except Exception:
        pass


async def _run_opus_judge(
    response_text: str,
    policy_checks: dict,
    feedback: dict,
    client: anthropic.AsyncAnthropic,
) -> list[dict] | None:
    prompt = OPUS_JUDGE_PROMPT.format(
        user_message="(retrieved from trace)",
        agent_response=json.dumps({"response_text": response_text}),
        transaction=json.dumps({}),
        policy_failures=json.dumps(policy_checks.get("layer1", [])),
        user_feedback=json.dumps(feedback),
    )
    try:
        resp = await client.messages.create(
            model=_OPUS,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(resp.content[0].text)
    except Exception as exc:
        logger.warning("Opus judge failed: %s", exc)
        return None


async def _generate_suggestion(
    failure_pattern: str,
    affected_layer: str,
    affected_category: Optional[str],
    count: int,
    trace_examples: list[dict],
    client: anthropic.AsyncAnthropic,
) -> dict | None:
    prompt = SUGGESTION_PROMPT.format(
        failure_pattern=failure_pattern,
        affected_layer=affected_layer,
        count=count,
        trace_examples=json.dumps(trace_examples[:3], default=str),
    )
    try:
        resp = await client.messages.create(
            model=_SONNET,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        suggestion = json.loads(text)
        suggestion["affected_category"] = affected_category
        return suggestion
    except Exception as exc:
        logger.warning("Suggestion generation failed: %s", exc)
        return None


async def run_nightly_analysis(min_cluster_size: int = 3) -> dict:
    db = get_supabase_client()
    client = anthropic.AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)

    traces = _load_traces(db)
    flagged_feedback = _load_flagged_feedback(db)
    already_processed = _load_already_processed_ids(db)
    logger.info(
        "Nightly analysis: %d traces, %d flagged feedback, %d already processed",
        len(traces), len(flagged_feedback), len(already_processed),
    )

    # Explicit "no new signal" stop condition
    new_traces = [t for t in traces if str(t.get("eval_id", "")) not in already_processed]
    if not new_traces and not flagged_feedback:
        stop_reason = "no_new_signal"
        if not traces:
            stop_reason = "input_missing"
        logger.info("Nightly analysis stop: %s — nothing meaningful changed", stop_reason)
        db.table("eval_queue").insert({
            "ticket_id": None,
            "failure_category": f"nightly_stop:{stop_reason}",
            "failure_freetext": f"Traces: {len(traces)}, new: {len(new_traces)}, flagged: {len(flagged_feedback)}",
        }).execute()
        return {
            "traces_analyzed": 0,
            "flagged_traces": 0,
            "policy_pass_rate": 1.0,
            "suggestions_created": 0,
            "failure_patterns": {},
            "stop_reason": stop_reason,
        }

    failure_clusters: dict[str, list] = defaultdict(list)
    total_policy_checks = 0
    total_policy_passes = 0

    for trace in traces:
        eval_id = str(trace.get("eval_id", ""))
        if eval_id in already_processed:
            continue

        policy_json = trace.get("policy_checks_json") or {}
        layer1 = policy_json.get("layer1", [])
        category = trace.get("classification")

        for r in layer1:
            total_policy_checks += 1
            if r["passed"]:
                total_policy_passes += 1
            else:
                cluster_key = f"{r['rule_id']}:{r['reason_code']}"
                failure_clusters[cluster_key].append({
                    "eval_id": eval_id,
                    "rule_id": r["rule_id"],
                    "explanation": r["explanation"],
                    "category": category,
                })

        _checkpoint_trace(db, eval_id)

    # Opus judge on flagged traces (score=1 or free text)
    flagged_ticket_ids = {f.get("ticket_id") for f in flagged_feedback}
    flagged_traces = [t for t in traces if t.get("ticket_id") in flagged_ticket_ids]

    for trace in flagged_traces[:20]:
        feedback_rows = [f for f in flagged_feedback if f.get("ticket_id") == trace.get("ticket_id")]
        feedback = {
            "helpful_score": feedback_rows[0].get("helpful_score"),
            "failure_freetext": feedback_rows[0].get("failure_freetext"),
            "human_review_label": feedback_rows[0].get("human_review_label"),
            "human_review_note": feedback_rows[0].get("human_review_note"),
        } if feedback_rows else {}

        judge_result = await _run_opus_judge(
            response_text=trace.get("response_text", ""),
            policy_checks=trace.get("policy_checks_json") or {},
            feedback=feedback,
            client=client,
        )
        if judge_result:
            db.table("eval_queue").update({
                "llm_judge_score": judge_result,
            }).eq("eval_id", trace["eval_id"]).execute()

    # Add human-annotated failures to clusters for suggestion generation
    for trace in flagged_traces:
        feedback_rows = [f for f in flagged_feedback if f.get("ticket_id") == trace.get("ticket_id")]
        if not feedback_rows:
            continue
        row = feedback_rows[0]
        if row.get("human_review_label") != "fail":
            continue
        eval_id = str(trace.get("eval_id", ""))
        category = trace.get("classification") or "UNKNOWN"
        note = row.get("human_review_note") or "admin flagged"
        cluster_key = f"HUMAN_REVIEW:{note}"
        failure_clusters[cluster_key].append({
            "eval_id": eval_id,
            "rule_id": "HUMAN_REVIEW",
            "explanation": note,
            "category": category,
        })

    # Generate suggestions for failure patterns meeting the occurrence threshold
    suggestions_created = 0
    for cluster_key, occurrences in failure_clusters.items():
        if len(occurrences) < min_cluster_size:
            continue

        rule_id, reason_code = cluster_key.split(":", 1)
        category = occurrences[0].get("category")
        affected_layer = (
            "policy" if "ESCALAT" in rule_id
            else "prompt" if "FILLER" in rule_id or "APPROXIMATION" in rule_id
            else "skill"
        )

        suggestion = await _generate_suggestion(
            failure_pattern=f"{category}|{rule_id} failed {len(occurrences)} times: {reason_code}",
            affected_layer=affected_layer,
            affected_category=category,
            count=len(occurrences),
            trace_examples=occurrences,
            client=client,
        )

        if suggestion:
            db.table("policy_suggestions").insert({
                "failure_pattern": suggestion["failure_pattern"],
                "affected_layer": suggestion["affected_layer"],
                "suggested_fix_text": suggestion["suggested_fix_text"],
                "confidence": str(suggestion.get("confidence", 0.5)),
                "source_trace_ids": [o["eval_id"] for o in occurrences],
                "status": "pending",
            }).execute()
            suggestions_created += 1

    policy_pass_rate = (total_policy_passes / total_policy_checks) if total_policy_checks else 1.0
    logger.info(
        "Nightly analysis complete: pass_rate=%.2f, suggestions=%d",
        policy_pass_rate, suggestions_created,
    )

    return {
        "traces_analyzed": len(traces),
        "flagged_traces": len(flagged_traces),
        "policy_pass_rate": round(policy_pass_rate, 4),
        "suggestions_created": suggestions_created,
        "failure_patterns": {k: len(v) for k, v in failure_clusters.items()},
    }
