"use client";

import * as Popover from "@radix-ui/react-popover";
import { ChevronDown, X } from "lucide-react";
import { useId } from "react";

import { SignOutButton } from "@/components/auth/sign-out-button";

function initials(displayName: string) {
  return displayName
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

export function AccountMenu({ displayName }: { displayName: string }) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <Popover.Root modal>
      <Popover.Trigger asChild>
        <button type="button" className="account-trigger" aria-label={`Account menu for ${displayName}`}>
          <span className="account-avatar" aria-hidden>
            {initials(displayName)}
          </span>
          <span className="hidden max-w-40 truncate text-sm font-medium text-[var(--pv-text-strong)] md:block">
            {displayName}
          </span>
          <ChevronDown className="hidden size-4 text-[var(--pv-text-muted)] md:block" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="account-content"
          align="end"
          sideOffset={8}
          collisionPadding={16}
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
        >
          <div className="flex items-start justify-between gap-4 border-b border-[var(--pv-divider)] px-4 py-3">
            <div className="min-w-0">
              <h2 id={titleId} className="truncate text-sm font-semibold text-[var(--pv-text-strong)]">
                {displayName}
              </h2>
              <p id={descriptionId} className="mt-1 text-xs text-[var(--pv-text-muted)]">
                Signed in to Privexa
              </p>
            </div>
            <Popover.Close className="icon-button" aria-label="Close account menu">
              <X className="size-4" aria-hidden />
            </Popover.Close>
          </div>
          <div className="p-2">
            <SignOutButton />
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
