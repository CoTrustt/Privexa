"use client";

import { Ellipsis, LoaderCircle } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useId, useRef, useState } from "react";

import { ConfirmationDialog } from "@/components/feedback/confirmation-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isSafeInternalHref } from "@/lib/professional-objects/object-types";
import type { ProfessionalObjectAction } from "@/lib/professional-objects/view-model";
import { cn } from "@/lib/ui/cn";

export type ProfessionalObjectActionResult =
  | { ok: true }
  | { ok: false; message: string };

function buttonVariant(action: ProfessionalObjectAction) {
  if (action.emphasis === "primary") return "primary" as const;
  if (action.emphasis === "destructive") return "destructive" as const;
  if (action.emphasis === "tertiary") return "tertiary" as const;
  return "secondary" as const;
}

export function ProfessionalObjectActions({
  actions,
  onAction,
}: {
  actions: ProfessionalObjectAction[];
  onAction?: (action: ProfessionalObjectAction) => Promise<ProfessionalObjectActionResult>;
}) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmationAction, setConfirmationAction] = useState<ProfessionalObjectAction | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const reasonId = useId();
  const overflowTriggerRef = useRef<HTMLButtonElement>(null);
  const confirmationReturnFocusRef = useRef<HTMLElement | null>(null);

  if (actions.length === 0) return null;

  const directActions = actions
    .filter((action) => action.emphasis === "primary" || action.emphasis === "secondary")
    .slice(0, 2);
  const directIds = new Set(directActions.map((action) => action.id));
  const overflowActions = actions.filter((action) => !directIds.has(action.id));

  async function execute(action: ProfessionalObjectAction) {
    if (pendingId || action.availability !== "available" || !onAction) return;
    if (action.confirmation && confirmationAction?.id !== action.id) {
      setProblem(null);
      setConfirmationAction(action);
      return;
    }
    setPendingId(action.id);
    setProblem(null);
    const result = await onAction(action).catch(() => ({
      ok: false as const,
      message: "The action could not be completed. Try again.",
    }));
    setPendingId(null);
    if (result.ok) {
      setConfirmationAction(null);
      return;
    }
    setProblem(result.message);
  }

  function actionDisabled(action: ProfessionalObjectAction) {
    return (
      action.availability !== "available" ||
      pendingId !== null ||
      (action.kind === "command" && !onAction) ||
      (action.kind === "navigate" && !isSafeInternalHref(action.href))
    );
  }

  function directAction(action: ProfessionalObjectAction) {
    if (
      action.kind === "navigate" &&
      isSafeInternalHref(action.href) &&
      action.availability === "available"
    ) {
      return (
        <Link
          key={action.id}
          href={action.href as Route}
          className={buttonVariants({ variant: buttonVariant(action) })}
        >
          {action.label}
        </Link>
      );
    }
    const disabled = actionDisabled(action);
    return (
      <Button
        key={action.id}
        variant={buttonVariant(action)}
        disabled={disabled}
        onClick={(event) => {
          confirmationReturnFocusRef.current = event.currentTarget;
          void execute(action);
        }}
        aria-describedby={action.disabledReason ? reasonId : undefined}
        className={cn(action.emphasis !== "primary" && "max-sm:hidden")}
      >
        {pendingId === action.id ? (
          <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        ) : null}
        {pendingId === action.id ? "Working…" : action.label}
      </Button>
    );
  }

  const explainedAction = actions.find((action) => action.disabledReason);

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
      {directActions.map(directAction)}
      {overflowActions.length > 0 ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              ref={overflowTriggerRef}
              variant="secondary"
              size="icon"
              aria-label="More object actions"
              disabled={pendingId !== null}
            >
              <Ellipsis className="size-4" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {overflowActions.map((action) => {
              const navigable =
                action.kind === "navigate" &&
                action.availability === "available" &&
                isSafeInternalHref(action.href);
              return navigable ? (
                <DropdownMenuItem
                  key={action.id}
                  asChild
                  destructive={action.emphasis === "destructive"}
                >
                  <Link href={action.href as Route}>{action.label}</Link>
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem
                  key={action.id}
                  destructive={action.emphasis === "destructive"}
                  disabled={actionDisabled(action)}
                  onSelect={() => {
                    confirmationReturnFocusRef.current = overflowTriggerRef.current;
                    if (action.confirmation) {
                      setProblem(null);
                      window.requestAnimationFrame(() => setConfirmationAction(action));
                      return;
                    }
                    void execute(action);
                  }}
                >
                  {action.label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
      {explainedAction?.disabledReason ? (
        <p id={reasonId} className="basis-full text-right text-xs leading-5 text-[var(--pv-text-muted)]">
          {explainedAction.disabledReason}
        </p>
      ) : null}
      {problem && !confirmationAction ? (
        <p className="basis-full text-right text-xs leading-5 text-[var(--pv-critical)]" role="alert">
          {problem}
        </p>
      ) : null}
      {confirmationAction?.confirmation ? (
        <ConfirmationDialog
          confirmation={confirmationAction.confirmation}
          open
          pending={pendingId === confirmationAction.id}
          error={problem}
          onOpenChange={(open) => {
            if (!open) {
              setConfirmationAction(null);
              setProblem(null);
            }
          }}
          onConfirm={() => void execute(confirmationAction)}
          onReturnFocus={() => confirmationReturnFocusRef.current?.focus()}
        />
      ) : null}
    </div>
  );
}
