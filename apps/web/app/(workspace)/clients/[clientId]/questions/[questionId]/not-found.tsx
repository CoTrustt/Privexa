import Link from "next/link";

import { EyeOff } from "lucide-react";

export default function QuestionNotFound() {
  return (
    <main className="workspace-state-page" aria-labelledby="question-not-found-title">
      <section className="workspace-state-card">
        <span className="workspace-state-icon" aria-hidden>
          <EyeOff className="size-5" />
        </span>
        <p className="workspace-eyebrow">Question</p>
        <h1 id="question-not-found-title" className="workspace-state-title">This question is not available</h1>
        <p className="workspace-state-copy">
          It may no longer exist or may not be available in the active client workspace.
        </p>
        <Link href="/" className="workspace-primary-action">Return to Overview</Link>
      </section>
    </main>
  );
}
