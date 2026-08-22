"use client";

import { LoaderCircle } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ProfessionalObjectConfirmation } from "@/lib/professional-objects/view-model";

export function ConfirmationDialog({
  confirmation,
  open,
  pending,
  error,
  onOpenChange,
  onConfirm,
  onReturnFocus,
}: {
  confirmation: ProfessionalObjectConfirmation;
  open: boolean;
  pending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onReturnFocus?: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}>
      <DialogContent
        showClose={!pending}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          window.requestAnimationFrame(() => cancelRef.current?.focus());
        }}
        onCloseAutoFocus={(event) => {
          if (!onReturnFocus) return;
          event.preventDefault();
          onReturnFocus();
        }}
      >
        <DialogTitle className="pr-10 text-xl font-semibold leading-7 tracking-[-0.025em] text-[var(--pv-text-strong)]">
          {confirmation.title}
        </DialogTitle>
        <DialogDescription className="mt-3 text-sm leading-6 text-[var(--pv-text-muted)]">
          {confirmation.description}
        </DialogDescription>
        {error ? (
          <p className="mt-4 rounded-[10px] bg-[var(--pv-critical-soft)] p-3 text-[13px] leading-5 text-[var(--pv-critical)]" role="alert">
            {error}
          </p>
        ) : null}
        <div className="mt-7 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <DialogClose asChild>
            <Button ref={cancelRef} variant="secondary" disabled={pending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant={confirmation.tone === "destructive" ? "destructive" : "primary"}
            onClick={onConfirm}
            disabled={pending}
          >
            {pending ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : null}
            {pending ? "Working…" : confirmation.confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
