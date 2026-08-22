import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfessionalObjectMetadataList } from "./metadata-list";

afterEach(cleanup);

describe("ProfessionalObjectMetadataList", () => {
  it("renders identifiers, actors, timestamps, and missing values without leaking literals", () => {
    render(
      <ProfessionalObjectMetadataList
        items={[
          { id: "id", label: "Object ID", value: { kind: "identifier", value: "full-uuid" } },
          {
            id: "actor",
            label: "Last changed by",
            value: {
              kind: "actor",
              value: { membershipId: "member-1", displayName: null },
            },
          },
          { id: "date", label: "Last changed", value: { kind: "timestamp", value: "invalid" } },
          { id: "empty", label: "Optional", value: { kind: "empty" } },
        ]}
      />,
    );

    expect(screen.getByText("full-uuid").tagName).toBe("CODE");
    expect(screen.getByText("Former or unavailable member")).toBeInTheDocument();
    expect(screen.getByText("Date unavailable")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("Invalid Date");
    expect(document.body).not.toHaveTextContent("undefined");
  });

  it("uses a machine-readable time element for valid audit chronology", () => {
    render(
      <ProfessionalObjectMetadataList
        items={[
          {
            id: "date",
            label: "Created",
            value: { kind: "timestamp", value: "2026-08-22T09:20:00.000Z" },
          },
        ]}
      />,
    );

    expect(screen.getByText(/22 Aug 2026/).closest("time")).toHaveAttribute(
      "datetime",
      "2026-08-22T09:20:00.000Z",
    );
  });
});
