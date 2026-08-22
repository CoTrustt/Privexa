import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApplicationContextResult } from "@/lib/application-context/types";

import WorkspaceLayout from "./layout";

const mocks = vi.hoisted(() => ({
  contextResult: null as ApplicationContextResult | null,
  redirect: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (target: string) => {
    mocks.redirect(target);
    throw new Error(`NEXT_REDIRECT:${target}`);
  },
}));
vi.mock("@/lib/application-context/server", () => ({
  getServerApplicationContext: async () => mocks.contextResult,
}));
vi.mock("@/components/workspace/application-shell", () => ({
  ApplicationShell: ({ children }: { children: React.ReactNode }) => <div data-testid="shell">{children}</div>,
}));
vi.mock("@/components/workspace/workspace-state", () => ({
  WorkspaceState: ({ kind }: { kind: string }) => <main>{kind} state</main>,
}));

const activeResult: ApplicationContextResult = {
  ok: true,
  context: {
    state: "ACTIVE_CLIENT",
    user: { id: "user-1", display_name: "Consultant Alice" },
    firm: { id: "firm-1", display_name: "Pai Privacy Consulting" },
    active_client: { id: "client-1", display_name: "Apollo Finance" },
    authorised_clients: [{ id: "client-1", display_name: "Apollo Finance" }],
  },
};

afterEach(() => {
  cleanup();
  mocks.redirect.mockClear();
  mocks.contextResult = activeResult;
});

describe("WorkspaceLayout", () => {
  it("renders protected work only for an active canonical client", async () => {
    mocks.contextResult = activeResult;
    render(await WorkspaceLayout({ children: <p>Apollo protected work</p> }));

    expect(screen.getByTestId("shell")).toHaveTextContent("Apollo protected work");
  });

  it("renders intentional client-selection and no-client states without protected children", async () => {
    mocks.contextResult = {
      ...activeResult,
      context: { ...activeResult.context, state: "CLIENT_SELECTION_REQUIRED", active_client: null },
    };
    const { rerender } = render(await WorkspaceLayout({ children: <p>Protected work</p> }));
    expect(screen.getByRole("heading", { name: "Choose where you are working" })).toBeInTheDocument();
    expect(screen.queryByText("Protected work")).not.toBeInTheDocument();

    mocks.contextResult = {
      ...activeResult,
      context: {
        ...activeResult.context,
        state: "NO_AUTHORISED_CLIENTS",
        active_client: null,
        authorised_clients: [],
      },
    };
    rerender(await WorkspaceLayout({ children: <p>Protected work</p> }));
    expect(screen.getByText("no-clients state")).toBeInTheDocument();
    expect(screen.queryByText("Protected work")).not.toBeInTheDocument();
  });

  it("distinguishes authorization unavailability from a temporary context failure", async () => {
    mocks.contextResult = {
      ok: false,
      status: 403,
      problem: { code: "MEMBERSHIP_INACTIVE", detail: "Unavailable" },
    };
    const { rerender } = render(await WorkspaceLayout({ children: <p>Protected work</p> }));
    expect(screen.getByText("unavailable state")).toBeInTheDocument();

    mocks.contextResult = {
      ok: false,
      status: 503,
      problem: { code: "APPLICATION_CONTEXT_UNAVAILABLE", detail: "Temporary" },
    };
    rerender(await WorkspaceLayout({ children: <p>Protected work</p> }));
    expect(screen.getByText("temporary state")).toBeInTheDocument();
  });

  it("redirects authentication expiry before rendering any protected shell", async () => {
    mocks.contextResult = {
      ok: false,
      status: 401,
      problem: { code: "SESSION_EXPIRED", detail: "Session expired" },
    };

    await expect(WorkspaceLayout({ children: <p>Apollo protected work</p> })).rejects.toThrow(
      "NEXT_REDIRECT",
    );
    expect(mocks.redirect).toHaveBeenCalledWith("/sign-in?reason=SESSION_EXPIRED");
    expect(screen.queryByText("Apollo protected work")).not.toBeInTheDocument();
  });
});
