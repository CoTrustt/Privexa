import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { decisionFixture, evidenceFixture, fixtureWorkspace } from "@/fixtures/professional-objects";

import { ProfessionalObjectShell } from "./professional-object-shell";

afterEach(cleanup);

function renderShell(page = evidenceFixture) {
  return render(
    <ProfessionalObjectShell
      page={page}
      activeFirmId={fixtureWorkspace.firmId}
      activeWorkspaceId={fixtureWorkspace.id}
    >
      <section aria-label="Fixture domain content">Authoritative domain body</section>
    </ProfessionalObjectShell>,
  );
}

describe("ProfessionalObjectShell", () => {
  it("keeps workspace, object identity, state, body, and inspector in one interaction frame", () => {
    renderShell();

    expect(screen.getByRole("heading", { level: 1, name: evidenceFixture.object.title })).toBeInTheDocument();
    expect(screen.getAllByText("Apollo Finance").length).toBeGreaterThan(0);
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Status: In review").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Fixture domain content")).toHaveTextContent("Authoritative domain body");
    expect(screen.getByRole("complementary", { name: "Record inspector" })).toBeInTheDocument();
  });

  it("reuses the same page architecture for a different professional object type", () => {
    renderShell(decisionFixture);

    expect(screen.getByRole("heading", { level: 1, name: decisionFixture.object.title })).toBeInTheDocument();
    expect(screen.getAllByText("Decision").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText("Status: Approved").length).toBeGreaterThan(0);
  });

  it("fails closed before rendering content when Firm or Client Workspace scope differs", () => {
    render(
      <ProfessionalObjectShell
        page={evidenceFixture}
        activeFirmId="10000000-0000-4000-8000-000000000099"
        activeWorkspaceId={fixtureWorkspace.id}
      >
        <p>Confidential object content</p>
      </ProfessionalObjectShell>,
    );

    expect(screen.getByRole("heading", { name: "This record is not available to you" })).toBeInTheDocument();
    expect(screen.queryByText("Confidential object content")).not.toBeInTheDocument();
    expect(screen.queryByText(evidenceFixture.object.title)).not.toBeInTheDocument();
  });
});
