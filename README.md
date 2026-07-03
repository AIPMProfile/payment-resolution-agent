# FinAssist - Payment Resolution Agent

An AI agent that resolves failed and unsettled payments by giving 
users honest, policy-accurate answers when their money is stuck.

Built with a four-loop architecture: agent loop, verification loop, 
event-driven lifecycle, and a human-gated self-improvement loop.


## What it does

- Classifies payment issues and retrieves transaction data 
  deterministically
- Composes regulation-accurate responses grounded in NPCI 
  and NEFT policy rules
- Blocks unsafe responses via a deterministic policy layer 
  before they reach the user
- Tracks tickets until the payment is resolved, not just 
  until the user gets an answer
- Learns from feedback through a nightly eval pipeline where 
  a stronger model grades output and humans approve changes

## Stack

FastAPI, Supabase, Anthropic API, OpenTelemetry + Arize

## Setup

```bash
git clone https://github.com/AIPMProfile/payment-resolution-agent
cd payment-resolution-agent
pip install -r requirements.txt
cp .env.example .env
python -m app.db.seed
uvicorn app.main:app --reload
```

Required keys in `.env`:

```
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
ADMIN_API_KEY=
AUTH_SECRET_KEY=
ARIZE_API_KEY=
ARIZE_SPACE_ID=
```

Run `app/db/supabase_schema.sql` in Supabase before seeding.

Chat: `http://localhost:8000`  
Admin: `http://localhost:8000/admin/?key=YOUR_ADMIN_KEY`
## Tests

```bash
pytest tests/ -v
```

## Known gaps

Transactions table is seeded and static. In production, 
`settled_at` would be populated by Federal Bank webhook on 
NPCI settlement confirmation — the cron and ticket lifecycle 
are built for this integration.
