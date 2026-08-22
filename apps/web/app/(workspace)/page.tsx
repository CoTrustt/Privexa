import { ShieldCheck } from "lucide-react";

export default function HomePage() {
  return (
    <main className="workspace-main">
      <div className="max-w-2xl">
        <p className="workspace-eyebrow">Home</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[var(--pv-text-strong)] sm:text-4xl">
          Client workspace established
        </h1>
        <p className="mt-4 max-w-xl text-base leading-7 text-[var(--pv-text-muted)]">
          Your authenticated firm and client context is active. Future professional work will open
          inside this verified boundary.
        </p>
      </div>
      <section className="mt-10 max-w-2xl border-t border-[var(--pv-divider)] pt-6" aria-label="Context status">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-[8px] bg-[var(--pv-success-soft)] text-[var(--pv-success)]">
            <ShieldCheck className="size-4" aria-hidden />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[var(--pv-text-strong)]">Secure context active</h2>
            <p className="mt-1 text-sm leading-6 text-[var(--pv-text-muted)]">
              The client shown above is resolved by Privexa and revalidated on every protected
              request.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
