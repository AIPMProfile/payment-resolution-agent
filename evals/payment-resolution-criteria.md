# Eval Scoring Criteria: Payment Resolution Agent

**Feature:** AI agent resolving UPI payment failures and savings pot withdrawal issues
**Owner:** Anusha
**Last reviewed:** 2026-06-30
**Baseline:** 0.93 (first full run, 50 cases / 65 turns, 2026-06-28)
**Target:** 0.95
**Kill threshold:** below 0.85, block deployment

## Criteria (10 binary checks)

### 1. Timelines come from policy rules only

PASS: "Reversal expected by 25 Jun 2026 per NPCI Rules."
FAIL: "Your money should be back in about 2 days."

Why: Made-up timelines create false expectations. When a user checks back on day 3 and nothing happened, they escalate — because the agent set the wrong expectation. Policy-backed timelines (NPCI T+5, NEFT batch schedule) are verifiable commitments.

### 2. Every resolution cites the regulation, timeline, and transaction reference

PASS: "₹2,340 debited to Swiggy on 18 Jun. Reversal by 25 Jun per NPCI Rules."
FAIL: "Your recent payment issue will be resolved soon."

Why: Without citation, the user can't verify the response and support can't trace it. The regulation tells the user *why* they'll get their money back. The timeline tells them *when*. The transaction reference confirms the agent is looking at the right issue.

### 3. Correctly identifies the issue type when user types freely

PASS: User types "my Swiggy payment got stuck yesterday" — agent classifies as UPI payment failure and loads the right resolution.
FAIL: User types "my Swiggy payment got stuck yesterday" — agent treats it as a pot withdrawal issue.

Why: When users type instead of selecting a tile, the classifier must map free text to the right category. Wrong classification means the agent gives resolution steps for the wrong problem entirely.

### 4. Refers to the correct transaction, not a made-up or different one

PASS: User asks about a ₹2,340 Swiggy payment — agent retrieves and references that exact transaction.
FAIL: User asks about a ₹2,340 Swiggy payment — agent responds about a ₹500 Amazon payment from last week.

Why: The agent has access to the user's transaction history. If it picks the wrong one, the entire resolution is about someone else's problem. Users notice immediately and lose trust.

### 5. High-risk cases escalate to a human

High-risk definition:
- Transaction amount exceeds ₹50,000
- User sounds angry or frustrated
- User mentions distress (rent, hospital, emergency)
- User explicitly asks for a human or manager

PASS: User says "this is my rent money and I need it urgently" — response escalates to senior colleague with case details shared.
FAIL: User says "this is my rent money and I need it urgently" — response gives standard "reversal by 25 Jun" timeline.

Why: These situations require human judgment. An automated timeline response to someone who can't pay rent tonight is tone-deaf at best, harmful at worst.

### 6. References only information from the knowledge base

PASS: "As per NPCI guidelines, auto-reversal is mandated within 5 business days."
FAIL: "RBI typically processes UPI refunds within 24 hours." (no such policy exists)

Why: Hallucinated policy is worse than no answer — the user acts on false information, then loses trust when it turns out to be wrong. Every factual claim must trace back to the policy knowledge base.

### 7. Asks clarifying question for vague messages, escalates if still unclear

PASS: User says "something wrong with my account" — agent asks "Could you tell me more? Is this about a UPI payment or a savings pot withdrawal?"
FAIL: User says "something wrong with my account" — agent guesses it's a UPI failure and gives a resolution.

PASS (continued): After clarifying, user says "I don't know, just fix it" — agent escalates to a human.
FAIL (continued): After clarifying, user says "I don't know, just fix it" — agent keeps asking more questions.

Why: Guessing wastes the user's time if wrong. But endless clarifying questions are just as bad — if the user can't clarify after one attempt, a human should step in.

### 8. Resolves in under 3 messages

PASS: User reports stuck payment → agent retrieves transaction and responds with resolution → user confirms. Done.
FAIL: Agent asks "which payment?", then "when was it?", then "how much?", then "which app?" before addressing the issue.

Why: The agent has access to the user's transaction history. It should retrieve and match — not interrogate. Each additional message increases abandonment, especially when the user is anxious about their money.

### 9. Never echoes back full account or card numbers

PASS: "I can see the transaction on your account ending ••4242."
FAIL: "Your account 912345678901234 shows a pending debit of ₹2,340."

Why: Full PAN (primary account number) or card numbers in agent responses create a security exposure — the transcript is stored, potentially logged, and visible in support tools. Masked references (last 4 digits) confirm identity without leaking sensitive data.

### 10. First response delivered within 1 second

PASS: User sends message → resolution card appears in under 1 second.
FAIL: User sends message → 4-second spinner before anything appears.

Why: Users with stuck money are already stressed. Every second of waiting amplifies anxiety and signals "this system doesn't work either." In voice agents, 1 second latency causes abandonment — text is more forgiving, but not by much. A slow agent feels broken even if the answer is perfect.

Current state: our pipeline takes ~4-5 seconds (Haiku classify ~1s + Supabase retrieve ~0.3s + Sonnet compose ~3s). This criterion is a failing eval today — which makes it the most important one. Fixes: response streaming, parallel classify+retrieve, prompt caching, or model optimization.

## How to Run

1. Collect the 50 golden dataset cases: `tests/golden_dataset.json`
2. Run each through the agent (or use `pytest tests/test_golden_evals.py -v`)
3. Score each response on all 10 criteria (1 = pass, 0 = fail)
4. Overall score = average (0.00 to 1.00)

## Per-Skill Breakdown

| Skill | Cases | Key risk |
|---|---|---|
| UPI_FAILURE | 20 | Criteria 1, 2 (timeline + regulation), 3 (classification), 4 (right transaction) |
| POT_WITHDRAWAL | 12 | Criterion 5 (high-value escalation — amounts often exceed ₹50K) |
| OUT_OF_SCOPE | 6 | Criterion 6 (must not hallucinate a resolution for unsupported issues) |
| UNCLEAR | 8 | Criterion 7 (clarify once, then escalate) and 8 (resolve quickly) |
| ALL | 50 | Criterion 10 (latency — currently failing, highest priority to fix) |

## When to Update

- New failure mode appears that no criterion catches
- A regulation changes (e.g., NPCI updates T+5 timeline)
- Escalation threshold adjusted (currently ₹50,000)
- Monthly review: first Monday of the month
- Always commit changes with a message explaining what and why

## Revision Log

Tracked in git — `git log --oneline -- evals/payment-resolution-criteria.md`.

| Date | Change | Why | Effect |
|---|---|---|---|
| 2026-06-28 | Initial criteria from policy_checker + structural_evals | 18 binary checks, mostly engineering-level | Baseline 0.93 |
| 2026-06-30 | Distilled to 10 PM-level criteria | Added classification, transaction grounding, clarification flow, latency; removed engineering checks | Sharper, user-facing signal |
