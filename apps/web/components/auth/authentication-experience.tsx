"use client";

import {
  StytchB2B,
  useStytchB2BClient,
  useStytchMemberSession,
} from "@stytch/nextjs/b2b";
import { AlertCircle, CheckCircle2, CircleEllipsis, LockKeyhole } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { copyForProblem } from "@/lib/auth/problem-copy";
import {
  clearRememberedReturnTo,
  rememberReturnTo,
  safeReturnTo,
} from "@/lib/auth/return-to";
import { buildStytchConfig, stytchPresentation } from "@/lib/auth/stytch-config";
import type { AuthenticationProblem } from "@/lib/auth/types";

type Props = {
  callback?: boolean;
  reason?: string;
  returnTo?: string;
  signedOut?: boolean;
};

function ProcessingState() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center text-center" role="status">
      <span className="flex size-10 items-center justify-center rounded-[10px] bg-[var(--pv-accent-soft)] text-[var(--pv-accent-text)]">
        <CircleEllipsis className="size-5" aria-hidden="true" />
      </span>
      <p className="mt-5 text-[15px] font-semibold leading-[22px]">Confirming your session</p>
      <p className="mt-2 max-w-xs text-[13px] leading-[18px] text-[var(--pv-text-muted)]">
        Checking your firm membership and access.
      </p>
    </div>
  );
}

