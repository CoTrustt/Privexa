"use client";

import { PanelRight } from "lucide-react";
import { useState } from "react";

import {
  ProfessionalObjectInspectorContent,
  type ProfessionalObjectInspectorSection,
} from "@/components/professional-object/inspector-content";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { ProfessionalObjectInspectorViewModel } from "@/lib/professional-objects/view-model";

import styles from "./professional-object-shell.module.css";

export function ProfessionalObjectInspector({
  inspector,
  onRetrySection,
}: {
  inspector: ProfessionalObjectInspectorViewModel;
  onRetrySection?: (section: ProfessionalObjectInspectorSection) => Promise<void>;
}) {
  const [retryingSection, setRetryingSection] = useState<ProfessionalObjectInspectorSection | null>(null);

  async function retry(section: ProfessionalObjectInspectorSection) {
    if (!onRetrySection || retryingSection) return;
    setRetryingSection(section);
    try {
      await onRetrySection(section);
    } finally {
      setRetryingSection(null);
    }
  }

  return (
    <div className="contents">
      <aside className={styles.desktopInspector} aria-labelledby="professional-object-inspector-title">
        <h2 id="professional-object-inspector-title" className="text-base font-semibold leading-6 text-[var(--pv-text-strong)]">
          Record inspector
        </h2>
        <p className="mt-1 mb-6 text-xs leading-5 text-[var(--pv-text-muted)]">Supporting context and provenance</p>
        <ProfessionalObjectInspectorContent
          inspector={inspector}
          idPrefix="desktop-inspector"
          retryingSection={retryingSection}
          onRetrySection={onRetrySection ? (section) => void retry(section) : undefined}
        />
      </aside>

      <div className={styles.mobileInspectorControl}>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="secondary" className="w-full justify-between sm:w-auto">
              <span className="inline-flex items-center gap-2">
                <PanelRight className="size-4" aria-hidden /> Record details
              </span>
              <span className="text-xs font-medium text-[var(--pv-text-muted)]">Details · Related · History</span>
            </Button>
          </DialogTrigger>
          <DialogContent className="left-auto right-0 top-0 h-dvh max-h-none w-[min(24rem,100vw)] translate-x-0 translate-y-0 rounded-none border-y-0 border-r-0 p-0" showClose>
            <div className="border-b border-[var(--pv-divider)] px-5 py-5 pr-16">
              <DialogTitle className="text-lg font-semibold leading-6 text-[var(--pv-text-strong)]">Record inspector</DialogTitle>
              <DialogDescription className="mt-1 text-xs leading-5 text-[var(--pv-text-muted)]">
                Details, relationships, and professional history
              </DialogDescription>
            </div>
            <div className="overflow-y-auto px-5 py-6">
              <ProfessionalObjectInspectorContent
                inspector={inspector}
                idPrefix="sheet-inspector"
                retryingSection={retryingSection}
                onRetrySection={onRetrySection ? (section) => void retry(section) : undefined}
              />
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
