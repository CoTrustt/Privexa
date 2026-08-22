"use client";

import { useStytchMemberSession } from "@stytch/nextjs/b2b";
import { LogIn } from "lucide-react";
import Link from "next/link";

export function SessionValidityGuard({ children }: Readonly<{ children: React.ReactNode }>) {
  const { session, isInitialized, fromCache } = useStytchMemberSession();

  if (isInitialized && !fromCache && !session) {
    return (
      <main className="workspace-state-page" aria-labelledby="session-expired-title">
        <section className="workspace-state-card" role="alert">
          <span className="workspace-state-icon" aria-hidden>
            <LogIn className="size-5" />
          </span>
          <p className="workspace-eyebrow">Session ended</p>
          <h1 id="session-expired-title" className="workspace-state-title">
            Sign in to return to your work
          </h1>
          <p className="workspace-state-copy">
            Your authenticated workspace has been removed from view. Sign in again to establish a
            new secure session.
          </p>
          <Link className="workspace-primary-action" href="/sign-in?reason=SESSION_EXPIRED">
            Sign in again
          </Link>
        </section>
      </main>
    );
  }

  return children;
}
