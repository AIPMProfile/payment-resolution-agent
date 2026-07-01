"""
Error Discovery — interactive failure analysis for LLM outputs and traces.
Implements the Error Discovery Skill Workflow:
  1. Load and enrich traces from eval_queue
  2. Cluster into failure modes
  3. Select diverse samples for human review
  4. Track annotation coverage and convergence
"""
from __future__ import annotations

import logging
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_traces(days: int = 7, limit: int = 200) -> list[dict]:
    db = get_supabase_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    r = (
        db.table("eval_queue")
        .select("*")
        .not_.is_("policy_checks_json", "null")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    traces = []
    for row in (r.data or []):
        pcj = row.get("policy_checks_json") or {}
        layer1 = pcj.get("layer1", [])
        failures = [r for r in layer1 if not r.get("passed")]
        traces.append({
            "eval_id": str(row.get("eval_id", "")),
            "ticket_id": str(row.get("ticket_id", "")),
            "category": row.get("classification", "UNKNOWN"),
            "response_text": row.get("response_text", ""),
            "helpful_score": row.get("helpful_score"),
            "failure_category": row.get("failure_category"),
            "failure_freetext": row.get("failure_freetext"),
            "policy_passed": len(failures) == 0,
            "policy_failures": failures,
            "policy_checks": layer1,
            "llm_judge_score": row.get("llm_judge_score"),
            "model_id": pcj.get("model_id"),
            "response_type": pcj.get("response_type", "card"),
            "annotation": row.get("failure_freetext") if (row.get("failure_category") or "").startswith("annotation:") else None,
            "annotation_mode": (row.get("failure_category") or "").replace("annotation:", "") if (row.get("failure_category") or "").startswith("annotation:") else None,
            "created_at": str(row.get("created_at", "")),
        })
    return traces


def get_failure_clusters(days: int = 7) -> dict:
    traces = get_traces(days=days, limit=500)

    clusters: dict[str, list] = defaultdict(list)
    category_counts: dict[str, int] = Counter()
    score_dist: dict[int, int] = Counter()

    for t in traces:
        category_counts[t["category"]] += 1
        if t["helpful_score"] is not None:
            score_dist[t["helpful_score"]] += 1

        for f in t["policy_failures"]:
            key = f"{f.get('rule_id', 'unknown')}:{f.get('reason_code', 'unknown')}"
            clusters[key].append({
                "eval_id": t["eval_id"],
                "category": t["category"],
                "explanation": f.get("explanation", ""),
                "response_preview": t["response_text"][:120],
            })

        if t["helpful_score"] == 1:
            clusters["low_score"].append({
                "eval_id": t["eval_id"],
                "category": t["category"],
                "explanation": t.get("failure_freetext", "User rated 1/3"),
                "response_preview": t["response_text"][:120],
            })

    failure_modes = []
    for key, items in sorted(clusters.items(), key=lambda x: -len(x[1])):
        categories_in_cluster = Counter(i["category"] for i in items)
        failure_modes.append({
            "mode_id": key,
            "count": len(items),
            "categories": dict(categories_in_cluster),
            "sample_explanation": items[0]["explanation"] if items else "",
            "severity": "high" if len(items) >= 5 else "medium" if len(items) >= 3 else "low",
            "trace_ids": [i["eval_id"] for i in items[:10]],
        })

    total = len(traces)
    failed = sum(1 for t in traces if not t["policy_passed"])
    annotated = sum(1 for t in traces if t["annotation"] is not None)

    # Per-category breakdown
    cat_stats: dict[str, dict] = {}
    for cat in category_counts:
        cat_traces = [t for t in traces if t["category"] == cat]
        cat_total = len(cat_traces)
        cat_failed = sum(1 for t in cat_traces if not t["policy_passed"])
        cat_scores = [t["helpful_score"] for t in cat_traces if t["helpful_score"] is not None]
        cat_escalated = sum(1 for t in cat_traces if t.get("failure_category") == "escalation")
        cat_stats[cat] = {
            "total": cat_total,
            "failed": cat_failed,
            "pass_rate": round((cat_total - cat_failed) / cat_total, 4) if cat_total else 1.0,
            "avg_helpful": round(sum(cat_scores) / len(cat_scores), 2) if cat_scores else None,
            "escalated": cat_escalated,
        }

    return {
        "total_traces": total,
        "failed_traces": failed,
        "pass_rate": round((total - failed) / total, 4) if total else 1.0,
        "annotated": annotated,
        "coverage": round(annotated / total, 4) if total else 0.0,
        "failure_modes": failure_modes,
        "category_distribution": dict(category_counts),
        "category_stats": cat_stats,
        "score_distribution": {str(k): v for k, v in sorted(score_dist.items())},
    }


def select_review_samples(days: int = 7, count: int = 20) -> list[dict]:
    traces = get_traces(days=days, limit=500)
    if not traces:
        return []

    clusters: dict[str, list] = defaultdict(list)
    for t in traces:
        if t["policy_failures"]:
            key = t["policy_failures"][0].get("rule_id", "unknown")
        elif t["helpful_score"] == 1:
            key = "low_score"
        elif t["helpful_score"] is None and not t["policy_passed"]:
            key = "unscored_failure"
        else:
            key = "passing"
        clusters[key].append(t)

    # 60-70% cluster representatives, 30-40% random
    cluster_picks = int(count * 0.65)
    random_picks = count - cluster_picks

    import random
    selected = []
    selected_ids = set()

    # Pick from each cluster proportionally
    non_passing = {k: v for k, v in clusters.items() if k != "passing"}
    if non_passing:
        per_cluster = max(1, cluster_picks // len(non_passing))
        for key, items in non_passing.items():
            sample = random.sample(items, min(per_cluster, len(items)))
            for s in sample:
                if s["eval_id"] not in selected_ids:
                    s["_sample_reason"] = f"cluster:{key}"
                    selected.append(s)
                    selected_ids.add(s["eval_id"])

    # Random picks from all traces
    remaining = [t for t in traces if t["eval_id"] not in selected_ids]
    if remaining:
        random_sample = random.sample(remaining, min(random_picks, len(remaining)))
        for s in random_sample:
            s["_sample_reason"] = "random"
            selected.append(s)
            selected_ids.add(s["eval_id"])

    return selected[:count]


def save_annotation(eval_id: str, annotation_text: str, failure_mode: str, reviewer: str) -> dict:
    db = get_supabase_client()
    db.table("eval_queue").insert({
        "ticket_id": None,
        "failure_category": f"annotation:{failure_mode}",
        "failure_freetext": f"[{reviewer}] {annotation_text}",
        "classification": failure_mode,
        "response_text": eval_id,
    }).execute()

    return {"status": "saved", "eval_id": eval_id, "mode": failure_mode}


def get_convergence(days: int = 7) -> dict:
    db = get_supabase_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Count annotations per day
    r = (
        db.table("eval_queue")
        .select("created_at, failure_category")
        .like("failure_category", "annotation:%")
        .gte("created_at", cutoff)
        .execute()
    )

    daily_annotations: dict[str, int] = Counter()
    modes_discovered: dict[str, str] = {}  # mode → first seen date

    for row in (r.data or []):
        day = str(row["created_at"])[:10]
        daily_annotations[day] += 1
        mode = row["failure_category"].replace("annotation:", "")
        if mode not in modes_discovered or day < modes_discovered[mode]:
            modes_discovered[mode] = day

    # New modes per day
    daily_new_modes: dict[str, int] = Counter()
    for mode, day in modes_discovered.items():
        daily_new_modes[day] += 1

    sorted_days = sorted(set(list(daily_annotations.keys()) + list(daily_new_modes.keys())))
    timeline = []
    cumulative_modes = 0
    for day in sorted_days:
        cumulative_modes += daily_new_modes.get(day, 0)
        timeline.append({
            "date": day,
            "annotations": daily_annotations.get(day, 0),
            "new_modes": daily_new_modes.get(day, 0),
            "cumulative_modes": cumulative_modes,
        })

    converging = len(sorted_days) >= 3 and daily_new_modes.get(sorted_days[-1], 0) == 0

    return {
        "timeline": timeline,
        "total_modes": len(modes_discovered),
        "total_annotations": sum(daily_annotations.values()),
        "converging": converging,
        "modes": list(modes_discovered.keys()),
    }
