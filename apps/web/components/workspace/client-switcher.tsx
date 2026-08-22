"use client";

import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronsUpDown, LoaderCircle, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { replaceWorkspaceLocation } from "@/components/workspace/workspace-navigation";
import type { ClientSummary } from "@/lib/application-context/types";

const SEARCH_THRESHOLD = 8;

interface ClientSwitcherProps {
  activeClient: ClientSummary | null;
  clients: ClientSummary[];
  selectionRequired?: boolean;
}

export function ClientSwitcher({
  activeClient,
  clients,
  selectionRequired = false,
}: ClientSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [switchingTo, setSwitchingTo] = useState<ClientSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const filteredClients = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized
      ? clients.filter((client) => client.display_name.toLocaleLowerCase().includes(normalized))
      : clients;
  }, [clients, query]);

  useEffect(() => {
    if (!switchingTo) return;
    const shell = document.querySelector<HTMLElement>(".workspace-shell");
    if (!shell) return;
    const previousAriaHidden = shell.getAttribute("aria-hidden");
    const previousOverflow = document.body.style.overflow;
    shell.inert = true;
    shell.setAttribute("inert", "");
    shell.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "hidden";
    return () => {
      shell.inert = false;
      shell.removeAttribute("inert");
      if (previousAriaHidden === null) shell.removeAttribute("aria-hidden");
      else shell.setAttribute("aria-hidden", previousAriaHidden);
      document.body.style.overflow = previousOverflow;
    };
  }, [switchingTo]);

  if (clients.length === 1 && activeClient && !selectionRequired) {
    return (
      <div className="min-w-0" aria-label={`Active client: ${activeClient.display_name}`}>
        <span className="workspace-context-label">Client workspace</span>
        <span className="workspace-context-name" title={activeClient.display_name}>
          {activeClient.display_name}
        </span>
      </div>
    );
  }

  async function selectClient(client: ClientSummary) {
    if (switchingTo || client.id === activeClient?.id) {
      setOpen(false);
      return;
    }
    setProblem(null);
    setSwitchingTo(client);
    setOpen(false);

    try {
      const response = await fetch(`/api/application-context/active-client/${client.id}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
      });
      if (response.ok) {
        replaceWorkspaceLocation(window.location.href);
        return;
      }
      if (response.status === 401) {
        replaceWorkspaceLocation("/sign-in?reason=SESSION_EXPIRED");
        return;
      }
      if (response.status === 404 || response.status === 403 || response.status === 400) {
        setSwitchingTo(null);
        setProblem("That client workspace is no longer available to your account.");
        return;
      }
      replaceWorkspaceLocation(window.location.href);
    } catch {
      // The server may have committed the change before the connection failed. Reloading is the
      // only safe way to reconcile display state with the authoritative session selection.
      replaceWorkspaceLocation(window.location.href);
    }
  }

  function moveOptionFocus(currentIndex: number, direction: 1 | -1) {
    if (filteredClients.length === 0) return;
    const nextIndex = (currentIndex + direction + filteredClients.length) % filteredClients.length;
    optionRefs.current[nextIndex]?.focus();
  }

  const triggerLabel = activeClient?.display_name ?? "Choose a client";

  return (
    <>
      <Popover.Root
        modal
        open={open}
        onOpenChange={(nextOpen) => {
          if (switchingTo) return;
          setOpen(nextOpen);
          if (!nextOpen) setQuery("");
        }}
      >
        <Popover.Trigger asChild>
          <button
            type="button"
            className="workspace-switcher-trigger"
            aria-label={`Active client: ${triggerLabel}. Change client workspace`}
            disabled={Boolean(switchingTo)}
          >
            <span className="min-w-0 text-left">
              <span className="workspace-context-label">Client workspace</span>
              <span className="workspace-context-name" title={triggerLabel}>
                {triggerLabel}
              </span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-[var(--pv-text-muted)]" aria-hidden />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className="workspace-switcher-content"
            sideOffset={8}
            align="start"
            collisionPadding={16}
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[var(--pv-divider)] px-4 py-3">
              <div>
                <h2 id={titleId} className="text-sm font-semibold text-[var(--pv-text-strong)]">
                  Change client workspace
                </h2>
                <p id={descriptionId} className="mt-1 text-xs leading-5 text-[var(--pv-text-muted)]">
                  Your working context changes after verification.
                </p>
              </div>
              <Popover.Close className="icon-button" aria-label="Close client switcher">
                <X className="size-4" aria-hidden />
              </Popover.Close>
            </div>
            {clients.length >= SEARCH_THRESHOLD ? (
              <label className="relative block px-3 pt-3">
                <span className="sr-only">Search client workspaces</span>
                <Search
                  className="pointer-events-none absolute left-6 top-6 size-4 text-[var(--pv-text-muted)]"
                  aria-hidden
                />
                <input
                  autoFocus
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search clients"
                  className="workspace-search-input"
                />
              </label>
            ) : null}
            <div
              className="workspace-options"
              role="listbox"
              aria-label="Authorised client workspaces"
            >
              {filteredClients.map((client, index) => {
                const selected = client.id === activeClient?.id;
                return (
                  <button
                    key={client.id}
                    ref={(element) => {
                      optionRefs.current[index] = element;
                    }}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className="workspace-option"
                    onClick={() => void selectClient(client)}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                        event.preventDefault();
                        moveOptionFocus(index, event.key === "ArrowDown" ? 1 : -1);
                      }
                    }}
                  >
                    <span className="truncate" title={client.display_name}>
                      {client.display_name}
                    </span>
                    {selected ? <Check className="size-4 shrink-0" aria-hidden /> : null}
                  </button>
                );
              })}
              {filteredClients.length === 0 ? (
                <p className="px-3 py-8 text-center text-sm text-[var(--pv-text-muted)]">
                  No clients match your search.
                </p>
              ) : null}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      {problem ? (
        <p className="workspace-switch-error" role="alert">
          {problem}
        </p>
      ) : null}

      {switchingTo && typeof document !== "undefined"
        ? createPortal(
            <div className="workspace-transition" role="status" aria-live="assertive">
              <div className="workspace-transition-card">
                <span className="workspace-transition-icon" aria-hidden>
                  <ShieldCheck className="size-5" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-[var(--pv-text-strong)]">
                    Changing client workspace
                  </p>
                  <p className="mt-1 max-w-xs truncate text-sm text-[var(--pv-text-muted)]">
                    Verifying access to {switchingTo.display_name}…
                  </p>
                </div>
                <LoaderCircle
                  className="ml-auto size-5 animate-spin text-[var(--pv-accent)]"
                  aria-hidden
                />
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
