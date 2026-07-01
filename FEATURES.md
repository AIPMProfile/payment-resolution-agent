# Features

## Agent loop
- Classifies payment issues via intent detection
- Retrieves transaction data deterministically after classification
- Composes policy-grounded responses citing NPCI or NEFT rules
- Handles UPI failures and Pot withdrawal delays

## Verification loop
- Deterministic policy checker blocks unsafe responses before delivery
- 7 policy rules: no guarantee language, no fraud verdicts, 
  mandatory citation, escalation triggers
- Structural evals score response quality and write to Arize
- Retries with violation context, max 2 times before escalation

## Lifecycle loop
- Ticket tracks from first message until payment confirmed resolved
- Auto-closes on Federal Bank settlement confirmation
- Auto-escalates when resolution deadline passes without settlement
- Returning users load open ticket context, not a fresh session

## Learning loop
- Stage 1 feedback writes to Arize span annotations
- Stage 2 feedback writes to eval queue by ticket
- Nightly analysis runs Opus judge on flagged traces only
- Human approval gate — no suggestion auto-applied
- Approved changes commit to skill file and policy rules atomically