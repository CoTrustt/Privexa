"use client";

import { Plus } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/feedback/confirmation-dialog";
import { QuestionForm, type QuestionFormResult } from "@/components/questions/question-form";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { questionProblem, questionSchema } from "@/lib/questions/contracts";
import type { QuestionDraft } from "@/lib/questions/validation";
import { replaceWorkspaceLocation } from "@/components/workspace/workspace-navigation";

export function QuestionCreateSheet({
  clientId,
  clientName,
}: {
  clientId: string;
  clientName: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  function requestClose() {
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    setOpen(false);
  }

  async function create(draft: QuestionDraft): Promise<QuestionFormResult> {
    try {
      const response = await fetch(`/api/clients/${clientId}/questions`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const body: unknown = await response.json().catch(() => null);
      if (response.status === 401) {
        replaceWorkspaceLocation("/sign-in?reason=SESSION_EXPIRED");
        return { ok: false, message: "Your session expired. Sign in to continue." };
      }
      if (!response.ok) {
        return {
          ok: false,
          message: questionProblem(body, "The question could not be created right now.").detail,
        };
      }
      const parsed = questionSchema.safeParse(body);
      if (!parsed.success) {
        return { ok: false, message: "The question was saved, but its page could not be opened. Refresh the Overview." };
      }
      setDirty(false);
      router.push(`/clients/${clientId}/questions/${parsed.data.id}` as Route);
      router.refresh();
      return { ok: true };
    } catch {
      return {
        ok: false,
        message: "The question could not be created right now. Your work is unchanged.",
      };
    }
  }

  return (
    <>
      <Sheet
        open={open}
        onOpenChange={(nextOpen) => {
          if (nextOpen) setOpen(true);
          else requestClose();
        }}
      >
        <SheetTrigger asChild>
          <Button variant="primary">
            <Plus className="size-4" aria-hidden /> Add question
          </Button>
        </SheetTrigger>
        <SheetContent
          showClose={false}
          className="flex flex-col"
          onInteractOutside={(event) => dirty && event.preventDefault()}
        >
          <div className="border-b border-[var(--pv-divider)] px-5 py-5 sm:px-8">
            <SheetTitle className="text-xl font-semibold leading-7 tracking-[-0.025em] text-[var(--pv-text-strong)]">
              Add question
            </SheetTitle>
            <SheetDescription className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
              {clientName} client workspace
            </SheetDescription>
          </div>
          <QuestionForm
            autoFocus
            prompt={`What does ${clientName} need help with?`}
            submitLabel="Add question"
            onSubmit={create}
            onCancel={requestClose}
            onDirtyChange={setDirty}
          />
        </SheetContent>
      </Sheet>

      <ConfirmationDialog
        confirmation={{
          title: "Discard this question?",
          description: "The text you entered has not been saved.",
          confirmLabel: "Discard question",
          tone: "destructive",
        }}
        open={confirmDiscard}
        pending={false}
        error={null}
        onOpenChange={setConfirmDiscard}
        onConfirm={() => {
          setConfirmDiscard(false);
          setDirty(false);
          setOpen(false);
        }}
      />
    </>
  );
}
