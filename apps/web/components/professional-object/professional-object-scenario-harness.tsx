"use client";

import { CheckCircle2, LoaderCircle, RotateCcw } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";

import type { ProfessionalObjectInspectorSection } from "@/components/professional-object/inspector-content";
import {
  BlockingProfessionalObjectError,
  ProfessionalObjectPermissionDenied,
} from "@/components/professional-object/object-states";
import { ProfessionalObjectShell } from "@/components/professional-object/professional-object-shell";
import { ProfessionalObjectSkeleton } from "@/components/professional-object/professional-object-skeleton";
import { Button } from "@/components/ui/button";
import {
  evidenceFixture,
  fixtureHistory,
  fixtureMixedRelatedItems,
} from "@/fixtures/professional-objects";
import type {
  ProfessionalObjectScenario,
  ProfessionalObjectScenarioName,
} from "@/fixtures/professional-object-scenarios";
import { professionalObjectScenarios } from "@/fixtures/professional-object-scenarios";
import { professionalObjectHref } from "@/lib/professional-objects/object-types";
import type {
  ProfessionalObjectAction,
  ProfessionalObjectPageViewModel,
  RelatedProfessionalObject,
} from "@/lib/professional-objects/view-model";

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

function bindRelatedItemsToWorkspace(
  items: RelatedProfessionalObject[],
  workspaceId: string,
): RelatedProfessionalObject[] {
  return items.map((item) => ({
    ...item,
    href:
      item.availability === "available"
        ? professionalObjectHref(workspaceId, item.type, item.id)
        : undefined,
  }));
}

function bindFixturePageToWorkspace(
  page: ProfessionalObjectPageViewModel,
  firmId: string,
  workspace: { id: string; name: string },
): ProfessionalObjectPageViewModel {
  return {
    ...page,
    object: {
      ...page.object,
      workspace: { firmId, id: workspace.id, name: workspace.name },
    },
    inspector: {
      ...page.inspector,
      details:
        page.inspector.details.state === "ready"
          ? {
              state: "ready",
              data: page.inspector.details.data.map((item) =>
                item.id === "client"
                  ? { ...item, value: { kind: "text", value: workspace.name } }
                  : item,
              ),
            }
          : page.inspector.details,
      related:
        page.inspector.related.state === "ready"
          ? {
              state: "ready",
              data: bindRelatedItemsToWorkspace(page.inspector.related.data, workspace.id),
            }
          : page.inspector.related,
    },
  };
}

function HarnessNavigation({ active }: { active: ProfessionalObjectScenarioName }) {
  return (
    <nav
      className="mx-auto flex w-full max-w-[1280px] gap-2 overflow-x-auto px-5 pb-2 pt-5 sm:px-8"
      aria-label="Professional object fixture scenarios"
    >
      {Object.values(professionalObjectScenarios).map((scenario) => (
        <Link
          key={scenario.name}
          href={`/ui-harness/professional-objects/${scenario.name}` as Route}
          aria-current={scenario.name === active ? "page" : undefined}
          className="shrink-0 rounded-full border border-[var(--pv-border)] bg-[var(--pv-surface)] px-3 py-1.5 text-xs font-medium text-[var(--pv-text-muted)] aria-[current=page]:border-[var(--pv-accent)] aria-[current=page]:bg-[var(--pv-accent-soft)] aria-[current=page]:text-[var(--pv-accent-text)]"
        >
          {scenario.label}
        </Link>
      ))}
    </nav>
  );
}

