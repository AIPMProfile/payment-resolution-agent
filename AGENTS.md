# AGENTS.md — Payment Resolution Agent

## Commands (see CLAUDE.md for full setup)
```bash
pip install -r requirements.txt
python -m app.db.seed         # seed users + transactions into Supabase
uvicorn app.main:app --reload # http://localhost:8000
pytest tests/ -v              # all 25 tests must pass
```

## Project structure
```
skills/             UPI_FAILURE.md, POT_WITHDRAWAL.md, OUT_OF_SCOPE.md
                    Loaded after classification. NOT in .claude/skills/.
app/core/           Core loop — classifier.py (Haiku), composer.py (Sonnet), retriever.py
app/verification/   Verification loop — policy_checker.py (blocks), structural_evals.py (scores)
app/lifecycle/      Lifecycle loop — chat_handler.py, followup_cron.py, autoclose_cron.py
app/learning/       Learning loop — feedback.py, nightly_analysis.py (Opus judge), admin_api.py, eval_gate.py, drift_check.py
app/knowledge/      policy_rules.json, prompts.py, policy_loader.py
app/observability/  arize_client.py
app/db/             models.py, seed.py, supabase_client.py
frontend/           index.html, app.js, style.css (served as FastAPI static files)
```

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

## Loop boundaries — three tiers

**✅ Always (no approval needed)**
- Run policy_checker on every composed response before returning it
- Load the skill file after classification, before composition
- Write to eval_queue (trace_data) on every successful chat turn, with model_id
- Update policy_rules.json AND the relevant skill file together, atomically

**⚠️ Ask first (needs approval)**
- Add a new skill category (requires new classifier label, new skill file, new tests)
- Change model routing (Haiku/Sonnet/Opus roles)
- Modify Supabase table schema
- Adjust the ₹50,000 escalation threshold or retry limit

**🚫 Never**
- Core loop writes to eval_queue (Learning loop domain only)
- Verification loop calls the Anthropic API (must stay deterministic)
- Learning loop auto-applies a policy suggestion (human gate in admin_api.py is mandatory)
- Cron jobs bypass Verification loop verification
- Remove or edit existing tests to make them pass

## Demo done-condition (end-to-end)
The demo is working when ALL of the following are true:
1. `POST /chat` with user USR001 and message "my Swiggy payment is stuck" returns a JSON card with `category: UPI_FAILURE`, a TXN ID in `reference`, and no forbidden phrases
2. The response passes all 7 policy checks (no failures logged)
3. A `trace_data` row appears in Supabase `eval_queue` within seconds, containing `model_id`
4. The Arize dashboard shows a `chat_turn` span with `classify` and `compose` child spans
5. `POST /feedback` with `helpful_score: 1` writes to `eval_queue` as `user_feedback`
6. `GET /admin/metrics` (Bearer ADMIN_API_KEY) returns `policy_pass_rate` > 0

## Stack decisions
- FastAPI not Flask: async-native, Pydantic validation built in, APScheduler fits the lifespan hook cleanly
- APScheduler not cron: single process for local demo; cron jobs live inside the FastAPI lifespan, no extra infra
- Skills not system prompt: progressive disclosure keeps Sonnet context lean; skill updates are isolated to one file
- policy_rules.json not .py: JSON diffs are readable and safe to apply without executing code; Learning loop writes JSON

## Policy rule change process
Always update policy_rules.json AND the relevant skill file together. Never one without the other.
Admin approval in Learning loop writes both atomically. policy_versions records old_content and new_content for rollback.

## Eval discipline
- Code-based evals (policy_checker.py, structural_evals.py): objective checks only — schema, format, forbidden phrases, citations
- Opus LLM judge: resolution quality and honest uncertainty only. Runs on flagged traces only, never every trace
- Tone signal comes from user free text keyword matching, not LLM judge
- Timeline accuracy tracked by deterministic counter, not LLM

## Model routing
- Haiku: intent classification only. One call per turn. Never composition.
- Sonnet: response composition and nightly analysis suggestions. Never classification or judging.
- Opus: LLM judge only. Never composition. Reduces self-evaluation bias when judging Sonnet output.
- Never swap models between roles without updating this file.

## Session persistence
In-flight ticket state lives in Supabase `tickets` table. If the FastAPI process restarts mid-conversation, the next request calls `_get_or_create_ticket` which resumes the existing open ticket by user_id. No in-memory state is required between requests. Cron jobs are idempotent — `followup_cron` selects open tickets where `resolution_deadline < now`, `autoclose_cron` selects open/pending tickets where `resolution_deadline` is more than 48 hours in the past.

## One rule per real failure
Every constraint in policy_checker.py has an inline comment: # Failure: <what happened> | Rule: <rule_id>
If you add a rule without a documented failure mode, it does not belong in policy_checker.py.
