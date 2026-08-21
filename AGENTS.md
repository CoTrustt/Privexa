# AGENTS.md — Privexa Engineering Instructions

> This file defines the default engineering rules for AI coding agents working in the Privexa repository.
> Apply these instructions to the entire repository unless a more specific `AGENTS.md` exists in a subdirectory.
> If repository code and this file conflict, preserve production behavior and flag the conflict rather than silently redesigning the system.

---

## 1. Product mission

Privexa is an AI-native Privacy Consultant Operating System for Indian privacy professionals and DPO consultancies.

The product should help a privacy professional:

1. understand a client's privacy environment,
2. maintain a living RoPA,
3. conduct and document DPIAs,
4. investigate privacy questions,
5. reach a defensible professional decision,
6. turn decisions into actions,
7. preserve the evidence and reasoning trail,
8. supervise more client engagements without diluting human judgement.

The product promise is:

**Ask. Decide. Prove.**

The operating principle is:

**AI investigates and prepares. Humans exercise professional judgement.**

Do not turn Privexa into a generic GRC suite, document repository, chatbot wrapper, workflow builder, or collection of disconnected compliance modules.

---

## 2. Product architecture: non-negotiable defaults

Privexa starts as a **modular monolith with workers**, not a microservice estate.

Preferred architecture:

- Web: Next.js + React + TypeScript
- UI: Tailwind CSS + shadcn/ui + Radix primitives
- Forms: React Hook Form + Zod + JSON Schema where dynamic forms are required
- Rich text: Tiptap
- API/backend: Python + FastAPI
- Validation: Pydantic
- ORM: SQLAlchemy
- Migrations: Alembic
- Primary database: PostgreSQL
- Flexible structured data: PostgreSQL JSONB
- Tenant isolation: PostgreSQL Row-Level Security
- Semantic retrieval: pgvector
- Keyword retrieval: PostgreSQL full-text search
- Graph V1: typed relationship tables in PostgreSQL
- Object storage: S3-compatible storage
- Authentication: Stytch B2B
- Firm-level roles: Stytch RBAC
- Client-level authorization: application policy + PostgreSQL RLS
- AI abstraction: internal `ai-gateway`
- Model routing: OpenRouter behind `ai-gateway`
- Agents: bounded Python agents
- Durable workflows: Temporal only when durable wait/retry/escalation semantics are actually required
- Billing: Razorpay behind an application abstraction
- Product analytics: PostHog
- Business analytics: PostgreSQL + dbt Core
- Observability: OpenTelemetry + Prometheus + Grafana + Sentry
- Runtime: Docker + Kubernetes / Red Hat OpenShift
- Infrastructure as Code: Terraform
- CI/CD: GitHub Actions
- Backend testing: Pytest
- Frontend testing: Vitest
- E2E testing: Playwright
- AI evaluation: golden datasets + prompt/version registry + regression harness

### Do not introduce without an explicit architecture decision

Do not add any of the following merely because they are convenient:

- independently deployed microservices,
- Neo4j or another graph database,
- Pinecone or another dedicated vector database,
- Elasticsearch/OpenSearch,
- MongoDB,
- Kafka,
- LangChain/LlamaIndex or another large AI framework,
- a second authentication system,
- direct model-provider SDK calls outside `ai-gateway`,
- a second workflow engine,
- a second billing provider embedded directly in domain code.

If a new dependency is genuinely required, document why the existing stack is insufficient.

---

## 3. Core domain model

Privexa's primary privacy-domain concepts are:

- `Firm`
- `User`
- `ClientWorkspace`
- `ClientMemory`
- `Question`
- `ProcessingActivity`
- `RoPA`
- `Evidence`
- `Obligation`
- `DPIA`
- `Opinion`
- `Decision`
- `Action`
- `Assessment`
- `Case`
- `FirmInterpretation`
- `FirmPrecedent`
- `AuditEvent`

The five foundational work objects remain:

**Question → Evidence → Decision → Action → Obligation**

`ProcessingActivity` is also foundational because it supports RoPA, DPIA, impact analysis, evidence relationships, and regulatory reasoning.

### Domain rules

