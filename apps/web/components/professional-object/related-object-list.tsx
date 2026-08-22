import { Archive, Ban, ChevronRight, EyeOff } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";

import { ProfessionalObjectStatusLabel } from "@/components/professional-object/professional-object-status";
import {
  isSafeInternalHref,
  PROFESSIONAL_OBJECT_TYPE_DEFINITIONS,
} from "@/lib/professional-objects/object-types";
import type { RelatedProfessionalObject } from "@/lib/professional-objects/view-model";

function availabilityCopy(item: RelatedProfessionalObject) {
  if (item.availability === "restricted") return "You do not have access to this related record.";
  if (item.availability === "unavailable") return "This related record is no longer available.";
  if (item.availability === "archived") return "Archived record";
  return null;
}

function RelatedItemContent({ item }: { item: RelatedProfessionalObject }) {
  const definition = PROFESSIONAL_OBJECT_TYPE_DEFINITIONS[item.type];
  const Icon = definition.icon;
  const unavailableCopy = availabilityCopy(item);
  return (
    <>
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-[8px] bg-[var(--pv-surface-strong)] text-[var(--pv-text-muted)]">
        {item.availability === "restricted" ? (
          <EyeOff className="size-4" aria-hidden />
        ) : item.availability === "unavailable" ? (
          <Ban className="size-4" aria-hidden />
        ) : item.availability === "archived" ? (
          <Archive className="size-4" aria-hidden />
        ) : (
          <Icon className="size-4" aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] font-semibold uppercase tracking-[0.045em] text-[var(--pv-text-muted)]">
          {item.relationshipLabel} · {definition.label}
        </span>
        <span className="mt-1 block break-words text-[13px] font-semibold leading-5 text-[var(--pv-text-strong)]">
          {item.title ?? unavailableCopy ?? "Related record unavailable"}
        </span>
        {unavailableCopy && item.title ? (
          <span className="mt-1 block text-xs leading-5 text-[var(--pv-text-muted)]">{unavailableCopy}</span>
        ) : null}
        {item.status ? <ProfessionalObjectStatusLabel status={item.status} compact className="mt-2" /> : null}
      </span>
      {item.availability === "available" && item.href ? (
        <ChevronRight className="mt-2 size-4 shrink-0 text-[var(--pv-text-faint)]" aria-hidden />
      ) : null}
    </>
  );
}

export function RelatedProfessionalObjectList({ items }: { items: RelatedProfessionalObject[] }) {
  return (
    <ul className="divide-y divide-[var(--pv-divider)]">
      {items.map((item) => {
        const href =
          item.availability === "available" && isSafeInternalHref(item.href)
            ? item.href
            : undefined;
        return (
          <li key={item.id} className="py-3 first:pt-0 last:pb-0">
            {href ? (
              <Link
                href={href as Route}
                className="-m-2 flex min-h-11 items-start gap-3 rounded-[8px] p-2 hover:bg-[var(--pv-surface-subtle)]"
              >
                <RelatedItemContent item={item} />
              </Link>
            ) : (
              <div className="flex min-h-11 items-start gap-3" aria-disabled="true">
                <RelatedItemContent item={item} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
