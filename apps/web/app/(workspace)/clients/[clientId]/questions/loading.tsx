import { QuestionsSectionSkeleton } from "@/components/questions/question-states";

export default function QuestionsLoading() {
  return (
    <main className="workspace-main">
      <div className="mx-auto max-w-5xl" aria-busy="true">
        <span className="workspace-skeleton block h-4 w-40" aria-hidden />
        <span className="workspace-skeleton mt-4 block h-10 w-56" aria-hidden />
        <QuestionsSectionSkeleton />
      </div>
    </main>
  );
}