1. A `Question` may affect one or more `ProcessingActivity` records.
2. A RoPA is a professional view over authoritative `ProcessingActivity` data.
3. A DPIA must reference the relevant processing activity or activities.
4. An `Opinion` is analytical work; a `Decision` is the human-approved professional outcome.
5. AI output is never itself a `Decision`.
6. A `Decision` may create one or more `Action` records.
7. Evidence may support, contradict, supersede, or relate to facts, controls, processing activities, DPIAs, Opinions, Decisions, or Actions.
8. Every material AI-supported conclusion must preserve source provenance.
9. Client-private knowledge must never become Firm Knowledge automatically.
10. Cross-client analytics must use approved aggregated or abstracted data, never unrestricted raw client context.

---

## 4. RoPA is first-class, not a spreadsheet clone

RoPA is a core Privexa capability.

Treat it as a **living processing map**, not a static annual compliance table.

A processing activity should be able to capture, as appropriate:

- business activity/name,
- purpose,
- Data Principal/data-subject categories,
- personal-data categories,
- sensitive/high-impact indicators where applicable,
- source of data,
- processors/recipients,
- systems or locations,
- transfers/geography,
- retention,
- safeguards/controls,
- legal/regulatory obligations,
- supporting evidence,
- related DPIAs,
- related Decisions,
- open Actions,
- review state,
- provenance and last verified date.

### RoPA AI behavior

AI may:

- discover candidate processing activities from evidence,
- suggest missing fields,
- identify contradictions,
- identify a processor or purpose not reflected in the RoPA,
- propose updates from new Questions, Evidence, DPIAs, Decisions, or Actions,
- explain why an update may be needed.

AI must not silently rewrite the authoritative RoPA.

Material RoPA changes require explicit user acceptance or a clearly defined approved rule.

### RoPA UI behavior

Default to a readable activity-oriented view.

Do not default to an enormous spreadsheet.

A table view may exist for review/export, but the primary UI should emphasize:

- processing activity,
- purpose,
- people/data involved,
- status,
- unresolved issues,
- evidence quality,
- linked DPIA/Decision state.

Do not invent arbitrary “RoPA compliance scores” unless a clearly defined methodology exists.

---

## 5. DPIA is first-class professional reasoning

DPIA is not merely a questionnaire.

A DPIA should reuse known facts from:

- Client Memory,
- RoPA,
- Processing Activities,
- Evidence,
- Obligations,
- Firm Interpretations,
- previous Decisions,
- relevant precedent.

Do not ask the user for information Privexa already possesses and can source reliably.

A DPIA should support, where appropriate:

- context and purpose,
- affected processing activities,
- personal data and Data Principals,
- processors/recipients,
- necessity,
- proportionality,
- potential privacy harms,
- existing safeguards,
- gaps,
- additional measures,
- residual risks,
- assumptions,
- evidence,
- applicable obligations,
- final professional Decision,
- resulting Actions.

### DPIA AI behavior

AI may:

- prepopulate source-backed facts,
- identify missing information,
- propose risk scenarios,
- analyse necessity/proportionality,
- evaluate safeguards,
- propose additional measures,
- draft findings,
- identify issues requiring human judgement.

AI must not:

- accept residual risk,
- approve high-risk processing,
- sign/finalize the DPIA,
- represent that an AI recommendation is the DPO's Decision.

The final DPIA decision is human.

---

## 6. AI architecture

All model usage must go through the internal `ai-gateway`.

Never call OpenRouter, OpenAI, Anthropic, Google, or another provider directly from feature/domain code.

Conceptually, feature code should request a capability:

```python
result = await ai_gateway.run(
    task="dpia_risk_analysis",
    tenant_context=tenant_context,
    sensitivity="high",
    input=data,
)
```

Feature code should not select a model by provider name.

The AI gateway owns:

- model/provider allowlists,
- sensitivity rules,
- Zero Data Retention requirements,
- redaction policy,
- model capability selection,
- cost ceilings,
- retry/fallback policy,
- timeout policy,
- tracing,
- prompt/version selection,
- audit metadata,
- model-specific normalization.

### Prefer structured output

For classifications, extraction, relationships, recommendations, gaps, RoPA updates, Actions, and agent tool calls:

