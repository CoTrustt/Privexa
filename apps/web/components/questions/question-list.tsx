import Link from "next/link";
import type { Route } from "next";

import { ProfessionalObjectStatusLabel } from "@/components/professional-object/professional-object-status";
import { formatProfessionalTimestamp } from "@/lib/professional-objects/date-time";
import { professionalObjectHref } from "@/lib/professional-objects/object-types";
import type { Question } from "@/lib/questions/contracts";
import { presentQuestionStatus } from "@/lib/questions/presenter";

export function QuestionList({ questions }: { questions: Question[] }) {
  return (
    <ul className="divide-y divide-[var(--pv-divider)]" aria-label="Privacy questions">
      {questions.map((question) => {
        const created = formatProfessionalTimestamp(question.created_at);
        return (
          <li key={question.id}>
            <Link
              href={professionalObjectHref(question.client_id, "question", question.id) as Route}
              className="group flex min-w-0 flex-col gap-3 py-5 text-left no-underline first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between"
            >
              <span className="min-w-0">
                <span className="block break-words text-[15px] font-semibold leading-6 text-[var(--pv-text-strong)] [overflow-wrap:anywhere] group-hover:text-[var(--pv-accent-text)]">
                  {question.title}
                </span>
                {created ? (
                  <time
                    dateTime={created.dateTime}
                    className="mt-1 block text-xs leading-5 text-[var(--pv-text-muted)]"
                  >
                    Created {created.label}
                  </time>
                ) : null}
              </span>
              <ProfessionalObjectStatusLabel
                compact
                status={presentQuestionStatus(question.status)}
                className="shrink-0"
              />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
