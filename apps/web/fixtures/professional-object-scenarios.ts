import type { SafeProblem } from "@/lib/api/problem-details";
import {
  actionFixture,
  decisionFixture,
  evidenceFixture,
  fixtureHistory,
  fixtureLargeRelatedItems,
  fixtureLongHistory,
  fixtureMixedRelatedItems,
  fixtureStatuses,
  professionalObjectFixture,
} from "@/fixtures/professional-objects";
import type { ProfessionalObjectPageViewModel } from "@/lib/professional-objects/view-model";

export type ProfessionalObjectScenarioName =
  | "evidence"
  | "decision"
  | "action-empty"
  | "long-content"
  | "read-only"
  | "archived"
  | "unknown-status"
  | "section-error"
  | "section-loading"
  | "action-forbidden"
  | "action-failure"
  | "large-lists"
  | "unsafe-text"
  | "optimistic-success"
  | "optimistic-failure"
  | "version-conflict"
  | "loading"
  | "object-error"
  | "permission-denied";

export type ProfessionalObjectScenario =
  | {
      kind: "object";
      name: ProfessionalObjectScenarioName;
      label: string;
      page: ProfessionalObjectPageViewModel;
      body: { heading: string; paragraphs: string[] };
      optimisticOutcome?: "success" | "failure" | "conflict";
      actionOutcome?: "success" | "failure";
    }
  | { kind: "loading"; name: "loading"; label: string }
  | { kind: "object_error"; name: "object-error"; label: string; problem: SafeProblem }
  | { kind: "permission_denied"; name: "permission-denied"; label: string };

const commonBody = {
  heading: "Professional content",
  paragraphs: [
    "This restrained fixture demonstrates where a later domain PBI supplies its authoritative professional interface.",
    "The common shell does not interpret, edit, or transform this content.",
  ],
};

const longTitle =
  "Assessment of the customer-support transcription, quality analytics, training-data reuse, cross-border access, and retention arrangements documented for the consumer lending service";

export const professionalObjectScenarios: Record<
  ProfessionalObjectScenarioName,
  ProfessionalObjectScenario