- define Pydantic schemas,
- validate every model response,
- reject malformed output,
- avoid parsing free-form prose when a structured response is possible.

### Model selection principle

Use the cheapest model class that reliably performs the task.

Typical categories:

- small/cheap model: classification, tagging, field extraction, simple summarization,
- embeddings: retrieval,
- reranker: retrieval quality,
- vision model: screenshots, scans, tables, diagrams,
- strong reasoning model: DPIA reasoning, conflicting evidence, novel privacy questions, incidents,
- deterministic software: permissions, deadlines, arithmetic, billing, workflow state, entitlements, SLA clocks.

**Use AI where ambiguity exists. Use software where truth is deterministic.**

---

## 7. Agent authority model

Agents are internal implementation details. Do not expose an “Agents” product menu.

Authority levels:

### Level 0 — Read
May retrieve and analyse authorized context.

### Level 1 — Prepare
May create drafts, proposed fields, proposed relationships, proposed Actions, proposed RoPA changes, proposed recommendations.

### Level 2 — Request
May send bounded requests for routine information when explicitly enabled by product policy.

### Level 3 — Execute workflow
May perform approved routine workflow actions such as reminders, evidence requests, scheduling reviews, and deterministic escalations.

### Level 4 — Professional judgement
**Human only.**

Agents must never:

- issue final DPO Opinions,
- approve high-risk processing,
- accept material residual risk,
- close serious privacy incidents,
- override client isolation,
- change permissions,
- change billing,
- publish Firm Precedent,
- represent the client before an authority,
- convert assumptions into facts without validation.

---

## 8. Expected agent roles

Use bounded agents where appropriate. Prefer composable capabilities over giant autonomous agents.

Possible roles include:

- Intake Agent
- Document Intake Agent
- Memory Assistant
- RoPA Mapping Agent
- RoPA Quality Agent
- Context Agent
- Evidence Agent
- Regulatory Retrieval Agent
- Reasoning Orchestrator
- Gap Agent
- Interview Agent
- DPIA Preparation Agent
- DPIA Reasoning Agent
- Opinion Copilot
- Consultant/Recommendation Agent
- Action Extraction Agent
- Follow-through Agent
- Onboarding Agent
- Judgement Prioritization Agent
- Briefing Agent
- Change Significance Agent
- RoPA Maintenance Agent
- Assessment Agent
- Case Agent
- Firm Knowledge Agent
- Precedent Abstraction Agent
- Regulatory Impact Agent
- Executive Briefing Agent
- Practice Analyst Agent

Each agent should:

1. have a narrowly defined purpose,
2. use explicit tools,
3. receive tenant-scoped context,
4. have a defined authority level,
5. return structured output when possible,
6. emit audit events,
7. fail safely,
8. be independently testable,
9. have evaluation fixtures where reasoning quality matters.

Do not create an agent when a normal function, database query, or rules engine is sufficient.

---

## 9. Human judgement and trust grammar

Privexa must visually and semantically distinguish:

- `LAW`
- `FIRM_POSITION`
- `CLIENT_FACT`
- `ASSUMPTION`
- `RECOMMENDATION`
- `HUMAN_DECISION`

Do not collapse these into one AI-generated narrative.

Any material recommendation should make clear:

- what facts were used,
- what evidence supports them,
- what law/regulation was retrieved,
- what firm interpretation was applied,
- what remains an assumption,
- what Privexa recommends,
- what the human ultimately decided.

Never expose hidden chain-of-thought.

Expose source-backed findings, issues examined, uncertainty, and rationale summaries.

---

## 10. Tenant isolation and privacy rules

Every client-scoped table must be designed with tenant isolation in mind.

Default expectation:

`Firm -> ClientWorkspace -> domain records`

### Required controls

- Stytch authenticates the member.
- Application authorization determines allowed operation.
- PostgreSQL RLS enforces row access.
- Retrieval queries must be tenant-scoped before ranking.
- Vector search must never search an unrestricted cross-client pool.
- Object-store paths must be client/tenant scoped.
- AI requests must contain tenant context.
- AI tools must enforce tenant context server-side.
- Audit events must record firm/client scope.
- Background jobs and Temporal workflows must preserve tenant scope.

