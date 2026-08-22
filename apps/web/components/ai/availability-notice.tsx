import { CircleAlert } from "lucide-react";

import type { AITaskCapability } from "@/lib/ai/availability";

export function AIAvailabilityNotice({
  capability,
  detail,
  onRetry,
}: {
  capability: AITaskCapability;
  detail?: string;
  onRetry?: () => void;
}) {
  const restricted = capability.state === "RESTRICTED";
  return (
    <section
      id="ai-availability-notice"
      className="mt-5 rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface-subtle)] p-4"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <CircleAlert
          className="mt-0.5 size-5 shrink-0 text-[var(--pv-text-muted)]"
          aria-hidden
        />
        <div>
          <h2 className="text-sm font-semibold text-[var(--pv-text-strong)]">
            {restricted
              ? "Preparation unavailable for this context"
              : "Privexa assistance unavailable"}
          </h2>
          <p className="mt-1 text-sm leading-6 text-[var(--pv-text-muted)]">
            {detail ??
              (restricted
                ? "You can continue working manually."
                : "Privexa assistance is temporarily unavailable. You can continue working normally.")}
          </p>
          {capability.retryable && onRetry ? (
            <button
              type="button"
              className="ai-tertiary-action mt-3"
              onClick={onRetry}
            >
              Try again
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
