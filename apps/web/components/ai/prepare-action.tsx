import { LoaderCircle } from "lucide-react";
import type { AITaskCapability } from "@/lib/ai/availability";

export function PrepareAction({
  pending,
  disabled,
  capability,
}: {
  pending: boolean;
  disabled: boolean;
  capability: AITaskCapability | null;
}) {
  const unavailable = capability !== null && !capability.available;
  return (
    <button
      type="submit"
      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--pv-radius-control)] bg-[var(--pv-accent)] px-4 text-sm font-semibold text-white transition hover:bg-[var(--pv-accent-hover)] disabled:cursor-not-allowed disabled:opacity-55"
      disabled={pending || disabled || unavailable}
      aria-describedby={unavailable ? "ai-availability-notice" : undefined}
    >
      {pending ? (
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
      ) : null}
      {pending
        ? "Preparing…"
        : unavailable
          ? "Prepare with Privexa · unavailable"
          : "Prepare with Privexa"}
    </button>
  );
}
