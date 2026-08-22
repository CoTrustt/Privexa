import { redirect } from "next/navigation";

import { QuestionsSection } from "@/components/questions/questions-section";
import { WorkspaceState } from "@/components/workspace/workspace-state";
import { getServerApplicationContext } from "@/lib/application-context/server";
import { questionCapabilities } from "@/lib/application-context/types";
import { listQuestions } from "@/lib/questions/server";

export default async function HomePage() {
  const contextResult = await getServerApplicationContext();
  if (!contextResult.ok) {
    if (contextResult.status === 401) redirect("/sign-in?reason=SESSION_EXPIRED");
    return <WorkspaceState kind={contextResult.status === 403 ? "unavailable" : "temporary"} />;
  }
  const client = contextResult.context.active_client;
  if (!client) return null;
  const [openResult, anyResult] = await Promise.all([
    listQuestions({ clientId: client.id, status: "OPEN", limit: 5 }),
    listQuestions({ clientId: client.id, limit: 1 }),
  ]);
  const capabilities = questionCapabilities(contextResult.context);

  return (
    <main className="workspace-main">
      <div className="max-w-3xl">
        <p className="workspace-eyebrow mt-0">Overview</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[var(--pv-text-strong)] sm:text-4xl">
          {client.display_name}
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--pv-text-muted)]">
          Current privacy work for this client workspace.
        </p>
      </div>
      <QuestionsSection
        clientId={client.id}
        clientName={client.display_name}
        openQuestions={openResult.ok ? openResult.data : null}
        hasAnyQuestions={anyResult.ok && anyResult.data.items.length > 0}
        canCreate={capabilities.can_create}
        problem={!openResult.ok ? openResult.problem : undefined}
      />
    </main>
  );
}
