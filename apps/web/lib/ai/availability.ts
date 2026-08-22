export type AICapabilityState =
  "AVAILABLE" | "TEMPORARILY_UNAVAILABLE" | "UNAVAILABLE" | "RESTRICTED";

export interface AITaskCapability {
  task_id: "ai.prepare_work_note";
  state: AICapabilityState;
  available: boolean;
  retryable: boolean;
  retry_after_seconds: number | null;
}

export function isAITaskCapability(value: unknown): value is AITaskCapability {
  if (typeof value !== "object" || value === null) return false;
  const capability = value as Record<string, unknown>;
  return (
    capability.task_id === "ai.prepare_work_note" &&
    [
      "AVAILABLE",
      "TEMPORARILY_UNAVAILABLE",
      "UNAVAILABLE",
      "RESTRICTED",
    ].includes(String(capability.state)) &&
    typeof capability.available === "boolean" &&
    typeof capability.retryable === "boolean" &&
    (capability.retry_after_seconds === null ||
      typeof capability.retry_after_seconds === "number")
  );
}

export function capabilityFromFailure(
  retryable: boolean,
  restricted: boolean,
): AITaskCapability {
  return {
    task_id: "ai.prepare_work_note",
    state: restricted
      ? "RESTRICTED"
      : retryable
        ? "TEMPORARILY_UNAVAILABLE"
        : "UNAVAILABLE",
    available: false,
    retryable,
    retry_after_seconds: null,
  };
}
