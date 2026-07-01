# Decision: Escalated tickets get fresh tickets on new queries

**Date:** 2026-06-26
**Status:** Active
**Category:** Bug fix / Product

## Context
A user with an old escalated ticket who sends a new, unrelated query was getting routed to the post-escalation flow instead of the classify-retrieve-compose pipeline. This skipped classification entirely, producing empty response cards.

## Decision
`_get_or_create_ticket` no longer reuses escalated tickets for new queries. Only `open` and `pending_confirmation` tickets are reused. Escalated tickets can still be accessed via explicit `ticket_id`.

## Why
Escalated tickets represent a terminal state for a specific issue. New queries deserve fresh classification and resolution, not continuation of a closed conversation path.

## Consequences
- Test added: `test_get_or_create_ticket_does_not_reuse_escalated_ticket`
- Explicit ticket_id parameter still allows viewing escalated ticket history
