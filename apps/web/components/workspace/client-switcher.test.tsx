import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ClientSummary } from "@/lib/application-context/types";

import { ClientSwitcher } from "./client-switcher";

const navigation = vi.hoisted(() => ({ replaceWorkspaceLocation: vi.fn() }));

vi.mock("./workspace-navigation", () => navigation);

const apollo = {
  id: "00000000-0000-4000-8000-000000000002",
  display_name: "Apollo Finance",
};
const acme = {
  id: "00000000-0000-4000-8000-000000000009",
  display_name: "Acme Healthcare",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ClientSwitcher", () => {
  it("renders one active client as context, not a misleading control", () => {
    render(<ClientSwitcher activeClient={apollo} clients={[apollo]} />);

    expect(screen.getByLabelText("Active client: Apollo Finance")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not optimistically change the visible client when a switch is rejected", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClientSwitcher activeClient={apollo} clients={[apollo, acme]} />);

    await userEvent.click(screen.getByRole("button", { name: /Active client: Apollo Finance/i }));
    await userEvent.click(screen.getByRole("option", { name: "Acme Healthcare" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That client workspace is no longer available",
    );
    expect(screen.getByRole("button", { name: /Active client: Apollo Finance/i })).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/application-context/active-client/${acme.id}`,
      expect.objectContaining({ method: "PUT", credentials: "same-origin" }),
    );
    expect(navigation.replaceWorkspaceLocation).not.toHaveBeenCalled();
  });

  it("revalidates from the authoritative server after a successful switch", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClientSwitcher activeClient={apollo} clients={[apollo, acme]} />);

    await userEvent.click(screen.getByRole("button", { name: /Active client: Apollo Finance/i }));
    await userEvent.click(screen.getByRole("option", { name: "Acme Healthcare" }));

    await waitFor(() =>
      expect(navigation.replaceWorkspaceLocation).toHaveBeenCalledWith(window.location.href),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("Verifying access to Acme Healthcare");
  });

  it("removes the protected shell and routes to sign-in when switching finds an expired session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    const { container } = render(
      <div className="workspace-shell">
        <p>Apollo confidential workspace</p>
        <ClientSwitcher activeClient={apollo} clients={[apollo, acme]} />
      </div>,
    );

    await userEvent.click(screen.getByRole("button", { name: /Active client: Apollo Finance/i }));
    await userEvent.click(screen.getByRole("option", { name: "Acme Healthcare" }));

    await waitFor(() =>
      expect(navigation.replaceWorkspaceLocation).toHaveBeenCalledWith(
        "/sign-in?reason=SESSION_EXPIRED",
      ),
    );
    expect(container.querySelector(".workspace-shell")).toHaveAttribute("aria-hidden", "true");
  });

  it("makes stale workspace content inert until authority is reconciled", async () => {
    let resolveRequest: ((value: { ok: false; status: number }) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveRequest = resolve;
          }),
      ),
    );
    const { container } = render(
      <div className="workspace-shell">
        <button type="button">Existing client action</button>
        <ClientSwitcher activeClient={apollo} clients={[apollo, acme]} />
      </div>,
    );

    await userEvent.click(screen.getByRole("button", { name: /Active client: Apollo Finance/i }));
    await userEvent.click(screen.getByRole("option", { name: "Acme Healthcare" }));

    const shell = container.querySelector<HTMLElement>(".workspace-shell");
    expect(shell).toHaveAttribute("inert");
    expect(shell).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Changing client workspace");

    await act(async () => resolveRequest?.({ ok: false, status: 404 }));
    await waitFor(() => expect(shell).not.toHaveAttribute("inert"));
    expect(shell).not.toHaveAttribute("aria-hidden");
  });

  it("adds search for a long authorised list and supports arrow-key option movement", async () => {
    const clients: ClientSummary[] = Array.from({ length: 8 }, (_, index) => ({
      id: `00000000-0000-4000-8000-0000000000${String(index + 10).padStart(2, "0")}`,
      display_name: `Client ${index + 1}`,
    }));
    render(<ClientSwitcher activeClient={clients[0]} clients={clients} />);

    await userEvent.click(screen.getByRole("button", { name: /Active client: Client 1/i }));
    const search = screen.getByRole("textbox", { name: "Search client workspaces" });
    expect(search).toHaveFocus();
    await userEvent.type(search, "Client 6");
    expect(screen.getByRole("option", { name: "Client 6" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Client 1" })).not.toBeInTheDocument();

    search.focus();
    await userEvent.keyboard("{Tab}");
    const onlyOption = screen.getByRole("option", { name: "Client 6" });
    await waitFor(() => expect(onlyOption).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    expect(onlyOption).toHaveFocus();
  });

  it("filters authorised clients with case-insensitive substring matching", async () => {
    const clients: ClientSummary[] = [
      apollo,
      acme,
      ...Array.from({ length: 6 }, (_, index) => ({
        id: `00000000-0000-4000-8000-0000000001${String(index).padStart(2, "0")}`,
        display_name: `Practice Client ${index + 1}`,
      })),
    ];
    render(<ClientSwitcher activeClient={apollo} clients={clients} />);

    await userEvent.click(screen.getByRole("button", { name: /Active client: Apollo Finance/i }));
    const search = screen.getByRole("textbox", { name: "Search client workspaces" });

    for (const query of ["apollo", "Apollo", "finance", "FINANCE"]) {
      await userEvent.clear(search);
      await userEvent.type(search, query);
      expect(screen.getByRole("option", { name: "Apollo Finance" })).toBeInTheDocument();
      expect(screen.queryByRole("option", { name: "Acme Healthcare" })).not.toBeInTheDocument();
    }
  });

  it("supports escape dismissal and restores focus to the switch trigger", async () => {
    render(<ClientSwitcher activeClient={apollo} clients={[apollo, acme]} />);
    const trigger = screen.getByRole("button", { name: /Active client: Apollo Finance/i });
    trigger.focus();

    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("listbox", { name: "Authorised client workspaces" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(trigger).toHaveFocus());
    expect(
      screen.queryByRole("listbox", { name: "Authorised client workspaces" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a single unselected client operable until the server establishes context", async () => {
    render(
      <ClientSwitcher
        activeClient={null}
        clients={[apollo]}
        selectionRequired
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "Active client: Choose a client. Change client workspace",
    });
    expect(trigger).toBeEnabled();
    await userEvent.click(trigger);
    expect(screen.getByRole("option", { name: "Apollo Finance" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("keeps long client identity accessible without making it authoritative browser state", async () => {
    const longClient = {
      id: "00000000-0000-4000-8000-000000000099",
      display_name:
        "Apollo Finance International Consumer Lending and Digital Payments Private Limited",
    };
    render(<ClientSwitcher activeClient={longClient} clients={[longClient, acme]} />);

    const trigger = screen.getByRole("button", {
      name: `Active client: ${longClient.display_name}. Change client workspace`,
    });
    expect(trigger).toBeInTheDocument();
    expect(screen.getByTitle(longClient.display_name)).toHaveTextContent(longClient.display_name);
  });
});