Never rely solely on a user-supplied `client_id`.

Do not put authorization only in the frontend.

Do not create “admin” bypasses casually.

Cross-client access is exceptional and must be explicit, authorized, and auditable.

---

## 11. Client Knowledge vs Firm Knowledge

There are three knowledge layers:

### Platform Knowledge
Public law, regulation, generic methodology, approved industry material.

### Firm Knowledge
Firm interpretations, playbooks, approved precedent, approved templates.

### Client Knowledge
Client Memory, Evidence, Questions, RoPA, DPIAs, Decisions, Actions, Cases.

Client Knowledge is strictly isolated.

Nothing moves from Client Knowledge to Firm Knowledge automatically.

Promotion to Firm Knowledge must:

1. be explicit,
2. remove client-identifying information,
3. abstract the reusable principle,
4. pass privacy/redaction checks,
5. require authorized human approval,
6. be audited.

---

## 12. UX principles

Privexa should reduce professional cognitive load.

Every screen should answer one or more of:

1. What happened?
2. What does it mean?
3. What needs my judgement?
4. What happens next?

### Required UX behavior

- Never ask a question Privexa already has a reliable answer to.
- Prefer progressive disclosure.
- Recommendation first; reasoning second; evidence/source detail on demand.
- Preserve manual fallback for critical workflows.
- Convert uncertainty into a next action.
- Keep human judgement explicit.
- Use ordinary language in the client portal.
- Avoid forcing clients to understand internal privacy workflow terminology.
- Surface exceptions, not routine machine activity.
- Keep autonomous activity inspectable and pausable.

---

## 13. UI principles

Privexa should feel calm, precise, professional, editorial, and premium.

### Visual rules

- One dominant purpose per screen.
- Strong typographic hierarchy.
- Use whitespace before adding borders.
- Neutral surfaces dominate.
- Semantic color only when it communicates state/consequence.
- Avoid decorative gradients and “AI magic” styling.
- No AI mascot.
- No robot avatar.
- No glowing AI buttons.
- No generic “AI is thinking” theatre.
- Use meaningful processing stages instead of generic spinners.
- Human Decisions must be visually distinct from AI recommendations.
- Avoid dashboard confetti.
- Avoid arbitrary donut charts.
- Avoid fake “compliance scores”.
- Avoid dense enterprise tables as the default when a clearer activity view works.
- Use tables when comparison or review density genuinely requires them.
- Keep client UI simpler and less dense than consultant UI.
- Design mobile primarily for review, briefing, approval, and client requests.

### Navigation target

Global navigation should remain small:

- Home
- Clients
- Ask Privexa
- Firm Brain
- Intelligence
- Settings

Within a client, first-class professional surfaces may include:

- Overview
- RoPA
- DPIAs
- Evidence
- Decisions
- Actions

Do not turn every backend module into navigation.

---

## 14. Backend engineering conventions

Keep domain logic outside route handlers.

Recommended flow:

`route -> application/service -> domain/policy -> persistence`

Route handlers should:

- authenticate,
- validate,
- call an application service,
- return typed responses.

Domain/application services should own:

- authorization checks,
- state transitions,
- business rules,
- orchestration,
- audit emission.

Persistence code should not contain product policy.

### API rules

- Use explicit request/response schemas.
- Avoid returning raw ORM objects.
- Use stable identifiers.
- Make state transitions explicit.
- Prefer idempotent mutation semantics where feasible.
- Validate client/tenant ownership server-side.
- Return structured domain errors.
- Never leak model/provider errors directly to end users.

---

## 15. Frontend engineering conventions

Use TypeScript strictly.

Prefer server-derived truth over duplicated client state.

Components should be:

- small,
- composable,
- accessible,
- typed,
- domain-aware only where necessary.

Prefer shared primitives for:

- status,
- provenance,
- evidence references,
- human-vs-AI authorship,
- decision states,
- object inspectors,
- activity timelines,
- tenant context.

Avoid duplicating business rules in React.

Do not hide authorization logic only in UI rendering.

For forms:

