import { formatProfessionalTimestamp } from "@/lib/professional-objects/date-time";
import type { ProfessionalObjectHistoryEntry } from "@/lib/professional-objects/view-model";

export function ProfessionalObjectHistoryList({
  entries,
}: {
  entries: ProfessionalObjectHistoryEntry[];
}) {
  return (
    <ol className="space-y-0">
      {entries.map((entry, index) => {
        const timestamp = formatProfessionalTimestamp(entry.occurredAt);
        return (
          <li key={entry.id} className="relative grid grid-cols-[1rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
            {index < entries.length - 1 ? (
              <span className="absolute bottom-0 left-[0.21875rem] top-3 w-px bg-[var(--pv-divider)]" aria-hidden />
            ) : null}
            <span className="relative mt-1.5 size-2 rounded-full border-2 border-[var(--pv-surface)] bg-[var(--pv-text-faint)] ring-1 ring-[var(--pv-border)]" aria-hidden />
            <div className="min-w-0">
              <p className="text-[13px] font-semibold leading-5 text-[var(--pv-text-strong)]">{entry.action}</p>
              {entry.description ? (
                <p className="mt-1 break-words text-xs leading-5 text-[var(--pv-text-muted)]">{entry.description}</p>
              ) : null}
              <p className="mt-1.5 text-[11px] leading-4 text-[var(--pv-text-muted)]">
                {entry.actor?.displayName ?? "Actor unavailable"}
                {timestamp ? (
                  <>
                    {" · "}
                    <time dateTime={timestamp.dateTime}>{timestamp.label}</time>
                  </>
                ) : null}
                {entry.version ? ` · Version ${entry.version}` : ""}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
