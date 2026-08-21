"use client";

import { useStytchB2BClient } from "@stytch/nextjs/b2b";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SignOutButton() {
  const stytch = useStytchB2BClient();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function signOut() {
    if (busy) return;
    setBusy(true);
    setProblem(null);

    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Sign-out failed");
      await stytch.session.revoke().catch(() => undefined);
      router.replace("/sign-in?signedOut=1");
      router.refresh();
    } catch {
      setBusy(false);
      setProblem("Could not sign out. Try again.");
    }
  }

  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="inline-flex min-h-11 items-center gap-2 rounded-[10px] px-3 text-sm font-medium text-[var(--pv-text-muted)] transition-colors duration-150 hover:bg-[var(--pv-surface-strong)] hover:text-[var(--pv-text-strong)] disabled:cursor-wait disabled:opacity-60"
      >
        <LogOut className="size-4" aria-hidden="true" />
        <span aria-live="polite">{busy ? "Signing out…" : "Sign out"}</span>
      </button>
      {problem ? (
        <p className="mt-1 text-xs leading-4 text-[var(--pv-critical)]" role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
