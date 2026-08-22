import {
  CheckSquare2,
  CircleHelp,
  FileCheck2,
  FileText,
  GitBranch,
  Scale,
  type LucideIcon,
} from "lucide-react";

import type {
  ProfessionalObjectInternalHref,
  ProfessionalObjectStatusTone,
  ProfessionalObjectType,
} from "@/lib/professional-objects/view-model";

interface ProfessionalObjectTypeDefinition {
  label: string;
  pluralRouteSegment: string;
  icon: LucideIcon;
}

export const PROFESSIONAL_OBJECT_TYPE_DEFINITIONS: Record<
  ProfessionalObjectType,
  ProfessionalObjectTypeDefinition
> = {
  question: { label: "Question", pluralRouteSegment: "questions", icon: CircleHelp },
  processing_activity: {
    label: "Processing activity",
    pluralRouteSegment: "processing-activities",
    icon: GitBranch,
  },
  evidence: { label: "Evidence", pluralRouteSegment: "evidence", icon: FileText },
  obligation: { label: "Obligation", pluralRouteSegment: "obligations", icon: Scale },
  decision: { label: "Decision", pluralRouteSegment: "decisions", icon: FileCheck2 },
  action: { label: "Action", pluralRouteSegment: "actions", icon: CheckSquare2 },
};

export const STATUS_TONE_LABELS: Record<ProfessionalObjectStatusTone, string> = {
  neutral: "Neutral state",
  information: "Active state",
  attention: "Needs attention",
  success: "Completed or verified state",
  critical: "Blocked or critical state",
};

export function professionalObjectHref(
  clientId: string,
  type: ProfessionalObjectType,
  objectId: string,
): ProfessionalObjectInternalHref {
  const segment = PROFESSIONAL_OBJECT_TYPE_DEFINITIONS[type].pluralRouteSegment;
  return `/clients/${encodeURIComponent(clientId)}/${segment}/${encodeURIComponent(objectId)}`;
}

export function isSafeInternalHref(
  value: string | null | undefined,
): value is ProfessionalObjectInternalHref {
  if (!value?.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return false;
  }

  try {
    const url = new URL(value, "https://privexa.invalid");
    return url.origin === "https://privexa.invalid";
  } catch {
    return false;
  }
}