export function AuthenticationExperience({
  callback = false,
  reason,
  returnTo,
  signedOut = false,
}: Props) {
  const stytch = useStytchB2BClient();
  const { session, isInitialized, fromCache } = useStytchMemberSession();
  const [problem, setProblem] = useState<string | null>(reason ? copyForProblem(reason) : null);
  const [providerFailed, setProviderFailed] = useState(false);
  const [validationAttempt, setValidationAttempt] = useState(0);
  const destination = safeReturnTo(returnTo);

  const config = useMemo(() => {
    return buildStytchConfig({
      appUrl: process.env.NEXT_PUBLIC_APP_URL ?? window.location.origin,
      destination,
      sessionDurationMinutes: Number(
        process.env.NEXT_PUBLIC_STYTCH_SESSION_DURATION_MINUTES ?? "480",
      ),
    });
  }, [destination]);

  useEffect(() => {
    if (!callback) rememberReturnTo(destination);
  }, [callback, destination]);

  useEffect(() => {
    if (!isInitialized || fromCache || !session) {
      return;
    }

    const controller = new AbortController();

    void fetch("/api/auth/session", {
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.ok) {
          clearRememberedReturnTo();
          window.location.assign(destination);
          return;
        }

        const result = (await response.json()) as AuthenticationProblem;
        setProblem(copyForProblem(result.code));
        if (response.status === 401 || response.status === 403) {
          setProviderFailed(true);
          await stytch.session.revoke().catch(() => undefined);
        }
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setProblem(copyForProblem("AUTHENTICATION_SERVICE_UNAVAILABLE"));
        }
      });

    return () => controller.abort();
  }, [destination, fromCache, isInitialized, session, stytch, validationAttempt]);

  const isProcessing = !isInitialized || fromCache || Boolean(session);
  const canRetryVerification = Boolean(problem && session);

  return (
    <main className="flex min-h-screen flex-col bg-[var(--pv-canvas)] px-5 py-6 sm:px-8 sm:py-8">
      <header className="mx-auto flex w-full max-w-6xl items-center">
        <span className="text-lg font-semibold tracking-[-0.025em] text-[var(--pv-text-strong)]">
          Privexa
        </span>
      </header>

      <section className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-16 py-10 lg:grid-cols-[minmax(0,1fr)_400px] lg:py-16">
        <div className="hidden max-w-xl lg:block">
          <p className="font-mono text-xs font-medium leading-4 text-[var(--pv-accent-text)]">
            Private firm workspace
          </p>
          <p className="mt-5 max-w-lg text-[32px] font-semibold leading-10 tracking-[-0.035em] text-[var(--pv-text-strong)]">
            Privacy intelligence, under professional control.
          </p>
          <p className="mt-5 max-w-lg text-[15px] leading-[24px] text-[var(--pv-text)]">
            Work with client context, evidence, and professional decisions inside the right firm
            boundary.
          </p>
          <p className="mt-10 text-[13px] leading-[18px] text-[var(--pv-text-muted)]">
            Ask. Decide. Prove.
          </p>
        </div>

        <div className="mx-auto w-full max-w-[400px] lg:mx-0">
          <div className="mb-6 text-left">
            <p className="font-mono text-xs font-medium leading-4 text-[var(--pv-accent-text)] lg:hidden">
              Private firm workspace
            </p>
            <h1 className="mt-3 text-[28px] font-semibold leading-9 tracking-[-0.035em] text-[var(--pv-text-strong)] lg:mt-0">
              {callback ? "Completing sign-in" : "Sign in to your firm"}
            </h1>
            <p className="mt-3 max-w-sm text-[15px] leading-[22px] text-[var(--pv-text-muted)]">
              {callback
                ? "Privexa is confirming your membership before opening the workspace."
                : "Enter your work email and we’ll send you a secure sign-in link."}
            </p>
          </div>

          {signedOut && !problem ? (
            <div
              className="mb-4 flex gap-3 rounded-[10px] border border-[#cfe7db] bg-[var(--pv-success-soft)] p-4 text-[13px] leading-[18px] text-[var(--pv-success)]"
              role="status"
            >
              <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />
              <p>You’re signed out. Your Privexa session has ended.</p>
            </div>
          ) : null}

          {problem ? (
            <div
              className="mb-4 flex gap-3 rounded-[10px] border border-[#f2c9c5] bg-[var(--pv-critical-soft)] p-4 text-[13px] leading-[18px] text-[var(--pv-critical)]"
              role="alert"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
              <p>{problem}</p>
            </div>
          ) : null}

          <div className="rounded-[12px] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-5 sm:p-6">
            {canRetryVerification ? (
              <div className="flex min-h-48 flex-col items-center justify-center text-center">
                <p className="text-[13px] leading-[20px] text-[var(--pv-text-muted)]">
                  Your secure session exists, but Privexa could not verify your firm access.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setProblem(null);
                    setValidationAttempt((attempt) => attempt + 1);
                  }}
                  className="mt-5 inline-flex min-h-11 items-center justify-center rounded-[10px] bg-[var(--pv-accent)] px-5 text-sm font-semibold text-white transition-colors duration-150 hover:bg-[var(--pv-accent-hover)]"
                >
                  Try verification again
                </button>
              </div>
            ) : providerFailed ? (
              <div className="flex min-h-48 flex-col items-center justify-center text-center">
                <p className="max-w-xs text-[13px] leading-[20px] text-[var(--pv-text-muted)]">
                  Request a new secure link, or use another provisioned account.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setProblem(null);
                    setProviderFailed(false);
                  }}
                  className="mt-5 inline-flex min-h-11 items-center justify-center rounded-[10px] bg-[var(--pv-accent)] px-5 text-sm font-semibold text-white transition-colors duration-150 hover:bg-[var(--pv-accent-hover)]"
                >
                  Return to sign in
                </button>
              </div>
            ) : isProcessing ? (
              <ProcessingState />
            ) : (
              <StytchB2B
                config={config}
                presentation={stytchPresentation}
                callbacks={{
                  onError: () => {
                    setProblem("We could not complete that sign-in. Please try again.");
                    setProviderFailed(true);
                  },
                }}
              />
            )}
          </div>

          <div className="mt-4 flex items-start gap-2 text-[12px] leading-4 text-[var(--pv-text-muted)]">
            <LockKeyhole className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            <p>Access is limited to members provisioned by your firm.</p>
          </div>
        </div>
      </section>

      <footer className="mx-auto flex w-full max-w-6xl items-center justify-between text-[12px] leading-4 text-[var(--pv-text-faint)]">
        <span>© {new Date().getFullYear()} Privexa</span>
        <span className="hidden sm:inline">Private by design</span>
      </footer>
    </main>
  );
}