> = {
  evidence: { kind: "object", name: "evidence", label: "Normal evidence", page: evidenceFixture, body: commonBody },
  decision: { kind: "object", name: "decision", label: "Decision with relationships", page: decisionFixture, body: commonBody },
  "action-empty": { kind: "object", name: "action-empty", label: "Empty related and history", page: actionFixture, body: commonBody },
  "long-content": {
    kind: "object",
    name: "long-content",
    label: "Long content",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000004",
      type: "question",
      title: longTitle,
      description:
        "This fixture exercises realistic professional copy, long names, wrapping behavior, and a relationship list that remains readable without becoming a dashboard.",
      inspector: { related: { state: "ready", data: fixtureMixedRelatedItems } },
    }),
    body: {
      heading: "Question under review",
      paragraphs: [
        "Does the proposed reuse of customer-support conversations remain compatible with the purpose communicated to customers, and what additional conditions would be required before the professional can reach a defensible decision?",
        "The eventual Question interface can replace this body without changing workspace context, provenance, relationships, responsive behavior, or failure handling.",
      ],
    },
  },
  "read-only": {
    kind: "object",
    name: "read-only",
    label: "Read-only",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000005",
      type: "obligation",
      title: "Maintain source-backed records of processing purposes and retention",
      readOnly: true,
    }),
    body: commonBody,
  },
  archived: {
    kind: "object",
    name: "archived",
    label: "Archived",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000006",
      type: "processing_activity",
      title: "Legacy support quality reporting",
      archived: true,
    }),
    body: commonBody,
  },
  "unknown-status": {
    kind: "object",
    name: "unknown-status",
    label: "Unknown future status",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000007",
      type: "evidence",
      title: "Support data-flow reconciliation notes",
      status: fixtureStatuses.unknown,
    }),
    body: commonBody,
  },
  "section-error": {
    kind: "object",
    name: "section-error",
    label: "Section error",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000008",
      type: "decision",
      title: "Conditional approval of support analytics",
      inspector: {
        related: {
          state: "error",
          problem: {
            code: "RELATED_ITEMS_UNAVAILABLE",
            detail: "Related records could not be loaded. The decision remains available.",
            requestId: "70000000-0000-4000-8000-000000000001",
          },
        },
        history: { state: "ready", data: fixtureHistory },
      },
    }),
    body: commonBody,
  },
  "section-loading": {
    kind: "object",
    name: "section-loading",
    label: "Section loading",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000009",
      type: "action",
      title: "Confirm the vendor deletion schedule",
      inspector: { related: { state: "loading" }, history: { state: "loading" } },
    }),
    body: commonBody,
  },
  "action-forbidden": {
    kind: "object",
    name: "action-forbidden",
    label: "Action forbidden",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000010",
      type: "decision",
      title: "Conditional approval of support analytics",
      status: fixtureStatuses.approved,
      actions: [
        {
          id: "edit",
          label: "Edit",
          kind: "command",
          emphasis: "primary",
          availability: "available",
        },
        {
          id: "publish",
          label: "Publish as precedent",
          kind: "command",
          emphasis: "secondary",
          availability: "denied",
          disabledReason: "Only authorised firm reviewers can publish precedent.",
        },
      ],
    }),
    body: commonBody,
  },
  "action-failure": {
    kind: "object",
    name: "action-failure",
    label: "Action failure",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000011",
      type: "action",
      title: "Confirm vendor deletion controls",
      status: fixtureStatuses.open,
    }),
    body: commonBody,
    actionOutcome: "failure",
  },
  "large-lists": {
    kind: "object",
    name: "large-lists",
    label: "Large related and history lists",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000012",
      type: "evidence",
      title: "Stress fixture for a substantial set of relationships and history entries",
      inspector: {
        related: { state: "ready", data: fixtureLargeRelatedItems },
        history: { state: "ready", data: fixtureLongHistory },
      },
    }),
    body: commonBody,
  },
  "unsafe-text": {
    kind: "object",
    name: "unsafe-text",
    label: "Unsafe text",
    page: professionalObjectFixture({
      id: "60000000-0000-4000-8000-000000000013",
      type: "evidence",
      title: '<script>alert("xss")</script>',
      description: '<img src=x onerror=alert("unsafe")> must remain visible as plain text.',
    }),
    body: {
      heading: "Untrusted source text",
      paragraphs: ['<script>alert("body")</script>', '<img src=x onerror=alert("body")>'],
    },
  },
  "optimistic-success": {
    kind: "object",
    name: "optimistic-success",
    label: "Optimistic success",
    page: evidenceFixture,
    body: commonBody,
    optimisticOutcome: "success",
  },
  "optimistic-failure": {
    kind: "object",
    name: "optimistic-failure",
    label: "Optimistic rollback",
    page: evidenceFixture,
    body: commonBody,
    optimisticOutcome: "failure",
  },
  "version-conflict": {
    kind: "object",
    name: "version-conflict",
    label: "Version conflict",
    page: evidenceFixture,
    body: commonBody,
    optimisticOutcome: "conflict",
  },
  loading: { kind: "loading", name: "loading", label: "Object loading" },
  "object-error": {
    kind: "object_error",
    name: "object-error",
    label: "Object error",
    problem: {
      code: "PROFESSIONAL_OBJECT_UNAVAILABLE",
      detail: "This professional record could not be loaded right now.",
      requestId: "70000000-0000-4000-8000-000000000002",
      status: 503,
    },
  },
  "permission-denied": {
    kind: "permission_denied",
    name: "permission-denied",
    label: "Permission denied",
  },
};

export const professionalObjectScenarioNames = Object.keys(
  professionalObjectScenarios,
) as ProfessionalObjectScenarioName[];

export function isProfessionalObjectScenarioName(
  value: string,
): value is ProfessionalObjectScenarioName {
  return Object.prototype.hasOwnProperty.call(professionalObjectScenarios, value);
}
