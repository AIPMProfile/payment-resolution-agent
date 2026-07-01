# CLAUDE.md — Payment Resolution Agent

## Running the project
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in real keys
python -m app.db.seed         # insert seed users and transactions
uvicorn app.main:app --reload # start server at localhost:8000
```
Frontend is served at http://localhost:8000 (FastAPI static files).
Admin panel lives at /admin, served from frontend/admin.html. Never add admin UI elements to frontend/index.html.
Access: GET /admin?key=ADMIN_API_KEY (or Bearer header). Returns 403 if key is missing or wrong.

## Secrets
All secrets live in .env only. Never hardcode API keys. Never commit .env.
The .gitignore already excludes .env.

## Policy rule change process
policy_rules.json and the relevant skill file (/skills/*.md) must always be updated together.
The admin approval flow in the Learning loop does this atomically. Do not edit one without the other manually.

## Model routing — never swap
- claude-haiku-4-5-20251001: classify_ticket only
- claude-sonnet-4-6: compose_response and nightly analysis suggestions
- claude-opus-4-8: LLM judge in nightly_analysis.py only

## Loop boundaries — do not cross
- app/core/: Core loop only. No writes to eval_queue.
- app/verification/: Verification loop only. No Anthropic API calls.
- app/lifecycle/: Lifecycle loop only. chat_handler orchestrates Core+Verification.
- app/learning/: Learning loop only. No auto-applying suggestions.

## Running tests
```bash
pytest tests/ -v
```
test_regression_guarantee_language.py documents a real failure caught during testing.

## Supabase schema
Schema reference in supabase_schema.sql.
To reset seed data: truncate transactions and users tables, then re-run python -m app.db.seed.

## Arize observability
Use the Arize instrumentation skill from 
https://github.com/Arize-ai/arize-skills 
to set up tracing. Do not manually configure 
OTLP exporters. The skill handles endpoint, 
auth, and transport automatically. 
Credentials needed in .env: ARIZE_SPACE_ID, 
ARIZE_API_KEY, and ARIZE_MODEL_ID.

## Skills — progressive disclosure
Skills live in /skills/*.md at the project root — NOT in .claude/skills/.
Do not look for SKILL.md. Files are named by category: UPI_FAILURE.md, POT_WITHDRAWAL.md, OUT_OF_SCOPE.md.
Agent loads only the relevant skill file after classification. Never put resolution knowledge in prompts.py.

## Project structure
```
app/core/           Core loop — classify (Haiku) + compose (Sonnet) + retrieve (Supabase tool)
app/verification/   Verification loop — policy_checker (blocks) + structural_evals (scores); no LLM calls
app/lifecycle/      Lifecycle loop — chat_handler, followup_cron, autoclose_cron
app/learning/       Learning loop — feedback, nightly_analysis (Opus judge), admin_api (human gate), eval_gate, drift_check
app/knowledge/      policy_rules.json + prompts.py + policy_loader.py
app/observability/  arize_client.py — traces sent to Arize OTLP; no-op if keys missing
app/db/             Supabase client, Pydantic models, seed script
skills/             UPI_FAILURE.md, POT_WITHDRAWAL.md, OUT_OF_SCOPE.md — loaded per category
tests/              pytest suite; test_regression_guarantee_language.py is mandatory green
frontend/           Static HTML/CSS/JS served by FastAPI
```

## Boundaries
```
✅ Always
   Run pytest tests/ -v before any policy_rules.json or skill file edit
   Update policy_rules.json AND the relevant skill file together, never one without the other
   Add inline comment to every new policy_checker rule: # Failure: <what happened> | Rule: <rule_id>
   Include model_id and classifier_model_id in every eval_queue trace_data insert

⚠️ Ask first
   Add a new skill category (requires new classifier label, new skill file, new tests)
   Change model routing (Haiku/Sonnet/Opus roles)
   Modify Supabase table schema
   Change the retry limit in chat_handler.py (currently 3 attempts)
   Adjust the ₹50,000 escalation threshold in policy_rules.json

🚫 Never
   Commit .env or hardcode any API key
   Auto-apply a policy suggestion — the human approval gate in the Learning loop is mandatory
   Call the Anthropic API from app/verification/ (Verification loop must stay deterministic)
   Write to eval_queue from app/core/ (Core loop domain boundary)
   Remove or edit existing tests to make them pass
```

## Done-conditions per loop
Core loop complete: response card has exactly 4 fields (category, reference, response, next_step); category matches classifier output; tool sequence is classify → retrieve → compose.

Verification loop complete: all 7 policy checks return passed=True; structural eval scores are written to Arize; if retries exhausted, ticket is escalated and fixed message is returned.

Lifecycle loop complete: ticket row in Supabase has category, status, resolution_deadline, and conversation_json updated; eval_queue has a trace_data row for the turn with model_id present.

Learning loop complete: nightly_analysis runs without auto-applying any suggestion; policy_suggestions row has status=pending; admin endpoint returns the suggestion with a unified diff; approval passes eval gate and writes both skill file and policy_versions atomically. Weekly drift check compares golden eval scores to baseline thresholds.