function FixtureBody({
  heading,
  paragraphs,
  optimisticOutcome,
  onOptimisticTitle,
}: {
  heading: string;
  paragraphs: string[];
  optimisticOutcome?: "success" | "failure" | "conflict";
  onOptimisticTitle: (title: string) => void;
}) {
  const [draft, setDraft] = useState("Support analytics retention configuration — reviewed");
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  async function applyOptimisticTitle() {
    if (!optimisticOutcome || pending || !draft.trim()) return;
    setProblem(null);
    setConfirmed(false);
    setPending(true);
    onOptimisticTitle(draft.trim());
    await wait(650);
    setPending(false);
    if (optimisticOutcome === "success") {
      setConfirmed(true);
      return;
    }
    if (optimisticOutcome === "conflict") {
      setProblem("A newer version of this record exists. The previous title has been restored; refresh and review before trying again.");
      return;
    }
    setProblem("The title update could not be saved. The previous title has been restored and your draft is still available.");
  }

  return (
    <section aria-labelledby="fixture-content-title">
      <p className="text-xs font-semibold text-[var(--pv-accent-text)]">Fixture-backed domain region</p>
      <h2 id="fixture-content-title" className="mt-2 text-xl font-semibold leading-7 tracking-[-0.025em] text-[var(--pv-text-strong)]">
        {heading}
      </h2>
      <div className="mt-4 max-w-[72ch] space-y-4 text-[15px] leading-7 text-[var(--pv-text)]">
        {paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </div>
      {optimisticOutcome ? (
        <div className="mt-8 border-t border-[var(--pv-divider)] pt-6">
          <h3 className="text-sm font-semibold text-[var(--pv-text-strong)]">Optimistic update contract</h3>
          <p className="mt-1 text-xs leading-5 text-[var(--pv-text-muted)]">
            This development-only control demonstrates a reversible, version-ready title update without calling a domain API.
          </p>
          <label className="mt-4 block text-xs font-semibold text-[var(--pv-text-strong)]" htmlFor="fixture-title-update">
            Proposed title
          </label>
          <input
            id="fixture-title-update"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={pending}
            className="mt-2 min-h-11 w-full rounded-[var(--pv-radius-control)] border border-[var(--pv-border)] bg-[var(--pv-surface)] px-3 text-sm text-[var(--pv-text-strong)] focus:border-[var(--pv-accent)]"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={() => void applyOptimisticTitle()} disabled={pending || !draft.trim()}>
              {pending ? (
                <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : null}
              {pending ? "Saving…" : "Apply title update"}
            </Button>
            {confirmed ? (
              <p className="inline-flex items-center gap-1.5 text-xs text-[var(--pv-success)]" role="status">
                <CheckCircle2 className="size-4" aria-hidden /> Update confirmed
              </p>
            ) : null}
          </div>
          {problem ? <p className="mt-3 text-xs leading-5 text-[var(--pv-critical)]" role="alert">{problem}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function ObjectScenario({
  scenario,
  activeFirmId,
  activeWorkspace,
}: {
  scenario: Extract<ProfessionalObjectScenario, { kind: "object" }>;
  activeFirmId: string;
  activeWorkspace: { id: string; name: string };
}) {
  const authoritativeTitle = scenario.page.object.title;
  const [page, setPage] = useState<ProfessionalObjectPageViewModel>(() =>
    bindFixturePageToWorkspace(scenario.page, activeFirmId, activeWorkspace),
  );
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  async function handleAction(action: ProfessionalObjectAction) {
    setActionNotice(null);
    if (action.id === "copy-link") {
      try {
        await navigator.clipboard.writeText(window.location.href);
        setActionNotice("Link copied.");
        return { ok: true as const };
      } catch {
        return { ok: false as const, message: "The link could not be copied. Copy it from the address bar instead." };
      }
    }
    await wait(500);
    if (scenario.actionOutcome === "failure") {
      return {
        ok: false as const,
        message: "The fixture action could not be completed. Review the record and try again.",
      };
    }
    if (action.id === "archive-pattern") {
      setActionNotice("Confirmation completed in the fixture harness. No authoritative record was changed.");
      return { ok: true as const };
    }
    setActionNotice("This action is ready for a later domain-specific controller.");
    return { ok: true as const };
  }

  async function retrySection(section: ProfessionalObjectInspectorSection) {
    await wait(500);
    setPage((current) => ({
      ...current,
      inspector: {
        ...current.inspector,
        [section]:
          section === "related"
            ? {
                state: "ready",
                data: bindRelatedItemsToWorkspace(fixtureMixedRelatedItems, activeWorkspace.id),
              }
            : section === "history"
              ? { state: "ready", data: fixtureHistory }
              : current.inspector.details,
      },
    }));
  }

  function optimisticTitle(title: string) {
    const shouldRollback = scenario.optimisticOutcome === "failure" || scenario.optimisticOutcome === "conflict";
    setPage((current) => ({ ...current, object: { ...current.object, title } }));
    if (shouldRollback) {
      window.setTimeout(() => {
        setPage((current) => ({ ...current, object: { ...current.object, title: authoritativeTitle } }));
      }, 650);
    }
  }

  return (
    <>
      <ProfessionalObjectShell
        page={page}
        activeFirmId={activeFirmId}
        activeWorkspaceId={activeWorkspace.id}
        onAction={handleAction}
        onRetrySection={retrySection}
      >
        <FixtureBody
          {...scenario.body}
          optimisticOutcome={scenario.optimisticOutcome}
          onOptimisticTitle={optimisticTitle}
        />
        {actionNotice ? <p className="mt-6 text-xs leading-5 text-[var(--pv-success)]" role="status">{actionNotice}</p> : null}
      </ProfessionalObjectShell>
    </>
  );
}

export function ProfessionalObjectScenarioHarness({
  scenario,
  activeFirmId,
  activeWorkspace,
}: {
  scenario: ProfessionalObjectScenario;
  activeFirmId: string;
  activeWorkspace: { id: string; name: string };
}) {
  const [recovered, setRecovered] = useState(false);
  return (
    <>
      <HarnessNavigation active={scenario.name} />
      {scenario.kind === "loading" ? <ProfessionalObjectSkeleton /> : null}
      {scenario.kind === "permission_denied" ? <ProfessionalObjectPermissionDenied /> : null}
      {scenario.kind === "object_error" && !recovered ? (
        <BlockingProfessionalObjectError
          problem={scenario.problem}
          retryAction={
            <Button variant="primary" onClick={() => setRecovered(true)}>
              <RotateCcw className="size-4" aria-hidden /> Try again
            </Button>
          }
        />
      ) : null}
      {scenario.kind === "object_error" && recovered ? (
        <ObjectScenario
          key={`recovered:${activeWorkspace.id}`}
          scenario={{
            kind: "object",
            name: "evidence",
            label: "Recovered evidence",
            page: evidenceFixture,
            body: {
              heading: "Professional content restored",
              paragraphs: ["The retry recovered the object without requiring a full-page browser refresh."],
            },
          }}
          activeFirmId={activeFirmId}
          activeWorkspace={activeWorkspace}
        />
      ) : null}
      {scenario.kind === "object" ? (
        <ObjectScenario
          key={`${scenario.name}:${activeWorkspace.id}`}
          scenario={scenario}
          activeFirmId={activeFirmId}
          activeWorkspace={activeWorkspace}
        />
      ) : null}
    </>
  );
}
