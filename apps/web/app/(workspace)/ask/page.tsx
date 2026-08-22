import { WorkNotePreparation } from "@/components/ai/work-note-preparation";
import { getServerApplicationContext } from "@/lib/application-context/server";

export default async function AskPrivexaPage() {
  const result = await getServerApplicationContext();
  if (!result.ok || !result.context.active_client) return null;
  return (
    <main className="workspace-main">
      <div className="max-w-2xl">
        <p className="workspace-eyebrow">Ask Privexa</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[var(--pv-text-strong)] sm:text-4xl">
          Prepare a client work note
        </h1>
        <p className="mt-4 max-w-xl text-base leading-7 text-[var(--pv-text-muted)]">
          Privexa prepares candidate work. You review it and decide whether to use it.
        </p>
      </div>
      <WorkNotePreparation activeClientId={result.context.active_client.id} />
    </main>
  );
}
