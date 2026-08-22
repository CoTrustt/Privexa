"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircle } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { questionDraftSchema, type QuestionDraft } from "@/lib/questions/validation";

export type QuestionFormResult = { ok: true } | { ok: false; message: string };

export function QuestionForm({
  prompt,
  defaultValues = { question_text: "", context: "" },
  submitLabel,
  autoFocus = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: {
  prompt: string;
  defaultValues?: QuestionDraft;
  submitLabel: string;
  autoFocus?: boolean;
  onSubmit: (draft: QuestionDraft) => Promise<QuestionFormResult>;
  onCancel: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [serverProblem, setServerProblem] = useState<string | null>(null);
  const questionErrorId = useId();
  const contextErrorId = useId();
  const {
    register,
    handleSubmit,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<QuestionDraft>({
    resolver: zodResolver(questionDraftSchema),
    defaultValues,
  });

  useEffect(() => onDirtyChange?.(isDirty), [isDirty, onDirtyChange]);

  async function submit(draft: QuestionDraft) {
    if (isSubmitting) return;
    setServerProblem(null);
    const result = await onSubmit(draft).catch(() => ({
      ok: false as const,
      message: "The question could not be saved right now. Your work is unchanged.",
    }));
    if (!result.ok) setServerProblem(result.message);
  }

  return (
    <form onSubmit={handleSubmit(submit)} noValidate className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-7 overflow-y-auto px-5 py-6 sm:px-8 sm:py-8">
        <div>
          <label
            htmlFor="question-text"
            className="block text-base font-semibold leading-6 text-[var(--pv-text-strong)]"
          >
            {prompt}
          </label>
          <textarea
            id="question-text"
            rows={7}
            autoFocus={autoFocus}
            aria-invalid={Boolean(errors.question_text)}
            aria-describedby={errors.question_text ? questionErrorId : undefined}
            className="mt-3 block min-h-44 w-full resize-y rounded-[var(--pv-radius-control)] border border-[var(--pv-border)] bg-[var(--pv-surface)] px-4 py-3 text-[15px] leading-6 text-[var(--pv-text-strong)] shadow-none outline-none placeholder:text-[var(--pv-text-faint)] focus:border-[var(--pv-accent)] focus:ring-2 focus:ring-[var(--pv-accent-soft)]"
            placeholder="Describe the privacy issue or decision that needs attention."
            {...register("question_text")}
          />
          {errors.question_text ? (
            <p id={questionErrorId} className="mt-2 text-[13px] leading-5 text-[var(--pv-critical)]">
              {errors.question_text.message}
            </p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="question-context"
            className="block text-sm font-semibold leading-5 text-[var(--pv-text-strong)]"
          >
            Additional context <span className="font-normal text-[var(--pv-text-muted)]">(optional)</span>
          </label>
          <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
            Add facts, timing, or background that will help the consultant understand the work.
          </p>
          <textarea
            id="question-context"
            rows={6}
            aria-invalid={Boolean(errors.context)}
            aria-describedby={errors.context ? contextErrorId : undefined}
            className="mt-3 block min-h-36 w-full resize-y rounded-[var(--pv-radius-control)] border border-[var(--pv-border)] bg-[var(--pv-surface)] px-4 py-3 text-sm leading-6 text-[var(--pv-text)] shadow-none outline-none placeholder:text-[var(--pv-text-faint)] focus:border-[var(--pv-accent)] focus:ring-2 focus:ring-[var(--pv-accent-soft)]"
            placeholder="Include any useful background."
            {...register("context")}
          />
          {errors.context ? (
            <p id={contextErrorId} className="mt-2 text-[13px] leading-5 text-[var(--pv-critical)]">
              {errors.context.message}
            </p>
          ) : null}
        </div>

        {serverProblem ? (
          <p
            className="rounded-[var(--pv-radius-control)] border border-[color-mix(in_srgb,var(--pv-critical)_20%,var(--pv-border))] bg-[var(--pv-critical-soft)] p-3 text-[13px] leading-5 text-[var(--pv-critical)]"
            role="alert"
          >
            {serverProblem}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-[var(--pv-divider)] bg-[var(--pv-surface-subtle)] px-5 py-4 sm:flex-row sm:justify-end sm:px-8">
        <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button variant="primary" type="submit" disabled={isSubmitting}>
          {isSubmitting ? (
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          ) : null}
          {isSubmitting ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
