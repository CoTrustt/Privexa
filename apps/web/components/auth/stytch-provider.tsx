"use client";

import { createStytchB2BClient, StytchB2BProvider } from "@stytch/nextjs/b2b";

import { PrivexaWordmark } from "@/components/brand/privexa-wordmark";

const publicToken = process.env.NEXT_PUBLIC_STYTCH_PUBLIC_TOKEN;
const customBaseUrl = process.env.NEXT_PUBLIC_STYTCH_CUSTOM_BASE_URL;
const client = publicToken
  ? createStytchB2BClient(publicToken, {
      ...(customBaseUrl ? { customBaseUrl } : {}),
      cookieOptions: { path: "/" },
    })
  : null;

export function StytchProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  if (!client) {
    return (
      <main className="grid min-h-screen place-items-center px-6">
        <section className="max-w-md rounded-[12px] border border-[var(--pv-border)] bg-[var(--pv-surface)] p-8">
          <PrivexaWordmark className="text-[22px] font-semibold tracking-[-0.025em] text-[var(--pv-text-strong)]" />
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">
            Authentication is not configured
          </h1>
          <p className="mt-3 text-sm leading-6 text-[var(--pv-text-muted)]">
            Set NEXT_PUBLIC_STYTCH_PUBLIC_TOKEN and restart the web application. No sign-in
            request has been sent.
          </p>
        </section>
      </main>
    );
  }

  return <StytchB2BProvider stytch={client}>{children}</StytchB2BProvider>;
}
