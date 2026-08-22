import { AlertTriangle, EyeOff, Inbox, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { SafeProblem } from "@/lib/api/problem-details";

export function ProfessionalObjectEmptyState({
  title,
  message,
  compact = false,
}: {
  title: string;
  message: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "py-3" : "py-10 text-center"}>
      {!compact ? (
        <span className="mx-auto grid size-10 place-items-center rounded-[10px] bg-[var(--pv-surface-strong)] text-[var(--pv-text-muted)]">
          <Inbox className="size-5" aria-hidden />
        </span>
      ) : null}
      <p className={`${compact ? "" : "mt-4"} text-[13px] font-semibold leading-5 text-[var(--pv-text-strong)]`}>
        {title}
      </p>
      <p className="mt-1 text-xs leading-5 text-[var(--pv-text-muted)]">{message}</p>
    </div>
  );
}

export function ProfessionalObjectSectionError({
  problem,
  retryAction,
}: {
  problem: SafeProblem;
  retryAction?: ReactNode;
}) {
  return (
    <div className="rounded-[10px] border border-[color-mix(in_srgb,var(--pv-critical)_20%,var(--pv-border))] bg-[var(--pv-critical-soft)] p-3" role="alert">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[var(--pv-critical)]" aria-hidden />
        <div className="min-w-0">
          <p className="text-[13px] font-semibold leading-5 text-[var(--pv-critical)]">Supporting information unavailable</p>
          <p className="mt-1 text-xs leading-5 text-[var(--pv-text-muted)]">{problem.detail}</p>
          {problem.requestId ? (
            <p className="mt-1 font-mono text-[10px] leading-4 text-[var(--pv-text-muted)]">Reference {problem.requestId}</p>
          ) : null}
          {retryAction ? <div className="mt-2">{retryAction}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function ProfessionalObjectRestrictedState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 py-3">
      <EyeOff className="mt-0.5 size-4 shrink-0 text-[var(--pv-text-muted)]" aria-hidden />
      <p className="text-xs leading-5 text-[var(--pv-text-muted)]">{message}</p>
    </div>
  );
}

export function BlockingProfessionalObjectError({
  problem,
  retryAction,
}: {
  problem: SafeProblem;
  retryAction?: ReactNode;
}) {
  return (
    <main className="workspace-state-page" aria-labelledby="professional-object-error-title">
      <section className="workspace-state-card" role="alert">
        <span className="workspace-state-icon" aria-hidden>
          <AlertTriangle className="size-5" />
        </span>
        <p className="workspace-eyebrow">Professional record</p>
        <h1 id="professional-object-error-title" className="workspace-state-title">This record could not be opened</h1>
        <p className="workspace-state-copy">{problem.detail}</p>
        {problem.requestId ? (
          <p className="mt-3 font-mono text-xs text-[var(--pv-text)]">Reference {problem.requestId}</p>
        ) : null}
        {retryAction ? <div className="mt-6">{retryAction}</div> : null}
      </section>
    </main>
  );
}

export function ProfessionalObjectPermissionDenied() {
  return (
    <main className="workspace-state-page" aria-labelledby="professional-object-denied-title">
      <section className="workspace-state-card">
        <span className="workspace-state-icon" aria-hidden>
          <EyeOff className="size-5" />
        </span>
        <p className="workspace-eyebrow">Professional record</p>
        <h1 id="professional-object-denied-title" className="workspace-state-title">This record is not available to you</h1>
        <p className="workspace-state-copy">
          Your current access does not allow this record to be displayed. Return to the active client workspace or contact your firm administrator if you expected access.
        </p>
      </section>
    </main>
  );
}

export function RetryButton({ onRetry, pending = false }: { onRetry: () => void; pending?: boolean }) {
  return (
    <Button variant="tertiary" size="compact" onClick={onRetry} disabled={pending}>
      <RotateCcw
        className={`size-3.5 ${pending ? "animate-spin motion-reduce:animate-none" : ""}`}
        aria-hidden
      />
      {pending ? "Retrying…" : "Try again"}
    </Button>
  );
}
