-- Payment Resolution Agent — Supabase Schema
-- Reference definition matching the actual Supabase tables.

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    account_type TEXT DEFAULT 'savings'
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    merchant TEXT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    channel TEXT,
    notes TEXT,
    initiated_at TIMESTAMPTZ NOT NULL,
    settled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    session_id TEXT,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    resolution_deadline TIMESTAMPTZ,
    conversation_json JSONB DEFAULT '[]',
    unclear_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval_queue (
    eval_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    ticket_id UUID REFERENCES tickets(ticket_id),
    response_text TEXT,
    classification TEXT,
    policy_checks_json JSONB,
    helpful_score INTEGER,
    failure_category TEXT,
    failure_freetext TEXT,
    resolution_confirmed BOOLEAN,
    timeline_accurate TEXT,
    llm_judge_score JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS policy_suggestions (
    suggestion_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    failure_pattern TEXT NOT NULL,
    affected_layer TEXT NOT NULL,
    suggested_fix_text TEXT NOT NULL,
    confidence TEXT,
    source_trace_ids TEXT[] DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT
);

CREATE TABLE IF NOT EXISTS policy_versions (
    version_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    version_number INTEGER NOT NULL,
    rules_json JSONB,
    affected_category TEXT NOT NULL,
    old_content TEXT,
    new_content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    change_reason TEXT,
    suggested_by TEXT,
    suggestion_id UUID REFERENCES policy_suggestions(suggestion_id)
);

-- Grants — required for service_role key used in the app
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- Indexes for frequent query patterns
CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON tickets(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_resolution_deadline ON tickets(resolution_deadline, status);
CREATE INDEX IF NOT EXISTS idx_eval_queue_ticket ON eval_queue(ticket_id);
CREATE INDEX IF NOT EXISTS idx_eval_queue_created ON eval_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_policy_suggestions_status ON policy_suggestions(status);
