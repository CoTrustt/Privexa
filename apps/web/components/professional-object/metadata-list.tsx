import { formatProfessionalTimestamp } from "@/lib/professional-objects/date-time";
import type {
  ProfessionalMetadataValue,
  ProfessionalObjectMetadataItem,
} from "@/lib/professional-objects/view-model";

function MetadataValue({ value }: { value: ProfessionalMetadataValue }) {
  if (value.kind === "empty") {
    return <span className="text-[var(--pv-text-muted)]">Not available</span>;
  }
  if (value.kind === "actor") {
    return <span>{value.value.displayName ?? "Former or unavailable member"}</span>;
  }
  if (value.kind === "timestamp") {
    const timestamp = formatProfessionalTimestamp(value.value);
    return timestamp ? (
      <time dateTime={timestamp.dateTime}>{timestamp.label}</time>
    ) : (
      <span className="text-[var(--pv-text-muted)]">Date unavailable</span>
    );
  }
  if (value.kind === "identifier") {
    return <code className="break-all font-mono text-[12px] leading-5">{value.value}</code>;
  }
  return <span>{value.value}</span>;
}

export function ProfessionalObjectMetadataList({
  items,
}: {
  items: ProfessionalObjectMetadataItem[];
}) {
  return (
    <dl className="divide-y divide-[var(--pv-divider)]">
      {items.map((item) => (
        <div key={item.id} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-4">
          <dt className="text-xs font-medium leading-5 text-[var(--pv-text-muted)]">{item.label}</dt>
          <dd className="min-w-0 break-words text-[13px] leading-5 text-[var(--pv-text)]">
            <MetadataValue value={item.value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
