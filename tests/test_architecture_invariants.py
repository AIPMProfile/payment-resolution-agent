"""
Architecture invariants — the rules in CLAUDE.md that no test previously enforced.

These are the guarantees the project treats as non-negotiable: loop boundaries,
model routing, the mandatory human approval gate, and trace completeness. Each
test below maps to one "Never" or "never swap" rule. They are cheap and static
where possible so a boundary violation fails fast in CI rather than in review.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_APP_ROOT = Path(__file__).parents[1] / "app"


def _python_files(package: str) -> list[Path]:
    files = [p for p in (_APP_ROOT / package).glob("*.py") if p.name != "__init__.py"]
    assert files, f"No modules found in app/{package}/ — invariant test is not scanning anything"
    return files


def _string_constants(tree: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _imported_module_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# --- Loop boundary: Verification must stay deterministic ---

def test_verification_loop_makes_no_anthropic_calls():
    """
    CLAUDE.md: "Call the Anthropic API from app/verification/" is a Never.
    The verification loop must stay deterministic — an LLM call here makes
    policy decisions non-reproducible and breaks the release gate's baselines.
    """
    offenders = []
    for path in _python_files("verification"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if "anthropic" in _imported_module_roots(tree):
            offenders.append(f"{path.name}: imports anthropic")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "anthropic":
                offenders.append(f"{path.name}: references anthropic at line {node.lineno}")

    assert not offenders, (
        "Verification loop must make no Anthropic API calls:\n  " + "\n  ".join(offenders)
    )


def test_verification_loop_does_not_import_core_composer_or_classifier():
    """Importing the LLM-backed core modules would reintroduce nondeterminism indirectly."""
    offenders = []
    for path in _python_files("verification"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app.core"):
                    offenders.append(f"{path.name} imports {node.module}")

    assert not offenders, (
        "Verification loop must not depend on app/core/ (LLM-backed):\n  " + "\n  ".join(offenders)
    )


# --- Loop boundary: Core must not write to eval_queue ---

def test_core_loop_never_writes_to_eval_queue():
    """
    CLAUDE.md: "Write to eval_queue from app/core/" is a Never.
    eval_queue belongs to the Lifecycle loop; a write from Core would produce
    duplicate trace rows and corrupt nightly analysis clustering.
    """
    offenders = []
    for path in _python_files("core"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if "eval_queue" in _string_constants(tree):
            offenders.append(path.name)

    assert not offenders, (
        "Core loop must not reference eval_queue (Lifecycle loop owns it): " + ", ".join(offenders)
    )


# --- Model routing: never swap ---

def test_model_routing_is_unchanged():
    """
    CLAUDE.md pins each model to one role. Swapping them silently changes cost
    and quality characteristics, and the Opus judge grading its own output would
    invalidate the nightly analysis.
    """
    from app.core import classifier, composer
    from app.learning import nightly_analysis

    assert classifier._HAIKU == "claude-haiku-4-5-20251001", "classify_ticket must run on Haiku"
    assert composer._SONNET == "claude-sonnet-4-6", "compose_response must run on Sonnet"
    assert nightly_analysis._OPUS == "claude-opus-4-8", "LLM judge must run on Opus"
    assert nightly_analysis._SONNET == "claude-sonnet-4-6", "Suggestion generation must run on Sonnet"


def test_opus_is_only_used_by_nightly_analysis():
    """The Opus judge is confined to app/learning/nightly_analysis.py."""
    offenders = []
    for package in ("core", "verification", "lifecycle", "learning"):
        for path in _python_files(package):
            if path.name == "nightly_analysis.py":
                continue
            if any("opus" in s for s in _string_constants(ast.parse(path.read_text(encoding="utf-8")))):
                offenders.append(f"{package}/{path.name}")

    assert not offenders, (
        "Opus may only be referenced in nightly_analysis.py: " + ", ".join(offenders)
    )


# --- Trace completeness ---

@pytest.mark.asyncio
async def test_card_trace_insert_includes_both_model_ids():
    """
    CLAUDE.md: "Include model_id and classifier_model_id in every eval_queue
    trace_data insert." Without them, nightly analysis cannot attribute a
    failure to the model that produced it.
    """
    from app.lifecycle import chat_handler

    db = MagicMock()
    chain = MagicMock()
    chain.insert.return_value = chain
    db.table.return_value = chain

    with patch.object(chat_handler, "get_supabase_client", return_value=db):
        await chat_handler._log_trace(
            ticket_id="tkt-001",
            card={"response": "r", "next_step": "n"},
            category="UPI_FAILURE",
            layer1_results=[],
            struct_results=[],
            tool_metadata={},
        )

    db.table.assert_called_with("eval_queue")
    payload = chain.insert.call_args[0][0]
    checks = payload["policy_checks_json"]
    assert checks["model_id"] == "claude-sonnet-4-6"
    assert checks["classifier_model_id"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_conversational_trace_insert_includes_both_model_ids():
    """Conversational (non-card) turns are traced too and must carry the same attribution."""
    from app.lifecycle import chat_handler

    db = MagicMock()
    chain = MagicMock()
    chain.insert.return_value = chain
    db.table.return_value = chain

    with patch.object(chat_handler, "get_supabase_client", return_value=db):
        await chat_handler._log_conversational_trace(
            ticket_id="tkt-001",
            response_text="text",
            category="UPI_FAILURE",
            situation="post_escalation",
        )

    db.table.assert_called_with("eval_queue")
    checks = chain.insert.call_args[0][0]["policy_checks_json"]
    assert checks["model_id"] == "claude-sonnet-4-6"
    assert checks["classifier_model_id"] == "claude-haiku-4-5-20251001"


# --- Human approval gate: no auto-apply ---

@pytest.mark.asyncio
async def test_nightly_analysis_writes_suggestions_as_pending_only():
    """
    CLAUDE.md: "Auto-apply a policy suggestion" is a Never — the human approval
    gate is mandatory. Every suggestion nightly analysis produces must land as
    status=pending and nothing else.
    """
    from app.learning import nightly_analysis

    traces = [
        {
            "eval_id": f"ev-{i}",
            "ticket_id": f"tkt-{i}",
            "response_text": "Great question! Your money is guaranteed.",
            "classification": "UPI_FAILURE",
            "category": "UPI_FAILURE",
            "policy_checks_json": {
                # Mirrors the real policy_checker result shape: rule_id, passed,
                # reason_code, explanation
                "layer1": [{
                    "rule_id": "NO_FILLER",
                    "passed": False,
                    "reason_code": "FILLER_OPENER",
                    "explanation": 'Filler opener: "great question"',
                }],
                "struct": [],
            },
        }
        for i in range(4)
    ]

    inserts: list[tuple[str, dict]] = []

    db = MagicMock()

    def _table(name):
        chain = MagicMock()
        result = MagicMock()
        result.data = traces if name == "eval_queue" else []
        chain.select.return_value = chain
        chain.not_.is_.return_value = chain
        chain.gte.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = result

        def _insert(payload):
            inserts.append((name, payload))
            return chain

        chain.insert.side_effect = _insert
        return chain

    db.table.side_effect = _table

    suggestion = {
        "failure_pattern": "UPI_FAILURE|NO_FILLER failed 4 times",
        "affected_layer": "prompt",
        "suggested_fix_text": "Never open with a filler phrase.",
        "confidence": 0.8,
    }

    with patch.object(nightly_analysis, "get_supabase_client", return_value=db), \
         patch.object(nightly_analysis, "_generate_suggestion", AsyncMock(return_value=suggestion)), \
         patch.object(nightly_analysis, "_run_opus_judge", AsyncMock(return_value={})), \
         patch("app.knowledge.policy_loader.update_skill_file") as mock_write_skill, \
         patch("anthropic.AsyncAnthropic", MagicMock()):
        await nightly_analysis.run_nightly_analysis(min_cluster_size=3)

    suggestion_inserts = [p for table, p in inserts if table == "policy_suggestions"]
    assert suggestion_inserts, "Expected nightly analysis to create at least one suggestion"
    for payload in suggestion_inserts:
        assert payload["status"] == "pending", (
            f"Suggestion written with status={payload['status']!r} — only 'pending' is allowed; "
            "the human approval gate is mandatory"
        )

    mock_write_skill.assert_not_called()
    assert not any(t in ("policy_versions",) for t, _ in inserts), (
        "Nightly analysis must not write policy_versions — that happens only on human approval"
    )


def test_nightly_analysis_does_not_touch_skill_files_or_policy_rules():
    """Static guard: the Learning loop's analysis step has no write path to the knowledge layer."""
    source = (_APP_ROOT / "learning" / "nightly_analysis.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.update(a.name for a in node.names)

    assert "update_skill_file" not in imported_names, (
        "nightly_analysis.py must not import update_skill_file — suggestions are applied "
        "only through the human-gated admin approval flow"
    )


# --- Atomic policy change ---

def test_approval_reverts_skill_file_when_eval_gate_detects_regression():
    """
    An approved suggestion that regresses a hard eval must leave the skill file
    exactly as it was, and must not record a policy_versions row.
    """
    from app.learning import admin_api

    db = MagicMock()
    inserts: list[str] = []

    def _table(name):
        chain = MagicMock()
        result = MagicMock()
        result.data = [{
            "suggestion_id": "sug-1",
            "status": "pending",
            "failure_pattern": "UPI_FAILURE|NO_FILLER failed 4 times",
            "suggested_fix_text": "NEW SKILL CONTENT",
        }] if name == "policy_suggestions" else []
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = result
        chain.insert.side_effect = lambda payload: (inserts.append(name), chain)[1]
        return chain

    db.table.side_effect = _table

    writes: list[tuple[str, str]] = []

    with patch.object(admin_api, "get_supabase_client", return_value=db), \
         patch.object(admin_api, "load_skill", return_value="OLD SKILL CONTENT"), \
         patch.object(admin_api, "update_skill_file", side_effect=lambda c, t: writes.append((c, t))), \
         patch.object(admin_api, "reload_policy_rules", MagicMock()), \
         patch.object(admin_api, "eval_gate_check", side_effect=[
             {"status": "pass", "hard_regressions": []},
             {"status": "fail", "hard_regressions": ["NO_GUARANTEE"]},
         ]):
        with pytest.raises(Exception) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                admin_api.approve_suggestion("sug-1", MagicMock(reviewer="anusha"))
            )

    assert "422" in str(exc_info.value) or "422" in repr(exc_info.value)
    assert writes[-1][1] == "OLD SKILL CONTENT", (
        "Skill file must be restored to its previous content when the eval gate fails"
    )
    assert "policy_versions" not in inserts, (
        "No policy_versions row may be written when the eval gate blocks the change"
    )


