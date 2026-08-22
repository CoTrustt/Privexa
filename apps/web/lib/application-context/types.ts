export type ApplicationContextState =
  | "ACTIVE_CLIENT"
  | "CLIENT_SELECTION_REQUIRED"
  | "NO_AUTHORISED_CLIENTS";

export interface IdentitySummary {
  id: string;
  display_name: string;
}

export type ClientSummary = IdentitySummary;

export interface ApplicationContext {
  state: ApplicationContextState;
  user: IdentitySummary;
  firm: IdentitySummary;
  active_client: ClientSummary | null;
  authorised_clients: ClientSummary[];
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
  return (
    validState &&
    isIdentitySummary(candidate.user) &&
    isIdentitySummary(candidate.firm) &&
    (candidate.active_client === null || isIdentitySummary(candidate.active_client)) &&
    Array.isArray(candidate.authorised_clients) &&
    candidate.authorised_clients.every(isIdentitySummary)
  );
}

export function isApplicationContextProblem(value: unknown): value is ApplicationContextProblem {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.detail === "string";
}
