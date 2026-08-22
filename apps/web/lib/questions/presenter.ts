import type { ClientSummary } from "@/lib/application-context/types";
import type {
  ProfessionalObjectAction,
  ProfessionalObjectPageViewModel,
  ProfessionalObjectStatus,
} from "@/lib/professional-objects/view-model";

import type { Question, QuestionStatus } from "./contracts";

const statuses: Record<QuestionStatus, ProfessionalObjectStatus> = {
  OPEN: {
    key: "OPEN",
    label: "Open",
    tone: "information",
    description: "This question still needs a professional outcome.",
  },
  RESOLVED: {
    key: "RESOLVED",
    label: "Resolved",
    tone: "success",
    description: "This question has been resolved.",
  },
  CLOSED: {
    key: "CLOSED",
    label: "Closed",
    tone: "neutral",
    description: "This question is closed.",
  },
};

export function presentQuestionStatus(status: QuestionStatus): ProfessionalObjectStatus {
  return statuses[status];
}

function questionActions(status: QuestionStatus, canUpdate: boolean): ProfessionalObjectAction[] {
  if (!canUpdate) return [];
  if (status === "OPEN") {
    return [
      {
        id: "edit",
        label: "Edit",
        kind: "command",
        emphasis: "secondary",
        availability: "available",
      },
      {
        id: "resolve",
        label: "Resolve question",
        kind: "command",
        emphasis: "primary",
        availability: "available",
      },
    ];
  }
  if (status === "RESOLVED") {
    return [
      {
        id: "reopen",
        label: "Reopen question",
        kind: "command",
        emphasis: "secondary",
        availability: "available",
      },
      {
        id: "close",
        label: "Close question",
        kind: "command",
        emphasis: "tertiary",
        availability: "available",
        confirmation: {
          title: "Close this question?",
          description:
            "Closed questions remain available and can be reopened later if more work is needed.",
          confirmLabel: "Close question",
        },
      },
    ];
  }
  return [
    {
      id: "reopen",
      label: "Reopen question",
      kind: "command",
      emphasis: "secondary",
      availability: "available",
    },
  ];
}

export function questionPageViewModel({
  question,
  firmId,
  client,
  canUpdate,
}: {
  question: Question;
  firmId: string;
  client: ClientSummary;
  canUpdate: boolean;
}): ProfessionalObjectPageViewModel {
  return {
    object: {
      id: question.id,
      type: "question",
      title: question.title,
      status: presentQuestionStatus(question.status),
      workspace: { firmId, id: client.id, name: client.display_name },
      createdAt: question.created_at,
      updatedAt: question.updated_at,
      createdBy: {
        membershipId: question.created_by_membership_id,
        displayName: null,
      },
      updatedBy: {
        membershipId: question.updated_by_membership_id,
        displayName: null,
      },
      version: question.version,
      capabilities: canUpdate
        ? { mode: "editable" }
        : { mode: "read_only", explanation: "You can review this question." },
      actions: questionActions(question.status, canUpdate),
    },
    inspector: {
      details: {
        state: "ready",
        data: [
          { id: "created-at", label: "Created", value: { kind: "timestamp", value: question.created_at } },
          { id: "updated-at", label: "Last changed", value: { kind: "timestamp", value: question.updated_at } },
        ],
      },
      related: {
        state: "empty",
        message: "No professional records have been linked to this question yet.",
      },
      history: {
        state: "empty",
        message: "Detailed history is not available for this question yet.",
      },
    },
  };
}
