from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parents[2]


def _run_git(*args: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return False, str(e)


def commit_policy_change(
    category: str,
    version: int,
    change_reason: str,
    reviewer: str,
    suggestion_id: str,
) -> dict:
    skill_file = f"skills/{category}.md"
    policy_file = "app/knowledge/policy_rules.json"

    staged = []
    for f in [skill_file, policy_file]:
        if (_REPO_ROOT / f).exists():
            ok, _ = _run_git("add", f)
            if ok:
                staged.append(f)

    if not staged:
        return {"committed": False, "reason": "No changed files to stage"}

    ok, diff_out = _run_git("diff", "--cached", "--stat")
    if not diff_out:
        return {"committed": False, "reason": "No staged changes detected"}

    msg = (
        f"policy: update {category} v{version}\n\n"
        f"Reason: {change_reason}\n"
        f"Reviewer: {reviewer}\n"
        f"Suggestion: {suggestion_id}\n"
        f"Files: {', '.join(staged)}"
    )

    ok, out = _run_git("commit", "-m", msg)
    if not ok:
        logger.warning("Git commit failed: %s", out)
        return {"committed": False, "reason": out}

    logger.info("Committed policy change: %s v%d by %s", category, version, reviewer)
    return {"committed": True, "files": staged, "version": version}


def commit_rollback(category: str, version_id: str, reviewer: str) -> dict:
    skill_file = f"skills/{category}.md"
    policy_file = "app/knowledge/policy_rules.json"

    staged = []
    for f in [skill_file, policy_file]:
        if (_REPO_ROOT / f).exists():
            ok, _ = _run_git("add", f)
            if ok:
                staged.append(f)

    if not staged:
        return {"committed": False, "reason": "No changed files to stage"}

    msg = (
        f"policy: rollback {category}\n\n"
        f"Rolled back to version {version_id}\n"
        f"Reviewer: {reviewer}\n"
        f"Files: {', '.join(staged)}"
    )

    ok, out = _run_git("commit", "-m", msg)
    if not ok:
        return {"committed": False, "reason": out}

    logger.info("Committed rollback: %s by %s", category, reviewer)
    return {"committed": True, "files": staged}
