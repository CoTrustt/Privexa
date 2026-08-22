import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApplicationContext } from "@/lib/application-context/types";

import { ApplicationShell } from "./application-shell";

vi.mock("./session-validity-guard", () => ({
  SessionValidityGuard: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("./account-menu", () => ({
  AccountMenu: ({ displayName }: { displayName: string }) => (
    <button type="button" aria-label={`Account menu for ${displayName}`} />
  ),
}));

const context: ApplicationContext = {
  state: "ACTIVE_CLIENT",
  user: { id: "user-1", display_name: "Consultant Alice" },
  firm: { id: "firm-1", display_name: "Pai Privacy Consulting" },
  active_client: { id: "client-1", display_name: "Apollo Finance" },
  authorised_clients: [
    { id: "client-1", display_name: "Apollo Finance" },
    { id: "client-2", display_name: "Northstar Health" },
  ],
};

afterEach(cleanup);

describe("ApplicationShell", () => {
  it("keeps authoritative firm and active-client identity visible in the authenticated shell", () => {
    render(
      <ApplicationShell context={context}>
        <main>Protected work</main>
      </ApplicationShell>,
    );

    expect(screen.getByText("Pai Privacy Consulting")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Active client: Apollo Finance. Change client workspace",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Account menu for Consultant Alice" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.getByText("Protected work")).toBeInTheDocument();
  });

  it("renders the newly revalidated authoritative client after a switch reload", () => {
    const { rerender } = render(
      <ApplicationShell context={context}>
        <main>Protected work</main>
      </ApplicationShell>,
    );

    rerender(
      <ApplicationShell
        context={{
          ...context,
          active_client: { id: "client-2", display_name: "Northstar Health" },
        }}
      >
        <main>Protected work</main>
      </ApplicationShell>,
    );

    expect(
      screen.getByRole("button", {
        name: "Active client: Northstar Health. Change client workspace",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Apollo Finance")).not.toBeInTheDocument();
  });

  it("exposes only implemented navigation and no future placeholder destinations", () => {
    render(
      <ApplicationShell context={context}>
        <main>Protected work</main>
      </ApplicationShell>,
    );

    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Ask Privexa" })).toHaveAttribute("href", "/ask");
    for (const placeholder of ["RoPA", "DPIA", "Evidence", "Opinions", "AI Assistant", "Reports"]) {
      expect(navigation).not.toHaveTextContent(placeholder);
    }
  });

  it("renders an intentional unavailable client boundary when no clients are authorised", () => {
    render(
      <ApplicationShell
        context={{
          ...context,
          state: "NO_AUTHORISED_CLIENTS",
          active_client: null,
          authorised_clients: [],
        }}
      >
        <main>No-client state</main>
      </ApplicationShell>,
    );

    expect(screen.getByLabelText("No available client workspace")).toHaveTextContent(
      "Not available",
    );
    expect(screen.queryByRole("button", { name: /Change client workspace/ })).not.toBeInTheDocument();
  });
});
