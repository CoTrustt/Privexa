import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceState } from "./workspace-state";

vi.mock("@/components/auth/sign-out-button", () => ({
  SignOutButton: () => <button type="button">Sign out</button>,
}));

afterEach(cleanup);

describe("WorkspaceState", () => {
  it("keeps account recovery available in the no-authorised-client state", () => {
    render(<WorkspaceState kind="no-clients" />);

    expect(screen.getByRole("heading", { name: "No client workspace is available" })).toBeInTheDocument();
    expect(screen.getByText(/signed in/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("distinguishes unavailable authorization from a temporary backend interruption", () => {
    const { rerender } = render(<WorkspaceState kind="unavailable" />);
    expect(screen.getByRole("heading", { name: "Your workspace access is unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    rerender(<WorkspaceState kind="temporary" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Temporary interruption");
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/");
    expect(screen.queryByText(/stack|traceback/i)).not.toBeInTheDocument();
  });
});
