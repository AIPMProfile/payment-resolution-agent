# Decision: Human approval gate is non-negotiable

**Date:** 2026-06-25
**Status:** Active
**Category:** Compliance

## Context
The Learning loop's nightly analysis generates suggestions for improving policy rules and skill files. In most agent systems, these changes would be auto-applied to maximize improvement velocity.

## Decision
The admin approval gate can never be bypassed. Nightly analysis generates suggestions with `status=pending`. Only an authenticated admin can approve, which atomically updates the skill file and `policy_rules.json`, and logs the change to `policy_versions`.

## Why
Automated policy changes in a financial services context create regulatory and liability risk. Every change must have:
- A human reviewer on record
- A diff showing what changed
- A rollback path via `policy_versions`

## Consequences
- `admin_api.py` enforces Bearer token auth on all approval endpoints
- Every approved change creates a `policy_versions` row with `old_content` and `new_content`
- Rollback is available via `POST /admin/versions/{version_id}/rollback`
- The eval gate runs before approval -- if hard regressions are detected, the approval is blocked
