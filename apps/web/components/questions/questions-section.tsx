import Link from "next/link";
import type { Route } from "next";

import { QuestionCreateSheet } from "@/components/questions/question-create-sheet";
import { QuestionList } from "@/components/questions/question-list";
import { QuestionsSectionError } from "@/components/questions/question-states";
import { buttonVariants } from "@/components/ui/button";
import type { QuestionList as QuestionListContract, QuestionProblem } from "@/lib/questions/contracts";

export function QuestionsSection({
  clientId,
  clientName,
  openQuestions,
  hasAnyQuestions,
  canCreate,
  problem,
}: {
  clientId: string;
  clientName: string;
  openQuestions: QuestionListContract | null;
  hasAnyQuestions: boolean;
  canCreate: boolean;
  problem?: QuestionProblem;
}) {
  return (
    <section className="mt-12 max-w-4xl border-t border-[var(--pv-divider)] pt-7" aria-labelledby="questions-title">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 id="questions-title" className="text-xl font-semibold leading-7 tracking-[-0.025em] text-[var(--pv-text-strong)]">
            Questions
          </h2>
          <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
            Privacy work that still needs a professional outcome.
          </p>
        </div>
        {canCreate ? <QuestionCreateSheet clientId={clientId} clientName={clientName} /> : null}
      </div>

      <div className="mt-6 rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-5 sm:p-6">
        {problem ? (
          <QuestionsSectionError detail={problem.detail} />
        ) : openQuestions && openQuestions.items.length > 0 ? (
          <QuestionList questions={openQuestions.items} />
        ) : (
          <div className="py-3">
            <p className="text-[15px] font-semibold leading-6 text-[var(--pv-text-strong)]">
              No open privacy questions.
            </p>
            <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
              {hasAnyQuestions
                ? "Previous questions remain available in the full list."
                : "Add a question when the client needs privacy help."}
            </p>
          </div>
        )}
      </div>

      {hasAnyQuestions || Boolean(openQuestions?.page.has_more) ? (
        <div className="mt-4">
          <Link
            href={`/clients/${clientId}/questions` as Route}
            className={buttonVariants({ variant: "tertiary", size: "compact" })}
          >
            View all questions
          </Link>
        </div>
      ) : null}
    </section>
  );
}
