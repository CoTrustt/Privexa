"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

export function QuestionsSectionSkeleton() {
  return (
    <section className="mt-12 max-w-4xl border-t border-[var(--pv-divider)] pt-7" aria-busy="true" aria-label="Loading questions">
      <span className="workspace-skeleton block h-6 w-28" aria-hidden />
      <span className="workspace-skeleton mt-5 block h-16 w-full" aria-hidden />
      <span className="workspace-skeleton mt-3 block h-16 w-full" aria-hidden />
      <span className="sr-only">Loading questions…</span>
    </section>
  );
}

export function QuestionsSectionError({ detail }: { detail: string }) {
  const router = useRouter();
  return (
    <div className="flex items-start gap-3 rounded-[var(--pv-radius-control)] bg-[var(--pv-critical-soft)] p-4" role="alert">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[var(--pv-critical)]" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-[var(--pv-critical)]">Questions are unavailable</p>
        <p className="mt-1 text-[13px] leading-5 text-[var(--pv-text-muted)]">{detail}</p>
        <Button variant="tertiary" size="compact" className="mt-2" onClick={() => router.refresh()}>
          <RotateCcw className="size-3.5" aria-hidden /> Try again
        </Button>
      </div>
    </div>
  );
}
