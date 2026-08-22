# Question Domain and API

PBI 1.3 makes `Question` Privexa's first-class representation of “the client needs an answer.” It
is a small client-owned professional object, not a ticket, answer, Evidence item, Decision, Action,
or AI analysis record.

## Authoritative state

A Question stores the exact accepted `title`, `question_text`, optional `context`, and lifecycle
`status`. The PBI 1.1 kernel supplies UUID identity, Firm and Client ownership, Membership-derived
creator/updater provenance, timezone-aware timestamps, and optimistic `version`. Firm, Client,
actor, status, timestamps, and version cannot be supplied through create or generic update bodies.

Question content accepts Unicode, punctuation, statutory references, URLs, and line breaks. The
application rejects blank or over-limit values without trimming or semantically rewriting accepted
content. No AI subsystem participates in Question creation, retrieval, update, listing, or
lifecycle operations.

## Lifecycle

Every Question begins `OPEN`. Status is changed only through explicit commands:

```text
OPEN -> RESOLVED -> CLOSED
  ^        |          |
  +--------+----------+
        explicit reopen
```

`OPEN -> CLOSED` and `CLOSED -> RESOLVED` are invalid. Repeating an already-achieved command with
the current version is an idempotent no-op. Content can be edited only while `OPEN`; a resolved or
closed Question must first be reopened.

## API

```text
POST  /v1/clients/{client_id}/questions
GET   /v1/clients/{client_id}/questions
GET   /v1/clients/{client_id}/questions/{question_id}
PATCH /v1/clients/{client_id}/questions/{question_id}
POST  /v1/clients/{client_id}/questions/{question_id}/resolve
POST  /v1/clients/{client_id}/questions/{question_id}/close
POST  /v1/clients/{client_id}/questions/{question_id}/reopen
```

Updates and lifecycle commands require `expected_version`. Lists use fixed newest-first ordering,
offset pagination with a default of 50 and maximum of 100, and an optional exact status filter.

## Authorization and isolation

Question routes use the server-selected active Client and the action-specific `question.read`,
`question.create`, or `question.update` Permission. Owners and admins have all three permissions.
Assigned consultants can read and mutate Questions; assigned reviewers and read-only users can
read only.

Every repository query includes Firm and Client predicates. PostgreSQL independently enforces
forced RLS through transaction-local validated Firm, Client, and Membership settings. Runtime
grants expose no hard delete and no updates to identity, ownership, creator, or creation time.
Cross-client, cross-Firm, inactive, and unavailable Questions use the same generic 404 response.

## Events and observability

Successful commits emit `question.created`, `question.updated`, `question.resolved`,
`question.closed`, or `question.reopened` domain events. Rollbacks discard pending events. The
post-commit operational representation includes IDs, actor provenance, correlation, event type,
and payload field names, but never Question title, text, context, or payload values. A future shared
append-only audit store may persist the existing event envelope without changing Question.

Question service operations use the PBI 1.1 allowlisted domain spans. Question content is never a
log, span, or metric attribute.
