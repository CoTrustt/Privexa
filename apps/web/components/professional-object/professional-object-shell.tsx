import type { ReactNode } from "react";

import { ProfessionalObjectHeader } from "@/components/professional-object/professional-object-header";
import { ProfessionalObjectInspector } from "@/components/professional-object/professional-object-inspector";
import type { ProfessionalObjectInspectorSection } from "@/components/professional-object/inspector-content";
import {
  ProfessionalObjectEmptyState,
  ProfessionalObjectPermissionDenied,
} from "@/components/professional-object/object-states";
import type { ProfessionalObjectActionResult } from "@/components/professional-object/professional-object-actions";
import type {
  ProfessionalObjectAction,
  ProfessionalObjectPageViewModel,
} from "@/lib/professional-objects/view-model";

import styles from "./professional-object-shell.module.css";

export function ProfessionalObjectShell({
  page,
  activeFirmId,
  activeWorkspaceId,
  children,
  onAction,
  onRetrySection,
}: {
  page: ProfessionalObjectPageViewModel;
  activeFirmId: string;
  activeWorkspaceId: string;
  children?: ReactNode;
  onAction?: (action: ProfessionalObjectAction) => Promise<ProfessionalObjectActionResult>;
  onRetrySection?: (section: ProfessionalObjectInspectorSection) => Promise<void>;
}) {
  if (
    page.object.workspace.firmId !== activeFirmId ||
    page.object.workspace.id !== activeWorkspaceId
  ) {
    return <ProfessionalObjectPermissionDenied />;
  }

  const titleId = "professional-object-title";
  return (
    <main className={`workspace-main ${styles.page}`} aria-labelledby={titleId}>
      <div className={styles.layout}>
        <ProfessionalObjectHeader object={page.object} titleId={titleId} onAction={onAction} />
        <article className={styles.content} aria-label={`${page.object.title} professional content`}>
          <div className={styles.contentSurface}>
            {children ?? (
              <ProfessionalObjectEmptyState
                title="No professional content yet"
                message="This record exists, but its domain content has not been populated."
              />
            )}
          </div>
        </article>
        <ProfessionalObjectInspector inspector={page.inspector} onRetrySection={onRetrySection} />
      </div>
    </main>
  );
}