def test_git_ops_stages_skill_file_and_policy_rules_together():
    """
    CLAUDE.md: policy_rules.json and the skill file must always change together.
    commit_policy_change must stage both paths in the same commit, never one alone.
    """
    from app.learning import git_ops

    calls: list[tuple[str, ...]] = []

    def _fake_git(*args):
        calls.append(args)
        if args[0] == "diff":
            return True, " skills/UPI_FAILURE.md | 2 +-"
        return True, ""

    with patch.object(git_ops, "_run_git", side_effect=_fake_git), \
         patch.object(git_ops.Path, "exists", return_value=True):
        result = git_ops.commit_policy_change(
            category="UPI_FAILURE",
            version=2,
            change_reason="tighten filler wording",
            reviewer="anusha",
            suggestion_id="sug-1",
        )

    added = [args[1] for args in calls if args[0] == "add"]
    assert "skills/UPI_FAILURE.md" in added
    assert "app/knowledge/policy_rules.json" in added, (
        "policy_rules.json must be staged alongside the skill file — they change atomically"
    )

    commits = [args for args in calls if args[0] == "commit"]
    assert len(commits) == 1, "Both files must land in a single commit, not sequential commits"
    assert result["committed"] is True
    assert set(result["files"]) == {"skills/UPI_FAILURE.md", "app/knowledge/policy_rules.json"}
