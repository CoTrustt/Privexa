"use client";

import { CheckCircle2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/feedback/confirmation-dialog";
import { QuestionContent } from "@/components/questions/question-content";
import { QuestionForm, type QuestionFormResult } from "@/components/questions/question-form";
import { ProfessionalObjectShell } from "@/components/professional-object/professional-object-shell";
import { replaceWorkspaceLocation } from "@/components/workspace/workspace-navigation";
import type { ProfessionalObjectActionResult } from "@/components/professional-object/professional-object-actions";
import { questionProblem, questionSchema, type Question } from "@/lib/questions/contracts";
import {
  normalizeQuestionContext,
  titleForEditedQuestion,
  type QuestionDraft,
} from "@/lib/questions/validation";
import type {
  ProfessionalObjectAction,
  ProfessionalObjectPageViewModel,
} from "@/lib/professional-objects/view-model";

export function QuestionDetailController({
  question,
  page,
  firmId,
  clientId,
}: {
  question: Question;
  page: ProfessionalObjectPageViewModel;
  firmId: string;
  clientId: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [editDirty, setEditDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function cancelEditing() {
    if (editDirty) {
      setConfirmDiscard(true);
      return;
    }
    setEditing(false);
  }

  async function parseMutation(response: Response): Promise<
    | { ok: true; question: Question }
    | { ok: false; message: string }
  > {
    const body: unknown = await response.json().catch(() => null);
    if (response.status === 401) {
      replaceWorkspaceLocation("/sign-in?reason=SESSION_EXPIRED");
      return { ok: false, message: "Your session expired. Sign in to continue." };
    }
    if (!response.ok) {
      const problem = questionProblem(body, "The question could not be updated right now.");
      if (problem.code === "VERSION_CONFLICT") {
        return {
          ok: false,
          message: "This question changed after you opened it. Your draft is preserved; refresh and review the latest version before saving.",
        };
      }
      if (problem.code === "LIFECYCLE_CONFLICT") {
        return {
          ok: false,
          message: "That action is no longer available for the question's current status. Refresh and try again.",
        };
      }
      return { ok: false, message: problem.detail };
    }
    const parsed = questionSchema.safeParse(body);
    return parsed.success
      ? { ok: true, question: parsed.data }
      : { ok: false, message: "The change was saved, but the refreshed question could not be read. Reload this page." };
  }

  async function save(draft: QuestionDraft): Promise<QuestionFormResult> {
    const response = await fetch(`/api/clients/${clientId}/questions/${question.id}`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_version: question.version,
        title: titleForEditedQuestion(question.title, question.question_text, draft.question_text),
        question_text: draft.question_text,
        context: normalizeQuestionContext(draft.context),
      }),
    }).catch(() => null);
    if (!response) {
      return { ok: false, message: "The question could not be saved right now. Your draft is unchanged." };
    }
    const result = await parseMutation(response);
    if (!result.ok) return result;
    setEditDirty(false);
    setEditing(false);
    setNotice("Question updated.");
    router.refresh();
    return { ok: true };
  }

  async function execute(action: ProfessionalObjectAction): Promise<ProfessionalObjectActionResult> {
    if (action.id === "edit") {
      setNotice(null);
      setEditing(true);
      return { ok: true };
    }
    if (action.id !== "resolve" && action.id !== "close" && action.id !== "reopen") {
      return { ok: false, message: "That question action is not available." };
    }
    const response = await fetch(
      `/api/clients/${clientId}/questions/${question.id}/${action.id}`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: question.version }),
      },
    ).catch(() => null);
    if (!response) {
      router.refresh();
      return {
        ok: false,
        message: "The status could not be confirmed. The page is refreshing from the saved record.",
      };
    }
    const result = await parseMutation(response);
    if (!result.ok) return result;
    setNotice(
      action.id === "resolve"
        ? "Question resolved."
        : action.id === "reopen"
          ? "Question reopened."
          : "Question closed.",
    );
    router.refresh();
    return { ok: true };
  }

  return (
    <>
      <ProfessionalObjectShell
        page={page}
        activeFirmId={firmId}
        activeWorkspaceId={clientId}
        onAction={execute}
      >
        {notice ? (
          <p className="mb-6 flex items-center gap-2 text-[13px] font-medium leading-5 text-[var(--pv-success)]" role="status">
            <CheckCircle2 className="size-4" aria-hidden /> {notice}
          </p>
        ) : null}
        {editing ? (
          <div className="-m-8 flex min-h-[34rem] flex-col max-sm:-mx-5 max-sm:-my-6">
            <div className="border-b border-[var(--pv-divider)] px-5 py-5 sm:px-8">
              <h2 className="text-lg font-semibold leading-6 text-[var(--pv-text-strong)]">Edit question</h2>
              <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
                Changes are saved only after you select Save changes.
              </p>
            </div>
            <QuestionForm
              autoFocus
              prompt="Question"
              defaultValues={{ question_text: question.question_text, context: question.context ?? "" }}
              submitLabel="Save changes"
              onSubmit={save}
              onCancel={cancelEditing}
              onDirtyChange={setEditDirty}
            />
          </div>
        ) : (
          <QuestionContent question={question} />
        )}
      </ProfessionalObjectShell>

      <ConfirmationDialog
        confirmation={{
          title: "Discard these changes?",
          description: "Your edits to this question have not been saved.",
          confirmLabel: "Discard changes",
          tone: "destructive",
        }}
        open={confirmDiscard}
        pending={false}
        error={null}
        onOpenChange={setConfirmDiscard}
        onConfirm={() => {
          setConfirmDiscard(false);
          setEditDirty(false);
          setEditing(false);
        }}
      />
    </>
  );
}
