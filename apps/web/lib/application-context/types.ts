export type ApplicationContextState =
  | "ACTIVE_CLIENT"
  | "CLIENT_SELECTION_REQUIRED"
  | "NO_AUTHORISED_CLIENTS";

export interface IdentitySummary {
  id: string;
  display_name: string;
}

export type ClientSummary = IdentitySummary;

export interface QuestionCapabilities {
  can_create: boolean;
  can_update: boolean;
}

export interface ApplicationContext {
  state: ApplicationContextState;
  user: IdentitySummary;
  firm: IdentitySummary;
  active_client: ClientSummary | null;
  authorised_clients: ClientSummary[];
  question_capabilities?: QuestionCapabilities;
}

export interface ApplicationContextProblem {
  code: string;
  detail: string;
}

export type ApplicationContextResult =
  | { ok: true; context: ApplicationContext }
  | { ok: false; status: number; problem: ApplicationContextProblem };

function isIdentitySummary(value: unknown): value is IdentitySummary {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.id === "string" && typeof candidate.display_name === "string";
}

export function isApplicationContext(value: unknown): value is ApplicationContext {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  const validState =
    candidate.state === "ACTIVE_CLIENT" ||
    candidate.state === "CLIENT_SELECTION_REQUIRED" ||
    candidate.state === "NO_AUTHORISED_CLIENTS";
  const capabilities = candidate.question_capabilities;
  const validCapabilities =
    capabilities === undefined ||
    (typeof capabilities === "object" &&
      capabilities !== null &&
      typeof (capabilities as Record<string, unknown>).can_create === "boolean" &&
      typeof (capabilities as Record<string, unknown>).can_update === "boolean");
  return (
    validState &&
    validCapabilities &&
    isIdentitySummary(candidate.user) &&
    isIdentitySummary(candidate.firm) &&
    (candidate.active_client === null || isIdentitySummary(candidate.active_client)) &&
    Array.isArray(candidate.authorised_clients) &&
    candidate.authorised_clients.every(isIdentitySummary)
  );
}

export function questionCapabilities(context: ApplicationContext): QuestionCapabilities {
  return context.question_capabilities ?? { can_create: false, can_update: false };
}

export function isApplicationContextProblem(value: unknown): value is ApplicationContextProblem {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.detail === "string";
}
