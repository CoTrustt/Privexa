import { professionalObjectHref } from "@/lib/professional-objects/object-types";
import type {
  ProfessionalActor,
  ProfessionalObjectAction,
  ProfessionalObjectHistoryEntry,
  ProfessionalObjectInspectorViewModel,
  ProfessionalObjectMetadataItem,
  ProfessionalObjectPageViewModel,
  ProfessionalObjectStatus,
  ProfessionalObjectType,
  RelatedProfessionalObject,
} from "@/lib/professional-objects/view-model";

const firmId = "10000000-0000-4000-8000-000000000001";
const clientId = "20000000-0000-4000-8000-000000000001";

export const fixtureWorkspace = {
  firmId,
  id: clientId,
  name: "Apollo Finance",
} as const;

export const fixtureActors = {
  asha: {
    membershipId: "30000000-0000-4000-8000-000000000001",
    displayName: "Asha Rao",
  },
  rohan: {
    membershipId: "30000000-0000-4000-8000-000000000002",
    displayName: "Rohan Mehta",
  },
  unavailable: {
    membershipId: "30000000-0000-4000-8000-000000000003",
    displayName: null,
  },
} satisfies Record<string, ProfessionalActor>;

export const fixtureStatuses = {
  draft: { key: "DRAFT", label: "Draft", tone: "neutral" },
  open: { key: "OPEN", label: "Open", tone: "information" },
  review: { key: "IN_REVIEW", label: "In review", tone: "attention" },
  approved: { key: "APPROVED", label: "Approved", tone: "success" },
  completed: { key: "COMPLETED", label: "Completed", tone: "success" },
  blocked: { key: "BLOCKED", label: "Blocked", tone: "critical" },
  archived: { key: "ARCHIVED", label: "Archived", tone: "neutral" },
  unknown: { key: "AWAITING_RECONCILIATION", label: "Awaiting reconciliation", tone: "neutral" },
} satisfies Record<string, ProfessionalObjectStatus>;

const timestamps = {
  created: "2026-08-12T04:45:00.000Z",
  updated: "2026-08-22T09:20:00.000Z",
  previous: "2026-08-18T11:05:00.000Z",
};

function metadata(
  objectId: string,
  createdBy: ProfessionalActor = fixtureActors.asha,
  updatedBy: ProfessionalActor = fixtureActors.rohan,
): ProfessionalObjectMetadataItem[] {
  return [
    { id: "client", label: "Client", value: { kind: "text", value: fixtureWorkspace.name } },
    { id: "created-by", label: "Created by", value: { kind: "actor", value: createdBy } },
    { id: "created-at", label: "Created", value: { kind: "timestamp", value: timestamps.created } },
    { id: "updated-by", label: "Last changed by", value: { kind: "actor", value: updatedBy } },
    { id: "updated-at", label: "Last changed", value: { kind: "timestamp", value: timestamps.updated } },
    { id: "version", label: "Version", value: { kind: "text", value: "7" } },
    { id: "identifier", label: "Object ID", value: { kind: "identifier", value: objectId } },
  ];
}

const relationshipSeed: Array<{
  type: ProfessionalObjectType;
  title: string;
  label: string;
  status: ProfessionalObjectStatus;
}> = [
  {
    type: "processing_activity",
    title: "Customer support conversation analytics",
    label: "Describes processing",
    status: fixtureStatuses.review,
  },
  {
    type: "obligation",
    title: "Provide clear notice of processing purposes",
    label: "Supports assessment of",
    status: fixtureStatuses.open,
  },
  {
    type: "decision",
    title: "Permit support analytics subject to retention controls",
    label: "Used in",
    status: fixtureStatuses.approved,
  },
  {
    type: "action",
    title: "Confirm deletion schedule with the support platform owner",
    label: "Created follow-up",
    status: fixtureStatuses.open,
  },
];

export const fixtureRelatedItems: RelatedProfessionalObject[] = relationshipSeed.map(
  (item, index) => {
    const id = `40000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
    return {
      id,
      type: item.type,
      title: item.title,
      relationshipLabel: item.label,
      status: item.status,
      href: professionalObjectHref(clientId, item.type, id),
      availability: "available",
    };
  },
);

export const fixtureMixedRelatedItems: RelatedProfessionalObject[] = [
  ...fixtureRelatedItems,
  {
    id: "40000000-0000-4000-8000-000000000005",
    type: "evidence",
    title: "Previous retention schedule",
    relationshipLabel: "Supersedes",
    status: fixtureStatuses.archived,
    availability: "archived",
  },
  {
    id: "40000000-0000-4000-8000-000000000006",
    type: "question",
    title: null,
    relationshipLabel: "Related record",
    availability: "restricted",
  },
  {
    id: "40000000-0000-4000-8000-000000000007",
    type: "evidence",
    title: null,
    relationshipLabel: "Referenced record",
    availability: "unavailable",
  },
];

const stressObjectTypes: ProfessionalObjectType[] = [
  "evidence",
  "decision",
  "action",
  "obligation",
  "processing_activity",
  "question",
];

export const fixtureLargeRelatedItems: RelatedProfessionalObject[] = Array.from(
  { length: 50 },
  (_, index) => {
    const type = stressObjectTypes[index % stressObjectTypes.length];
    const id = `41000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
    return {
      id,
      type,
      title:
        index === 0
          ? "Documented relationship between the customer-support transcription service, analytics configuration, retention schedule, access controls, processor instructions, and the professional decision governing continued use"
          : `Related professional record ${index + 1}`,
      relationshipLabel: index % 2 === 0 ? "Supports" : "Related to",
      status: index % 3 === 0 ? fixtureStatuses.review : fixtureStatuses.open,
      href: professionalObjectHref(clientId, type, id),
      availability: "available",
    };
  },
);

