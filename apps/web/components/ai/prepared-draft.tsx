import { Check, RotateCcw, X } from "lucide-react";

import type { PreparedWorkNoteCandidate } from "@/lib/ai/work-note";

export function PreparedDraft({
  candidate,
  accepted,
  onAccept,
  onDismiss,
  onRetry,
}: {
  candidate: PreparedWorkNoteCandidate;
  accepted: boolean;
  onAccept: () => void;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  return (
    <section
      className="mt-6 rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-5"
      aria-labelledby="prepared-draft-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="workspace-eyebrow">Prepared by Privexa</p>
          <h2 id="prepared-draft-title" className="mt-2 text-lg font-semibold text-[var(--pv-text-strong)]">
            {accepted ? "Draft selected for your work" : "Review this provisional draft"}
          </h2>
        </div>
        <span className="rounded-full bg-[var(--pv-attention-soft)] px-3 py-1 text-xs font-semibold text-[var(--pv-attention)]">
          {accepted ? "Human accepted" : "Review required"}
        </span>
      </div>
      <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[var(--pv-text)]">{candidate.draft}</p>
      <dl className="mt-5 grid gap-4 border-t border-[var(--pv-divider)] pt-4 text-sm">
        <div>
          <dt className="font-semibold text-[var(--pv-text-strong)]">Suggested follow-up</dt>
          <dd className="mt-1 leading-6 text-[var(--pv-text-muted)]">{candidate.suggested_follow_up}</dd>
        </div>
        {candidate.caveat ? (
          <div>
            <dt className="font-semibold text-[var(--pv-text-strong)]">Caveat</dt>
            <dd className="mt-1 leading-6 text-[var(--pv-text-muted)]">{candidate.caveat}</dd>
          </div>
        ) : null}
      </dl>
      <p className="mt-4 text-xs leading-5 text-[var(--pv-text-muted)]">
        This candidate is not an authoritative client record or professional decision.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        {!accepted ? (
          <button type="button" className="ai-secondary-action" onClick={onAccept}>
            <Check className="size-4" aria-hidden /> Use draft
          </button>
        ) : null}
        <button type="button" className="ai-tertiary-action" onClick={onDismiss}>
          <X className="size-4" aria-hidden /> Dismiss
        </button>
        <button type="button" className="ai-tertiary-action" onClick={onRetry}>
          <RotateCcw className="size-4" aria-hidden /> Retry
        </button>
      </div>
    </section>
  );
}
