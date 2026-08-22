"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { AIAvailabilityNotice } from "@/components/ai/availability-notice";
import { PrepareAction } from "@/components/ai/prepare-action";
import { PreparedDraft } from "@/components/ai/prepared-draft";
import {
  isPrepareWorkNoteResponse,
  type AIWorkNoteProblem,
  type PreparedWorkNoteCandidate,
} from "@/lib/ai/work-note";
import {
  capabilityFromFailure,
  isAITaskCapability,
  type AITaskCapability,
} from "@/lib/ai/availability";

export function WorkNotePreparation({
  activeClientId,
  sourceFileIds = [],
}: {
  activeClientId: string;
  sourceFileIds?: readonly string[];
}) {
  return (
    <ClientWorkNotePreparation
      key={activeClientId}
      activeClientId={activeClientId}
      sourceFileIds={sourceFileIds}
    />
  );
}

function ClientWorkNotePreparation({
  activeClientId,
  sourceFileIds,
}: {
  activeClientId: string;
  sourceFileIds: readonly string[];
}) {
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [candidate, setCandidate] = useState<PreparedWorkNoteCandidate | null>(
    null,
  );
  const [accepted, setAccepted] = useState(false);
  const [problem, setProblem] = useState<AIWorkNoteProblem | null>(null);
  const [capability, setCapability] = useState<AITaskCapability | null>(null);
  const requestSequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/ai/capability", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => response.json() as Promise<unknown>)
      .then((body) => {
        if (isAITaskCapability(body)) setCapability(body);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function prepare(event?: FormEvent) {
    event?.preventDefault();
    if (pending || note.trim().length === 0) return;
    const sequence = ++requestSequence.current;
    setPending(true);
    setProblem(null);
    setCandidate(null);
    setAccepted(false);
    try {
      const response = await fetch("/api/ai/work-note", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note, source_file_ids: sourceFileIds }),
      });
      const body: unknown = await response.json();
      if (sequence !== requestSequence.current) return;
      if (!isPrepareWorkNoteResponse(body)) throw new Error("invalid response");
      if (body.status === "PREPARED") {
        setCapability({
          task_id: "ai.prepare_work_note",
          state: "AVAILABLE",
          available: true,
          retryable: false,
          retry_after_seconds: null,
        });
        if (body.candidate.client_id !== activeClientId) {
          setProblem({
            code: "AI_STALE_CLIENT_CONTEXT",
            detail:
              "The client context changed, so this draft was discarded. Continue manually.",
            retryable: false,
            retry_after_seconds: null,
          });
          setCapability(capabilityFromFailure(false, false));
          return;
        }
        setCandidate(body.candidate);
      } else {
        setProblem(body.problem);
        setCapability(
          capabilityFromFailure(
            body.problem.retryable,
            body.status === "RESTRICTED",
          ),
        );
      }
    } catch {
      if (sequence === requestSequence.current) {
        setProblem({
          code: "AI_PREPARATION_FAILED",
          detail:
            "Privexa could not prepare this draft. Your manual note is unchanged.",
          retryable: true,
          retry_after_seconds: null,
        });
        setCapability(capabilityFromFailure(true, false));
      }
    } finally {
      if (sequence === requestSequence.current) setPending(false);
    }
  }

  function dismiss() {
    requestSequence.current += 1;
    setCandidate(null);
    setAccepted(false);
  }

  return (
    <form onSubmit={prepare} className="mt-8 max-w-3xl">
      <label
        htmlFor="client-work-note"
        className="text-sm font-semibold text-[var(--pv-text-strong)]"
      >
        Client work note
      </label>
      <p
        id="client-work-note-help"
        className="mt-1 text-sm leading-6 text-[var(--pv-text-muted)]"
      >
        Capture your facts and working observations. Privexa can prepare a
        concise draft for review.
      </p>
      <textarea
        id="client-work-note"
        aria-describedby="client-work-note-help"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        maxLength={5_000}
        rows={9}
        className="mt-3 w-full resize-y rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-4 text-sm leading-6 text-[var(--pv-text-strong)] shadow-sm outline-none transition focus:border-[var(--pv-accent)]"
        placeholder="Record the client context, known facts, and points that still need verification."
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-[var(--pv-text-muted)]">
          {note.length.toLocaleString()} / 5,000 characters
        </span>
        <PrepareAction
          pending={pending}
          disabled={note.trim().length === 0}
          capability={capability}
        />
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {pending ? "Privexa is preparing a work-note draft." : ""}
      </div>

      {capability && !capability.available ? (
        <AIAvailabilityNotice
          capability={capability}
          detail={problem?.detail}
          onRetry={capability.retryable ? () => void prepare() : undefined}
        />
      ) : null}

      {candidate ? (
        <PreparedDraft
          candidate={candidate}
          accepted={accepted}
          onAccept={() => {
            setNote(candidate.draft);
            setAccepted(true);
          }}
          onDismiss={dismiss}
          onRetry={() => void prepare()}
        />
      ) : null}
    </form>
  );
}