export const fixtureHistory: ProfessionalObjectHistoryEntry[] = [
  {
    id: "50000000-0000-4000-8000-000000000003",
    action: "Status changed to In review",
    description: "The interpretation is ready for professional review.",
    occurredAt: timestamps.updated,
    actor: fixtureActors.rohan,
    version: 7,
  },
  {
    id: "50000000-0000-4000-8000-000000000002",
    action: "Interpretation updated",
    description: "Retention and affected processing references were clarified.",
    occurredAt: timestamps.previous,
    actor: fixtureActors.asha,
    version: 6,
  },
  {
    id: "50000000-0000-4000-8000-000000000001",
    action: "Evidence record created",
    occurredAt: timestamps.created,
    actor: fixtureActors.asha,
    version: 1,
  },
];

export const fixtureLongHistory: ProfessionalObjectHistoryEntry[] = Array.from(
  { length: 20 },
  (_, index) => ({
    id: `51000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    action: index === 0 ? "Professional assessment expanded" : `Record reviewed — step ${20 - index}`,
    description:
      index === 0
        ? "The reviewer documented how the evidence, processing purpose, affected Data Principals, processor access, retention safeguards, and unresolved assumptions influence the professional assessment. The description is intentionally substantial so wrapping and chronology remain understandable under realistic audit conditions."
        : "The fixture records a deterministic review step without presenting it as an authoritative backend audit event.",
    occurredAt: `2026-08-${String(20 - index).padStart(2, "0")}T09:20:00.000Z`,
    actor: index % 5 === 4 ? null : index % 2 === 0 ? fixtureActors.asha : fixtureActors.rohan,
    version: 20 - index,
  }),
);

function inspector(
  objectId: string,
  overrides: Partial<ProfessionalObjectInspectorViewModel> = {},
): ProfessionalObjectInspectorViewModel {
  return {
    details: { state: "ready", data: metadata(objectId) },
    related: { state: "ready", data: fixtureRelatedItems },
    history: { state: "ready", data: fixtureHistory },
    ...overrides,
  };
}

interface ObjectFixtureOptions {
  id: string;
  type: ProfessionalObjectType;
  title: string;
  description?: string;
  status?: ProfessionalObjectStatus;
  readOnly?: boolean;
  archived?: boolean;
  inspector?: Partial<ProfessionalObjectInspectorViewModel>;
  actions?: ProfessionalObjectAction[];
}

export function professionalObjectFixture({
  id,
  type,
  title,
  description,
  status = fixtureStatuses.review,
  readOnly = false,
  archived = false,
  inspector: inspectorOverrides,
  actions,
}: ObjectFixtureOptions): ProfessionalObjectPageViewModel {
  return {
    object: {
      id,
      type,
      title,
      description,
      status: archived ? fixtureStatuses.archived : status,
      workspace: fixtureWorkspace,
      createdAt: timestamps.created,
      updatedAt: timestamps.updated,
      createdBy: fixtureActors.asha,
      updatedBy: fixtureActors.rohan,
      version: 7,
      archivedAt: archived ? timestamps.updated : undefined,
      capabilities: readOnly
        ? {
            mode: "read_only",
            explanation: "You can review this record, but your current access does not allow changes.",
          }
        : { mode: "editable" },
      actions: actions ?? (readOnly
        ? [
            {
              id: "edit",
              label: "Edit",
              kind: "command",
              emphasis: "primary",
              availability: "denied",
              disabledReason: "Your current access is read-only.",
            },
          ]
        : [
            {
              id: "edit",
              label: "Edit",
              kind: "command",
              emphasis: "primary",
              availability: "available",
            },
            {
              id: "copy-link",
              label: "Copy link",
              kind: "command",
              emphasis: "tertiary",
              availability: "available",
            },
            {
              id: "archive-pattern",
              label: "Preview archive confirmation",
              kind: "command",
              emphasis: "destructive",
              availability: archived ? "disabled" : "available",
              disabledReason: archived ? "This record is already archived." : undefined,
              confirmation: {
                title: "Archive this professional record?",
                description:
                  "Archiving removes the record from active work views while preserving its professional history.",
                confirmLabel: "Archive record",
                tone: "destructive",
              },
            },
          ]),
    },
    inspector: inspector(id, inspectorOverrides),
  };
}

export const evidenceFixture = professionalObjectFixture({
  id: "60000000-0000-4000-8000-000000000001",
  type: "evidence",
  title: "Customer support platform retention and analytics configuration",
  description: "A source-backed record used to understand support-data processing and retention.",
});

export const decisionFixture = professionalObjectFixture({
  id: "60000000-0000-4000-8000-000000000002",
  type: "decision",
  title: "Use support conversations for quality analytics with additional retention controls",
  description: "Human-approved professional outcome and the conditions attached to it.",
  status: fixtureStatuses.approved,
  inspector: { related: { state: "ready", data: fixtureMixedRelatedItems } },
});

export const actionFixture = professionalObjectFixture({
  id: "60000000-0000-4000-8000-000000000003",
  type: "action",
  title: "Confirm the support platform deletion schedule with the accountable system owner",
  description: "Follow-through created from an approved privacy decision.",
  status: fixtureStatuses.open,
  inspector: {
    related: { state: "empty", message: "No related records have been linked yet." },
    history: { state: "empty", message: "No changes have been recorded since creation." },
  },
});
