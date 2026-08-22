import Link from "next/link";
import type { Route } from "next";
import { notFound, redirect } from "next/navigation";

import { QuestionCreateSheet } from "@/components/questions/question-create-sheet";
import { QuestionList } from "@/components/questions/question-list";
import { QuestionsSectionError } from "@/components/questions/question-states";
import { buttonVariants } from "@/components/ui/button";
import { getServerApplicationContext } from "@/lib/application-context/server";
import { questionCapabilities } from "@/lib/application-context/types";
import type { QuestionStatus } from "@/lib/questions/contracts";
import { listQuestions } from "@/lib/questions/server";
import { cn } from "@/lib/ui/cn";

const filters = [
  { value: "all", label: "All" },
  { value: "open", label: "Open", status: "OPEN" },
  { value: "resolved", label: "Resolved", status: "RESOLVED" },
  { value: "closed", label: "Closed", status: "CLOSED" },
] as const satisfies ReadonlyArray<{ value: string; label: string; status?: QuestionStatus }>;

export default async function QuestionsPage({
  params,
  searchParams,
}: {
  params: Promise<{ clientId: string }>;
  searchParams: Promise<{ status?: string; offset?: string }>;
}) {
  const { clientId } = await params;
  const query = await searchParams;
  const selected = filters.find((filter) => filter.value === query.status) ?? filters[0];
  const selectedStatus = "status" in selected ? selected.status : undefined;
  const parsedOffset = Number.parseInt(query.offset ?? "0", 10);
  const offset = Number.isSafeInteger(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
  const contextResult = await getServerApplicationContext();
  if (!contextResult.ok) {
    if (contextResult.status === 401) redirect("/sign-in?reason=SESSION_EXPIRED");
    notFound();
  }
  const client = contextResult.context.active_client;
  if (!client || client.id !== clientId) notFound();
  const result = await listQuestions({ clientId, status: selectedStatus, limit: 50, offset });
  const capabilities = questionCapabilities(contextResult.context);

  return (
    <main className="workspace-main">
      <div className="mx-auto max-w-5xl">
        <header className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="workspace-eyebrow mt-0">{client.display_name}</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[var(--pv-text-strong)] sm:text-4xl">Questions</h1>
            <p className="mt-3 max-w-2xl text-[15px] leading-6 text-[var(--pv-text-muted)]">
              Privacy issues and decisions raised for this client.
            </p>
          </div>
          {capabilities.can_create ? <QuestionCreateSheet clientId={clientId} clientName={client.display_name} /> : null}
        </header>

        <nav className="mt-8 flex flex-wrap gap-1 border-b border-[var(--pv-divider)]" aria-label="Filter questions">
          {filters.map((filter) => {
            const active = filter.value === selected.value;
            return (
              <Link
                key={filter.value}
                href={`/clients/${clientId}/questions${filter.value === "all" ? "" : `?status=${filter.value}`}` as Route}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "border-b-2 px-3 py-3 text-sm font-semibold no-underline",
                  active ? "border-[var(--pv-accent)] text-[var(--pv-text-strong)]" : "border-transparent text-[var(--pv-text-muted)] hover:text-[var(--pv-text-strong)]",
                )}
              >
                {filter.label}
              </Link>
            );
          })}
        </nav>

        <section className="mt-7 rounded-[var(--pv-radius-card)] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-5 sm:p-7" aria-label={`${selected.label} questions`}>
          {!result.ok ? (
            <QuestionsSectionError detail={result.problem.detail} />
          ) : result.data.items.length > 0 ? (
            <QuestionList questions={result.data.items} />
          ) : (
            <div className="py-8 text-center">
              <p className="text-[15px] font-semibold text-[var(--pv-text-strong)]">
                {selected.value === "all"
                  ? "No questions yet."
                  : selected.value === "open"
                    ? "No open privacy questions."
                    : `No ${selected.label.toLowerCase()} questions.`}
              </p>
              <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">
                {selected.value === "all" ? "Questions will appear here after they are added." : "Choose another status to review other questions."}
              </p>
            </div>
          )}
        </section>

        {result.ok && (offset > 0 || result.data.page.has_more) ? (
          <nav className="mt-5 flex items-center justify-between" aria-label="Question pages">
            {offset > 0 ? (
              <Link
                className={buttonVariants({ variant: "secondary", size: "compact" })}
                href={`/clients/${clientId}/questions?${new URLSearchParams({ ...(selected.value !== "all" ? { status: selected.value } : {}), offset: String(Math.max(0, offset - 50)) })}` as Route}
              >Previous</Link>
            ) : <span />}
            {result.data.page.has_more ? (
              <Link
                className={buttonVariants({ variant: "secondary", size: "compact" })}
                href={`/clients/${clientId}/questions?${new URLSearchParams({ ...(selected.value !== "all" ? { status: selected.value } : {}), offset: String(offset + 50) })}` as Route}
              >Next</Link>
            ) : null}
          </nav>
        ) : null}
      </div>
    </main>
  );
}
