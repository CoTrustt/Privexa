import { PrivexaWordmark } from "@/components/brand/privexa-wordmark";

export default function WorkspaceLoading() {
  return (
    <div className="workspace-shell" role="status" aria-label="Establishing secure workspace">
      <header className="workspace-header">
        <div className="workspace-header-inner">
          <PrivexaWordmark className="workspace-brand" />
          <span className="workspace-divider workspace-skeleton h-8 w-px" />
          <span className="workspace-firm workspace-skeleton h-8 w-32" />
          <span className="workspace-context-slot workspace-skeleton ml-auto h-10 w-52 max-w-full" />
          <span className="workspace-skeleton size-10 rounded-full" />
        </div>
        <div className="workspace-nav h-11" />
      </header>
      <main className="workspace-main">
        <span className="workspace-skeleton block h-4 w-16" />
        <span className="workspace-skeleton mt-4 block h-10 w-80 max-w-full" />
        <span className="workspace-skeleton mt-4 block h-5 w-[32rem] max-w-full" />
      </main>
      <span className="sr-only">Establishing secure workspace…</span>
    </div>
  );
}
