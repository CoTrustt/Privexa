import { Eye } from "lucide-react";

import {
  ProfessionalObjectActions,
  type ProfessionalObjectActionResult,
} from "@/components/professional-object/professional-object-actions";
import { ProfessionalObjectStatusLabel } from "@/components/professional-object/professional-object-status";
import { PROFESSIONAL_OBJECT_TYPE_DEFINITIONS } from "@/lib/professional-objects/object-types";
import type {
  ProfessionalObjectAction,
  ProfessionalObjectViewModel,
} from "@/lib/professional-objects/view-model";

import styles from "./professional-object-shell.module.css";

export function ProfessionalObjectHeader({
  object,
  titleId,
  onAction,
}: {
  object: ProfessionalObjectViewModel;
  titleId: string;
  onAction?: (action: ProfessionalObjectAction) => Promise<ProfessionalObjectActionResult>;
}) {
  const definition = PROFESSIONAL_OBJECT_TYPE_DEFINITIONS[object.type];
  const TypeIcon = definition.icon;
  return (
    <header className={styles.header}>
      <div className="flex min-w-0 flex-col gap-7 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 max-w-4xl">
          <p className="flex min-w-0 items-center gap-2 text-xs font-semibold leading-5 text-[var(--pv-text-muted)]">
            <span className="min-w-0 truncate" title={object.workspace.name}>{object.workspace.name}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex shrink-0 items-center gap-1.5">
              <TypeIcon className="size-3.5" aria-hidden />
              {definition.label}
            </span>
          </p>
          <h1
            id={titleId}
            className="mt-3 break-words text-[clamp(1.75rem,3.4vw,2.25rem)] font-semibold leading-[1.16] tracking-[-0.04em] text-[var(--pv-text-strong)] [overflow-wrap:anywhere]"
          >
            {object.title}
          </h1>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <ProfessionalObjectStatusLabel status={object.status} />
            {object.capabilities.mode === "read_only" ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--pv-text-muted)]">
                <Eye className="size-3.5" aria-hidden /> Read-only
              </span>
            ) : null}
          </div>
          {object.description ? (
            <p className="mt-4 max-w-[72ch] text-[15px] leading-6 text-[var(--pv-text-muted)]">
              {object.description}
            </p>
          ) : null}
          {object.capabilities.mode === "read_only" && object.capabilities.explanation ? (
            <p className="mt-3 max-w-[72ch] text-xs leading-5 text-[var(--pv-text-muted)]">
              {object.capabilities.explanation}
            </p>
          ) : null}
        </div>
        <ProfessionalObjectActions actions={object.actions} onAction={onAction} />
      </div>
    </header>
  );
}
