import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionValidityGuard } from "./session-validity-guard";

const stytchSession = vi.hoisted(() => ({
  value: { session: { member_session_id: "session-1" } as object | null, isInitialized: true, fromCache: false },
}));

vi.mock("@stytch/nextjs/b2b", () => ({
  useStytchMemberSession: () => stytchSession.value,
}));

afterEach(() => {
  cleanup();
  stytchSession.value = {
    session: { member_session_id: "session-1" },
    isInitialized: true,
    fromCache: false,
  };
});

describe("SessionValidityGuard", () => {
  it("removes stale client content when the validated member session expires", () => {
    const { rerender } = render(
      <SessionValidityGuard>
        <button type="button">Apollo confidential action</button>
      </SessionValidityGuard>,
    );
    expect(screen.getByRole("button", { name: "Apollo confidential action" })).toBeInTheDocument();

    stytchSession.value = { session: null, isInitialized: true, fromCache: false };
    rerender(
      <SessionValidityGuard>
        <button type="button">Apollo confidential action</button>
      </SessionValidityGuard>,
    );

    expect(screen.queryByText("Apollo confidential action")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Your authenticated workspace has been removed");
    expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute(
      "href",
      "/sign-in?reason=SESSION_EXPIRED",
    );
  });

  it("does not treat an unverified cached absence as definitive expiry", () => {
    stytchSession.value = { session: null, isInitialized: true, fromCache: true };
    render(
      <SessionValidityGuard>
        <p>Server-authorised shell</p>
      </SessionValidityGuard>,
    );

    expect(screen.getByText("Server-authorised shell")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
