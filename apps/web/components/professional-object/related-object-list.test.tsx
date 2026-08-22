import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RelatedProfessionalObject } from "@/lib/professional-objects/view-model";

import { RelatedProfessionalObjectList } from "./related-object-list";

afterEach(cleanup);

const items: RelatedProfessionalObject[] = [
  {
    id: "related-1",
    type: "evidence",
    title: "Available evidence",
    relationshipLabel: "Supports",
    href: "/clients/client-1/evidence/related-1",
    availability: "available",
    status: { key: "OPEN", label: "Open", tone: "information" },
  },
  {
    id: "related-2",
    type: "question",
    title: null,
    relationshipLabel: "Related record",
    availability: "restricted",
  },
  {
    id: "related-3",
    type: "evidence",
    title: null,
    relationshipLabel: "Referenced record",
    availability: "unavailable",
  },
];

describe("RelatedProfessionalObjectList", () => {
  it("uses link semantics only for an available internal relationship", () => {
    render(<RelatedProfessionalObjectList items={items} />);

    expect(screen.getByRole("link", { name: /Available evidence/ })).toHaveAttribute(
      "href",
      "/clients/client-1/evidence/related-1",
    );
    expect(screen.getByText("You do not have access to this related record.").closest("a")).toBeNull();
    expect(screen.getByText("This related record is no longer available.").closest("a")).toBeNull();
  });

  it("keeps type, title, relationship, and optional status distinguishable", () => {
    render(<RelatedProfessionalObjectList items={items.slice(0, 1)} />);

    expect(screen.getByText(/Supports · Evidence/)).toBeInTheDocument();
    expect(screen.getByText("Available evidence")).toBeInTheDocument();
    expect(screen.getByLabelText("Status: Open")).toBeInTheDocument();
  });
});
