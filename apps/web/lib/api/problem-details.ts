export interface SafeProblem {
  code: string;
  detail: string;
  requestId?: string;
  status?: number;
}

export function isSafeProblem(value: unknown): value is SafeProblem {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.code === "string" &&
    typeof candidate.detail === "string" &&
    (candidate.requestId === undefined || typeof candidate.requestId === "string") &&
    (candidate.status === undefined || typeof candidate.status === "number")
  );
}

export function unexpectedResponseProblem(requestId?: string): SafeProblem {
  return {
    code: "UNEXPECTED_RESPONSE",
    detail: "Privexa received an unexpected response. Try again.",
    requestId,
  };
}
