import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

import { QuestionsSection } from "./questions-section";

afterEach(cleanup);

describe("QuestionsSection", () => {
  it("uses the required restrained empty state and authorized primary action", () => {
    render(
      <QuestionsSection
        clientId="20000000-0000-4000-8000-000000000001"
        clientName="Apollo Finance"
        openQuestions={{ items: [], page: { limit: 5, offset: 0, has_more: false } }}
        hasAnyQuestions={false}
        canCreate
      />,
    );
    expect(screen.getByRole("heading", { name: "Questions" })).toBeInTheDocument();
    expect(screen.getByText("No open privacy questions.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add question" })).toBeInTheDocument();
  });

  it("keeps read-only users free of dead mutation controls", () => {
    render(
      <QuestionsSection
        clientId="20000000-0000-4000-8000-000000000001"
        clientName="Apollo Finance"
        openQuestions={{ items: [], page: { limit: 5, offset: 0, has_more: false } }}
        hasAnyQuestions
        canCreate={false}
      />,
    );
    expect(screen.queryByRole("button", { name: "Add question" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all questions" })).toBeInTheDocument();
  });
});
