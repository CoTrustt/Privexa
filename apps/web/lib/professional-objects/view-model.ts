import type { SafeProblem } from "@/lib/api/problem-details";

export const PROFESSIONAL_OBJECT_TYPES = [
  "question",
  "processing_activity",
  "evidence",
  "obligation",
  "decision",
  "action",
] as const;

export type ProfessionalObjectType = (typeof PROFESSIONAL_OBJECT_TYPES)[number];

export type ProfessionalObjectInternalHref = `/${string}`;

export type ProfessionalObjectStatusTone =
  | "neutral"
  | "information"
  | "attention"
  | "success"
  | "critical";

export interface ProfessionalObjectStatus {
  key: string;
  label: string;
  tone: ProfessionalObjectStatusTone;
  description?: string;
}

export interface ProfessionalActor {
  membershipId: string;
  displayName: string | null;
}

export interface ProfessionalObjectWorkspace {
  firmId: string;
  id: string;
  name: string;
}

export interface ProfessionalObjectCapabilities {
  mode: "editable" | "read_only";
  explanation?: string;
}

export interface ProfessionalObjectConfirmation {
  title: string;
  description: string;
  confirmLabel: string;
  tone?: "default" | "destructive";
}

export interface ProfessionalObjectAction {
  id: string;
  label: string;
  kind: "navigate" | "command";
  href?: ProfessionalObjectInternalHref;
  emphasis: "primary" | "secondary" | "tertiary" | "destructive";
  availability: "available" | "disabled" | "denied";
  disabledReason?: string;
  confirmation?: ProfessionalObjectConfirmation;
}

export type ProfessionalMetadataValue =
  | { kind: "text"; value: string }
  | { kind: "identifier"; value: string }
  | { kind: "timestamp"; value: string }
  | { kind: "actor"; value: ProfessionalActor }
  | { kind: "empty"; value?: never };

export interface ProfessionalObjectMetadataItem {
  id: string;
  label: string;
  value: ProfessionalMetadataValue;
}

export type RelatedObjectAvailability =
  | "available"
  | "restricted"
  | "archived"
  | "unavailable";

export interface RelatedProfessionalObject {
  id: string;
  type: ProfessionalObjectType;
  title: string | null;
  relationshipLabel: string;
  status?: ProfessionalObjectStatus;
  href?: ProfessionalObjectInternalHref;
  availability: RelatedObjectAvailability;
}

export interface ProfessionalObjectHistoryEntry {
  id: string;
  action: string;
  description?: string;
  occurredAt: string;
  actor: ProfessionalActor | null;
  version?: number;
}

export type ProfessionalObjectSectionState<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "empty"; message: string }
  | { state: "restricted"; message: string }
  | { state: "error"; problem: SafeProblem };

export interface ProfessionalObjectInspectorViewModel {
  details: ProfessionalObjectSectionState<ProfessionalObjectMetadataItem[]>;
  related: ProfessionalObjectSectionState<RelatedProfessionalObject[]>;
  history: ProfessionalObjectSectionState<ProfessionalObjectHistoryEntry[]>;
}

export interface ProfessionalObjectViewModel {
  id: string;
  type: ProfessionalObjectType;
  title: string;
  description?: string;
  status: ProfessionalObjectStatus;
  workspace: ProfessionalObjectWorkspace;
  createdAt: string;
  updatedAt: string;
  createdBy: ProfessionalActor;
  updatedBy: ProfessionalActor;
  version: number;
  archivedAt?: string;
  capabilities: ProfessionalObjectCapabilities;
  actions: ProfessionalObjectAction[];
}

export interface ProfessionalObjectPageViewModel {
  object: ProfessionalObjectViewModel;
  inspector: ProfessionalObjectInspectorViewModel;
}
