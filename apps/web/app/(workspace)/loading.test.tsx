import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import WorkspaceLoading from "./loading";

describe("WorkspaceLoading", () => {
  it("uses accessible loading semantics without displaying a guessed client", () => {
    render(<WorkspaceLoading />);

    expect(screen.getByRole("status", { name: "Establishing secure workspace" })).toBeInTheDocument();
    expect(screen.getByText("Establishing secure workspace…")).toBeInTheDocument();
    expect(screen.queryByText(/Apollo|Northstar|Choose a client/)).not.toBeInTheDocument();
    expect(document.querySelector(".workspace-divider.workspace-skeleton")).toBeInTheDocument();
    expect(document.querySelector(".workspace-firm.workspace-skeleton")).toBeInTheDocument();
    expect(document.querySelector(".workspace-context-slot.workspace-skeleton")).toBeInTheDocument();
  });
});
