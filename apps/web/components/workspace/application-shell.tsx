import Link from "next/link";

import { PrivexaWordmark } from "@/components/brand/privexa-wordmark";
import { AccountMenu } from "@/components/workspace/account-menu";
import { ClientSwitcher } from "@/components/workspace/client-switcher";
import { SessionValidityGuard } from "@/components/workspace/session-validity-guard";
import type { ApplicationContext } from "@/lib/application-context/types";

export function ApplicationShell({
  context,
  children,
}: Readonly<{ context: ApplicationContext; children: React.ReactNode }>) {
  return (
    <SessionValidityGuard>
      <div className="workspace-shell">
        <header className="workspace-header">
          <div className="workspace-header-inner">
            <Link className="workspace-brand" href="/" aria-label="Privexa home">
              <PrivexaWordmark />
            </Link>
            <div className="workspace-divider" aria-hidden />
            <div className="workspace-firm min-w-0">
              <span>Consulting firm</span>
              <strong title={context.firm.display_name}>{context.firm.display_name}</strong>
            </div>
            <div className="workspace-context-slot">
              {context.authorised_clients.length > 0 ? (
                <ClientSwitcher
                  activeClient={context.active_client}
                  clients={context.authorised_clients}
                  selectionRequired={context.state === "CLIENT_SELECTION_REQUIRED"}
                />
              ) : (
                <div className="min-w-0" aria-label="No available client workspace">
                  <span className="workspace-context-label">Client workspace</span>
                  <span className="workspace-context-name">Not available</span>
                </div>
              )}
            </div>
            <AccountMenu displayName={context.user.display_name} />
          </div>
          <nav className="workspace-nav" aria-label="Primary navigation">
            <div className="workspace-nav-inner">
              <Link className="workspace-nav-link" href="/">
                Home
              </Link>
              <Link className="workspace-nav-link" href="/ask">
                Ask Privexa
              </Link>
            </div>
          </nav>
        </header>
        {children}
      </div>
    </SessionValidityGuard>
  );
}
