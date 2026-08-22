import { redirect } from "next/navigation";

import { ApplicationShell } from "@/components/workspace/application-shell";
import { WorkspaceState } from "@/components/workspace/workspace-state";
import { getServerApplicationContext } from "@/lib/application-context/server";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const allowLocalE2EContext =
    process.env.NODE_ENV !== "production" &&
    process.env.PRIVEXA_E2E_AUTH_BYPASS === "true";
  const result = await getServerApplicationContext();
  if (!result.ok) {
    if (result.status === 401) {
      redirect(`/sign-in?reason=${encodeURIComponent(result.problem.code)}`);
    }
    return <WorkspaceState kind={result.status === 403 ? "unavailable" : "temporary"} />;
  }

  return (
    <ApplicationShell
      context={result.context}
      enforceSessionValidity={!allowLocalE2EContext}
    >
      {result.context.state === "ACTIVE_CLIENT" ? (
        children
      ) : result.context.state === "CLIENT_SELECTION_REQUIRED" ? (
        <main className="workspace-state-page" aria-labelledby="choose-client-title">
          <section className="workspace-state-card">
            <p className="workspace-eyebrow">Client context required</p>
            <h1 id="choose-client-title" className="workspace-state-title">
              Choose where you are working
            </h1>
            <p className="workspace-state-copy">
              Select an authorised client from the header. Privexa will verify the choice before
              opening the workspace.
            </p>
          </section>
        </main>
      ) : (
        <WorkspaceState kind="no-clients" />
      )}
    </ApplicationShell>
  );
}