- use React Hook Form,
- use Zod validation,
- derive dynamic forms from explicit schemas where possible.

For DPO Opinions and narrative professional content:

- use Tiptap,
- preserve structured source/provenance references outside raw prose.

---

## 16. Database and migration rules

PostgreSQL is the system of record.

### Required practices

- use Alembic migrations,
- never edit an applied migration in place,
- add indexes intentionally,
- model tenant scope explicitly,
- add RLS policies to client-scoped tables,
- test RLS behavior,
- prefer relational columns for stable/queryable domain truth,
- use JSONB for extensible extracted/AI metadata,
- do not hide core domain data in opaque JSON blobs,
- use pgvector only for semantic retrieval,
- keep authoritative values outside embeddings.

### Graph V1

Use typed relationship tables.

Example concepts:

- `evidence SUPPORTS control`
- `evidence CONTRADICTS claim`
- `decision BASED_ON evidence`
- `action IMPLEMENTS decision`
- `processing_activity SUBJECT_TO obligation`
- `dpia ASSESSES processing_activity`

Do not add a dedicated graph database without demonstrated need.

---

## 17. Temporal/workflow rules

Do not use Temporal for ordinary synchronous application logic.

Use Temporal when a workflow must survive:

- long waits,
- retries,
- process restarts,
- external replies,
- reminders,
- scheduled re-checks,
- escalations,
- multi-day/multi-week cases.

Examples:

- wait seven days for evidence,
- remind client,
- wait again,
- escalate,
- pause for human input,
- continue after response.

Workflow state must remain inspectable in Privexa.

LLMs may decide how to phrase a bounded message or interpret a response.

Deterministic workflow code owns:

- timers,
- retry count,
- SLA clocks,
- state transitions,
- escalation thresholds.

---

## 18. Audit and provenance

For every material professional operation, preserve enough information to reconstruct what happened.

Audit important events including:

- Question created,
- Evidence uploaded,
- Evidence interpretation accepted/changed,
- RoPA activity created/changed,
- DPIA created/changed/finalized,
- Opinion created/changed,
- AI recommendation generated,
- human Decision made,
- Action created/completed,
- Firm Knowledge promoted,
- agent external action executed.

For AI calls record, as appropriate:

- task name,
- prompt/template version,
- model capability/class,
- provider/model identifier when policy permits,
- tenant/client scope,
- source object IDs,
- retrieval snapshot/reference,
- output hash,
- policy result,
- human accepted/edited/rejected state,
- latency/cost metadata,
- trace ID.

Do not log raw sensitive prompt content indiscriminately.

---

## 19. Security requirements

Treat privacy-client information as sensitive by default.

Never:

- log secrets,
- log raw tokens,
- put credentials in source,
- expose provider API keys to the browser,
- send unrestricted client datasets to models,
- bypass RLS for convenience,
- mix tenants in cache keys,
- use public object-store buckets,
- store unnecessary sensitive model traces,
- train/evaluate on client data without explicit policy/authorization.

Prefer:

- least privilege,
- server-side authorization,
- encrypted transport,
- managed secret storage,
- KMS-backed encryption,
- tenant-scoped cache/storage keys,
- explicit data-retention policies,
- zero-data-retention provider routes for sensitive model tasks when required.

---

## 20. Testing expectations

Every meaningful change should include the relevant tests.

### Backend

Use Pytest for:

- domain rules,
- authorization,
- RLS behavior where practical,
- API contracts,
- state transitions,
- billing/entitlement rules,
- agent tool authorization,
- workflow logic.

### Frontend

Use Vitest for:

- components,
- interaction logic,
- state behavior,
- schema/form behavior.

### E2E

Use Playwright for critical flows, especially:

1. create client,
2. upload evidence,
3. create/review processing activity,
4. maintain RoPA,
5. ask privacy question,
6. create DPIA,
7. prepare Opinion,
8. human Decision,
9. create/complete Action,
10. verify audit history,
11. client portal information request,
12. tenant-isolation checks.

### AI evaluations

AI features that affect professional work need evaluation fixtures.

At minimum test:

