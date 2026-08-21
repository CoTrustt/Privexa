import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { getServerSession } from "@/lib/auth/server-session";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSession();
  if (!result.ok) {
    redirect(`/sign-in?reason=${encodeURIComponent(result.problem.code)}`);
  }

  const initials = result.session.display_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <div className="min-h-screen bg-[var(--canvas)]">
      <header className="border-b border-[var(--pv-border)] bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <span className="text-lg font-semibold tracking-[-0.025em] text-[var(--pv-text-strong)]">
            Privexa
          </span>
          <div className="flex items-center gap-2 sm:gap-4">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium">{result.session.display_name}</p>
              <p className="text-xs text-[var(--pv-text-muted)]">{result.session.firm_name}</p>
            </div>
            <span
              className="grid size-9 place-items-center rounded-full bg-[var(--pv-surface-strong)] text-xs font-semibold text-[var(--pv-text)]"
              aria-hidden="true"
            >
              {initials}
            </span>
            <SignOutButton />
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
