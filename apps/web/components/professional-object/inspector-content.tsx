"use client";

import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { ProfessionalObjectMetadataList } from "@/components/professional-object/metadata-list";
import { ProfessionalObjectHistoryList } from "@/components/professional-object/object-history-list";
import {
  ProfessionalObjectEmptyState,
  ProfessionalObjectRestrictedState,
  ProfessionalObjectSectionError,
  RetryButton,
} from "@/components/professional-object/object-states";
import { RelatedProfessionalObjectList } from "@/components/professional-object/related-object-list";
import type {
  ProfessionalObjectInspectorViewModel,
  ProfessionalObjectSectionState,
} from "@/lib/professional-objects/view-model";

export type ProfessionalObjectInspectorSection = "details" | "related" | "history";

function SectionLoading({ label }: { label: string }) {
  return (
    <div className="space-y-3 py-2" role="status" aria-label={`Loading ${label.toLowerCase()}`}>
      <span className="workspace-skeleton block h-3 w-24" aria-hidden />
      <span className="workspace-skeleton block h-4 w-full" aria-hidden />
      <span className="workspace-skeleton block h-4 w-4/5" aria-hidden />
      <span className="sr-only">Loading {label.toLowerCase()}…</span>
    </div>
  );
}

function InspectorSection<T>({
  id,
  label,
  state,
  emptyTitle,
  renderReady,
  retrying,
  onRetry,
}: {
  id: string;
  label: string;
  state: ProfessionalObjectSectionState<T>;
  emptyTitle: string;
  renderReady: (data: T) => ReactNode;
  retrying: boolean;
  onRetry?: () => void;
}) {
  let content: ReactNode;
  if (state.state === "loading") {
    content = <SectionLoading label={label} />;
  } else if (state.state === "empty") {
    content = <ProfessionalObjectEmptyState compact title={emptyTitle} message={state.message} />;
  } else if (state.state === "restricted") {
    content = <ProfessionalObjectRestrictedState message={state.message} />;
  } else if (state.state === "error") {
    content = (
      <ProfessionalObjectSectionError
        problem={state.problem}
        retryAction={onRetry ? <RetryButton onRetry={onRetry} pending={retrying} /> : undefined}
      />
    );
  } else {
    content = renderReady(state.data);
  }

  return (
    <section aria-labelledby={id} className="border-t border-[var(--pv-divider)] py-6 first:border-t-0 first:pt-0 last:pb-0">
      <h3 id={id} className="mb-4 text-sm font-semibold leading-5 text-[var(--pv-text-strong)]">
        {label}
      </h3>
      {content}
    </section>
  );
}

export function ProfessionalObjectInspectorContent({
  inspector,
  idPrefix,
  retryingSection,
  onRetrySection,
}: {
  inspector: ProfessionalObjectInspectorViewModel;
  idPrefix: string;
  retryingSection: ProfessionalObjectInspectorSection | null;
  onRetrySection?: (section: ProfessionalObjectInspectorSection) => void;
}) {
  return (
    <>
      <InspectorSection
        id={`${idPrefix}-details`}
        label="Details"
        state={inspector.details}
        emptyTitle="No shared details"
        retrying={retryingSection === "details"}
        onRetry={onRetrySection ? () => onRetrySection("details") : undefined}
        renderReady={(items) =>
          items.length > 0 ? (
            <ProfessionalObjectMetadataList items={items} />
          ) : (
            <ProfessionalObjectEmptyState compact title="No shared details" message="No common metadata is available for this record." />
          )
        }
      />
      <InspectorSection
        id={`${idPrefix}-related`}
        label="Related items"
        state={inspector.related}
        emptyTitle="No related records"
        retrying={retryingSection === "related"}
        onRetry={onRetrySection ? () => onRetrySection("related") : undefined}
        renderReady={(items) =>
          items.length > 0 ? (
            <RelatedProfessionalObjectList items={items} />
          ) : (
            <ProfessionalObjectEmptyState compact title="No related records" message="No professional records have been linked yet." />
          )
        }
      />
      <InspectorSection
        id={`${idPrefix}-history`}
        label="History"
        state={inspector.history}
        emptyTitle="No recorded changes"
        retrying={retryingSection === "history"}
        onRetry={onRetrySection ? () => onRetrySection("history") : undefined}
        renderReady={(entries) =>
          entries.length > 0 ? (
            <ProfessionalObjectHistoryList entries={entries} />
          ) : (
            <ProfessionalObjectEmptyState compact title="No recorded changes" message="No history entries are available for this record." />
          )
        }
      />
      {retryingSection ? (
        <div className="sr-only" role="status">
          <LoaderCircle aria-hidden /> Retrying {retryingSection}…
        </div>
      ) : null}
    </>
  );
}
