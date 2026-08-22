import type { Question } from "@/lib/questions/contracts";

export function QuestionContent({ question }: { question: Question }) {
  const titleContainsFullQuestion = question.title === question.question_text;
  return (
    <div className="space-y-8">
      {!titleContainsFullQuestion ? (
        <section aria-labelledby="question-content-title">
          <h2 id="question-content-title" className="text-sm font-semibold leading-5 text-[var(--pv-text-strong)]">
            Question
          </h2>
          <p className="mt-3 whitespace-pre-wrap break-words text-[17px] leading-7 text-[var(--pv-text-strong)] [overflow-wrap:anywhere]">
            {question.question_text}
          </p>
        </section>
      ) : null}
      <section aria-labelledby="question-context-title">
        <h2 id="question-context-title" className="text-sm font-semibold leading-5 text-[var(--pv-text-strong)]">
          Context
        </h2>
        {question.context ? (
          <p className="mt-3 whitespace-pre-wrap break-words text-[15px] leading-7 text-[var(--pv-text)] [overflow-wrap:anywhere]">
            {question.context}
          </p>
        ) : (
          <p className="mt-2 text-[13px] leading-5 text-[var(--pv-text-muted)]">
            No additional context was added.
          </p>
        )}
      </section>
    </div>
  );
}