- extraction accuracy,
- unsupported-claim rate,
- source attribution,
- tenant-context isolation,
- gap detection,
- RoPA mapping quality,
- DPIA risk coverage,
- recommendation consistency,
- refusal to make Level-4 Decisions,
- behavior with missing evidence,
- behavior with contradictory evidence.

Never treat “the prompt seems good” as adequate QA.

---

## 21. Definition of done

A feature is not done because the UI renders.

Before declaring completion, check:

### Product
- Does this solve a clear consultant/client job?
- Is it consistent with Ask → Decide → Prove?
- Does it preserve human judgement?

### Architecture
- Is it inside the modular monolith unless separation is justified?
- Did we avoid unnecessary infrastructure/dependencies?
- Are domain boundaries clear?

### Security
- Is server-side authorization present?
- Is tenant scope enforced?
- Is RLS correct where required?
- Are files/retrieval/model context tenant-scoped?

### AI
- Does the model call go through `ai-gateway`?
- Is structured output used where appropriate?
- Are source/provenance and uncertainty preserved?
- Is agent authority bounded?
- Is there a safe manual fallback?
- Are deterministic facts kept outside LLM control?
- Are relevant evals present?

### UX/UI
- Is there one dominant action?
- Can unnecessary controls be removed?
- Does the user understand what needs judgement?
- Are AI recommendation and human Decision visually distinct?
- Is client-facing language ordinary and concise?

### Quality
- Tests pass.
- Types pass.
- Migrations are safe.
- Audit events are emitted.
- Observability is adequate.
- Documentation is updated when behavior or architecture changes.

---

## 22. How coding agents should work in this repository

Before changing code:

1. Read this file.
2. Inspect the existing repository structure.
3. Read any more-specific `AGENTS.md` in the target subtree.
4. Identify the existing module responsible for the feature.
5. Reuse existing patterns before introducing new abstractions.
6. Check tenant/security implications.
7. Check AI-gateway implications if models are involved.
8. Check audit/provenance requirements.
9. Check RoPA/DPIA impact if processing facts or privacy decisions are involved.

While coding:

- make the smallest coherent change,
- preserve compatibility unless the task requires a breaking change,
- avoid unrelated refactors,
- do not reorganize the repository simply to match an imagined ideal structure,
- avoid “helpful” architecture changes outside task scope,
- do not silently weaken validation or authorization,
- do not hardcode secrets, tenant IDs, model IDs, or customer-specific values,
- write tests alongside behavior.

After coding:

1. run the relevant project-defined formatter/linter/typecheck,
2. run targeted tests,
3. run broader tests when shared/domain code changed,
4. run AI evaluation fixtures when AI behavior changed,
5. summarize:
   - what changed,
   - why,
   - tests run,
   - migrations/config changes,
   - security/tenant considerations,
   - remaining risks.

If a requested implementation conflicts with a non-negotiable rule in this file, do not silently violate the rule. Surface the conflict and choose the safest architecture-compatible implementation possible.

---

## 23. Repository structure guidance

Respect the actual repository structure.

A typical shape may be:

```text
privexa/
├── apps/
│   ├── web/
│   └── api/
├── packages/
│   └── ui/
├── infra/
├── docs/
├── tests/
└── AGENTS.md
```

Within the backend, prefer capability-oriented modules such as:

```text
identity/
access_control/
clients/
questions/
processing_activities/
ropa/
evidence/
obligations/
dpia/
opinions/
decisions/
actions/
client_memory/
regulatory_knowledge/
retrieval/
reasoning/
ai_gateway/
ai_policy/
agents/
workflow/
approvals/
audit/
entitlements/
metering/
billing/
analytics/
```

These are internal capabilities, not independently deployed services.

Do not rename every subsystem with the `Privexa` prefix.

Externally the product is **Privexa**.

Internally use ordinary engineering names.

---

## 24. Final decision heuristic

When uncertain, prefer the implementation that best satisfies this ordering:

1. client data isolation,
2. professional defensibility,
3. human judgement,
4. correctness,
5. simplicity,
6. maintainability,
7. user experience,
8. AI sophistication,
9. infrastructure sophistication.

Privexa should become more intelligent over time without becoming less trustworthy.

**The software may prepare the work. The professional owns the decision.**
