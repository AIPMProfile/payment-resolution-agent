# AGENTS.md — Payment Resolution Agent

## Running the project
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in real keys
python -m app.db.seed         # seed users + transactions into Supabase
uvicorn app.main:app --reload # http://localhost:8000
pytest tests/ -v              # all 25 tests must pass
```
Frontend is served at http://localhost:8000 (FastAPI static files).
Admin panel lives at /admin, served from frontend/admin.html. Never add admin UI elements to frontend/index.html.
Access: GET /admin?key=ADMIN_API_KEY (or Bearer header). Returns 403 if key is missing or wrong.

## Secrets
All secrets live in .env only. Never hardcode API keys. Never commit .env.
The .gitignore already excludes .env.

## Project structure
```
app/core/           Core loop — classifier.py (Haiku), composer.py (Sonnet), retriever.py (Supabase tool)
app/verification/   Verification loop — policy_checker.py (blocks), structural_evals.py (scores); no LLM calls
app/lifecycle/      Lifecycle loop — chat_handler.py, followup_cron.py, autoclose_cron.py
app/learning/       Learning loop — feedback.py, nightly_analysis.py (Opus judge), admin_api.py, eval_gate.py, drift_check.py
app/knowledge/      policy_rules.json, prompts.py, policy_loader.py
app/observability/  arize_client.py — traces sent to Arize OTLP; no-op if keys missing
app/db/             models.py, seed.py, supabase_client.py, supabase_schema.sql
skills/             UPI_FAILURE.md, POT_WITHDRAWAL.md, OUT_OF_SCOPE.md — loaded per category
tests/              pytest suite; test_regression_guarantee_language.py is mandatory green
frontend/           index.html, admin.html, app.js, style.css (served as FastAPI static files)
```

## Skills — progressive disclosure
Skills live in /skills/*.md at the project root — not inside an agent tool's own skills directory, and there is no SKILL.md.
Files are named by category: UPI_FAILURE.md, POT_WITHDRAWAL.md, OUT_OF_SCOPE.md.
The agent loads only the relevant skill file after classification. Never put resolution knowledge in prompts.py.

## Skill contract — five-section format
Every skill file in /skills/ follows this exact structure:
```
## What happened       — one-paragraph plain-English description of the failure mode
## What you know       — grounded facts available from retrieved transaction data + policy rules
## What you do not know — explicit unknowns the agent must never invent
## Resolution rules    — numbered, deterministic steps; cite rule IDs (e.g. NPCI_RULE_UPI_T5)
## What to never say   — forbidden phrases specific to this category
```
Do not add or remove sections. Do not put resolution knowledge in prompts.py.

## Model routing — never swap
- claude-haiku-4-5-20251001: classify_ticket only. One call per turn. Never composition.
- claude-sonnet-4-6: compose_response and nightly analysis suggestions. Never classification or judging.
- claude-opus-4-8: LLM judge in nightly_analysis.py only. Never composition. Reduces self-evaluation bias when judging Sonnet output.

Never swap models between roles without updating this file and the test expectations
in tests/test_architecture_invariants.py.

## Loop boundaries — do not cross
- app/core/: Core loop only. No writes to eval_queue.
- app/verification/: Verification loop only. No LLM API calls — must stay deterministic.
- app/lifecycle/: Lifecycle loop only. chat_handler orchestrates Core + Verification.
- app/learning/: Learning loop only. No auto-applying suggestions.

## Boundaries — three tiers
```
✅ Always (no approval needed)
   Run pytest tests/ -v before any policy_rules.json or skill file edit
   Run policy_checker on every composed response before returning it
   Load the skill file after classification, before composition
   Update policy_rules.json AND the relevant skill file together, atomically
   Add inline comment to every new policy_checker rule: # Failure: <what happened> | Rule: <rule_id>
   Include model_id and classifier_model_id in every eval_queue trace_data insert

⚠️ Ask first (needs approval)
   Add a new skill category (requires new classifier label, new skill file, new tests)
   Change model routing (Haiku/Sonnet/Opus roles)
   Modify Supabase table schema
   Change the retry limit in chat_handler.py (currently 3 attempts)
   Adjust the ₹50,000 escalation threshold in policy_rules.json

