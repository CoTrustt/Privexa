import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfessionalObjectHistoryList } from "./object-history-list";

afterEach(cleanup);

describe("ProfessionalObjectHistoryList", () => {
  it("preserves actor, action, exact timestamp, description, and version chronology", () => {
    render(
      <ProfessionalObjectHistoryList
        entries={[
          {
            id: "history-1",
            action: "Decision approved",
            description: "The professional approved the documented conditions.",
            occurredAt: "2026-08-22T09:20:00.000Z",
            actor: { membershipId: "member-1", displayName: "Asha Rao" },
            version: 8,
          },
          {
            id: "history-2",
            action: "System record imported",
            occurredAt: "invalid",
            actor: null,
          },
        ]}
      />,
    );

    expect(screen.getByText("Decision approved")).toBeInTheDocument();
    expect(screen.getByText(/Asha Rao/)).toHaveTextContent("Version 8");
    expect(screen.getByText(/22 Aug 2026/).closest("time")).toHaveAttribute(
      "datetime",
      "2026-08-22T09:20:00.000Z",
    );
    expect(screen.getByText("Actor unavailable")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("Invalid Date");
  });
});
