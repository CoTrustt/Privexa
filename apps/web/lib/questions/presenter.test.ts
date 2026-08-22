import { describe, expect, it } from "vitest";

import type { Question } from "./contracts";
import { presentQuestionStatus, questionPageViewModel } from "./presenter";

const question: Question = {
  id: "10000000-0000-4000-8000-000000000001",
  client_id: "20000000-0000-4000-8000-000000000001",
  title: "May we retain this data?",
  question_text: "May we retain this data?",
  context: null,
  status: "OPEN",
  version: 1,
  created_by_membership_id: "30000000-0000-4000-8000-000000000001",
  updated_by_membership_id: "30000000-0000-4000-8000-000000000001",
  created_at: "2026-08-22T10:00:00Z",
  updated_at: "2026-08-22T10:00:00Z",
};

describe("Question presenter", () => {
  it("maps domain statuses to human labels and permitted commands", () => {
    expect(presentQuestionStatus("RESOLVED")).toMatchObject({ label: "Resolved", tone: "success" });
    const page = questionPageViewModel({
      question,
      firmId: "40000000-0000-4000-8000-000000000001",
      client: { id: question.client_id, display_name: "Apollo Finance" },
      canUpdate: true,
    });
    expect(page.object.actions.map((action) => action.id)).toEqual(["edit", "resolve"]);
    expect(page.inspector.details.state).toBe("ready");
  });

  it("renders a clean read-only projection without dead mutation controls", () => {
    const page = questionPageViewModel({
      question,
      firmId: "40000000-0000-4000-8000-000000000001",
      client: { id: question.client_id, display_name: "Apollo Finance" },
      canUpdate: false,
    });
    expect(page.object.capabilities.mode).toBe("read_only");
    expect(page.object.actions).toEqual([]);
  });
});
