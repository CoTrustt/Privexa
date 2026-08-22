import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfessionalObjectStatusLabel } from "./professional-object-status";

afterEach(cleanup);

describe("ProfessionalObjectStatusLabel", () => {
  it("communicates state with text and an accessible label", () => {
    render(
      <ProfessionalObjectStatusLabel
        status={{ key: "IN_REVIEW", label: "In review", tone: "attention" }}
      />,
    );

    expect(screen.getByLabelText("Status: In review")).toHaveTextContent("In review");
  });

  it("renders a presenter-supplied future state without requiring a universal enum", () => {
    render(
      <ProfessionalObjectStatusLabel
        status={{
          key: "AWAITING_RECONCILIATION",
          label: "Awaiting reconciliation",
          tone: "neutral",
        }}
      />,
    );

    expect(screen.getByText("Awaiting reconciliation")).toBeInTheDocument();
  });
});
