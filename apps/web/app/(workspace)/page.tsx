import { ArrowRight, Scale } from "lucide-react";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-7xl px-5 py-12 sm:px-8 sm:py-16">
      <div className="max-w-2xl">
        <p className="text-sm font-medium text-[var(--accent)]">Home</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">
          Your privacy work starts here.
        </h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-[var(--ink-muted)]">
          Authentication is active. Client access is resolved separately so an empty client list
          never becomes an authentication failure.
        </p>
      </div>

      <section className="mt-12 grid max-w-3xl gap-4 sm:grid-cols-2" aria-label="Workspace status">
        <article className="rounded-2xl border border-[var(--line)] bg-white p-6">
          <Scale className="size-5 text-[var(--accent)]" aria-hidden="true" />
          <h2 className="mt-8 text-lg font-semibold">Professional judgement</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--ink-muted)]">
            Privexa prepares the work. You own every material decision.
          </p>
        </article>
        <article className="flex flex-col justify-between rounded-2xl border border-[var(--line)] bg-[#20231f] p-6 text-white">
          <div>
            <p className="text-sm text-white/60">Next capability</p>
            <h2 className="mt-2 text-lg font-semibold">Client workspaces</h2>
          </div>
          <p className="mt-8 flex items-center gap-2 text-sm text-white/70">
            Available when provisioned <ArrowRight className="size-4" aria-hidden="true" />
          </p>
        </article>
      </section>
    </main>
  );
}
