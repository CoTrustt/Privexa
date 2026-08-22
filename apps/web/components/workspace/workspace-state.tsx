import { Building2, RefreshCw, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { SignOutButton } from "@/components/auth/sign-out-button";

type WorkspaceStateKind = "no-clients" | "unavailable" | "temporary";

const states = {
  "no-clients": {
    eyebrow: "Workspace access",
    title: "No client workspace is available",
    copy: "Your account is signed in, but it is not currently assigned to an active client workspace. Contact your firm administrator if you expected access.",
    icon: Building2,
  },
  unavailable: {
    eyebrow: "Workspace access",
    title: "Your workspace access is unavailable",
    copy: "Privexa could not establish an authorised firm workspace for this account. Contact your firm administrator if you expected access.",
    icon: ShieldAlert,
  },
  temporary: {
    eyebrow: "Temporary interruption",
    title: "Your workspace could not be established",
    copy: "Your session may still be valid. Retry to resolve your current firm and client context securely.",
    icon: RefreshCw,
  },
} as const;

export function WorkspaceState({ kind }: { kind: WorkspaceStateKind }) {
  const state = states[kind];
  const Icon = state.icon;
  return (
    <main className="workspace-state-page" aria-labelledby="workspace-state-title">
      <section className="workspace-state-card" role={kind === "temporary" ? "alert" : undefined}>
        <span className="workspace-state-icon" aria-hidden>
          <Icon className="size-5" />
        </span>
        <p className="workspace-eyebrow">{state.eyebrow}</p>
        <h1 id="workspace-state-title" className="workspace-state-title">
          {state.title}
        </h1>
        <p className="workspace-state-copy">{state.copy}</p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          {kind === "temporary" ? (
            <Link className="workspace-primary-action" href="/">
              Try again
            </Link>
          ) : null}
          <SignOutButton />
        </div>
      </section>
    </main>
  );
}