🚫 Never
   Commit .env or hardcode any API key
   Core loop writes to eval_queue (Learning loop domain only)
   Verification loop calls the LLM API (must stay deterministic)
   Learning loop auto-applies a policy suggestion (human gate in admin_api.py is mandatory)
   Cron jobs bypass Verification loop verification
   Remove or edit existing tests to make them pass
```

## Policy rule change process
policy_rules.json and the relevant skill file (/skills/*.md) must always be updated together.
Never one without the other. The admin approval flow in the Learning loop does this atomically.
policy_versions records old_content and new_content for rollback.

## Eval discipline
- Code-based evals (policy_checker.py, structural_evals.py): objective checks only — schema, format, forbidden phrases, citations
- Opus LLM judge: resolution quality and honest uncertainty only. Runs on flagged traces only, never every trace
- Tone signal comes from user free text keyword matching, not LLM judge
- Timeline accuracy tracked by deterministic counter, not LLM

## One rule per real failure
Every constraint in policy_checker.py has an inline comment: # Failure: <what happened> | Rule: <rule_id>
If you add a rule without a documented failure mode, it does not belong in policy_checker.py.

## Running tests
```bash
pytest tests/ -v
```
test_regression_guarantee_language.py documents a real failure caught during testing.

## Supabase schema
Schema reference in app/db/supabase_schema.sql.
To reset seed data: truncate transactions and users tables, then re-run python -m app.db.seed.

## Session persistence
In-flight ticket state lives in Supabase `tickets` table. If the FastAPI process restarts mid-conversation, the next request calls `_get_or_create_ticket` which resumes the existing open ticket by user_id. No in-memory state is required between requests. Cron jobs are idempotent — `followup_cron` selects open tickets where `resolution_deadline < now`, `autoclose_cron` selects open/pending tickets where `resolution_deadline` is more than 48 hours in the past.

## Arize observability
Use the Arize instrumentation skill from https://github.com/Arize-ai/arize-skills to set up tracing.
Do not manually configure OTLP exporters — the skill handles endpoint, auth, and transport automatically.
Credentials needed in .env: ARIZE_SPACE_ID, ARIZE_API_KEY, ARIZE_MODEL_ID.

## Stack decisions
- FastAPI not Flask: async-native, Pydantic validation built in, APScheduler fits the lifespan hook cleanly
- APScheduler not cron: single process for local demo; cron jobs live inside the FastAPI lifespan, no extra infra
- Skills not system prompt: progressive disclosure keeps Sonnet context lean; skill updates are isolated to one file
- policy_rules.json not .py: JSON diffs are readable and safe to apply without executing code; Learning loop writes JSON

## Done-conditions per loop
Core loop complete: response card has exactly 4 fields (category, reference, response, next_step); category matches classifier output; tool sequence is classify → retrieve → compose.

Verification loop complete: all 7 policy checks return passed=True; structural eval scores are written to Arize; if retries exhausted, ticket is escalated and fixed message is returned.

Lifecycle loop complete: ticket row in Supabase has category, status, resolution_deadline, and conversation_json updated; eval_queue has a trace_data row for the turn with model_id present.

Learning loop complete: nightly_analysis runs without auto-applying any suggestion; policy_suggestions row has status=pending; admin endpoint returns the suggestion with a unified diff; approval passes eval gate and writes both skill file and policy_versions atomically. Weekly drift check compares golden eval scores to baseline thresholds.

## Demo done-condition (end-to-end)
The demo is working when ALL of the following are true:
1. `POST /chat` with user USR001 and message "my Swiggy payment is stuck" returns a JSON card with `category: UPI_FAILURE`, a TXN ID in `reference`, and no forbidden phrases
2. The response passes all 7 policy checks (no failures logged)
3. A `trace_data` row appears in Supabase `eval_queue` within seconds, containing `model_id`
4. The Arize dashboard shows a `chat_turn` span with `classify` and `compose` child spans
5. `POST /feedback` with `helpful_score: 1` writes to `eval_queue` as `user_feedback`
6. `GET /admin/metrics` (Bearer ADMIN_API_KEY) returns `policy_pass_rate` > 0
