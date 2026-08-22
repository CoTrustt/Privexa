import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Question } from "@/lib/questions/contracts";

import { QuestionContent } from "./question-content";

afterEach(cleanup);

const question: Question = {
  id: "10000000-0000-4000-8000-000000000001",
  client_id: "20000000-0000-4000-8000-000000000001",
  title: "Markup-looking privacy question",
  question_text: '<script>window.__questionExecuted = true</script>\nMay we retain A&B\'s data?',
  context: '<img src=x onerror="window.__contextExecuted = true">',
  status: "OPEN",
  version: 1,
  created_by_membership_id: "30000000-0000-4000-8000-000000000001",
  updated_by_membership_id: "30000000-0000-4000-8000-000000000001",
  created_at: "2026-08-22T10:00:00Z",
  updated_at: "2026-08-22T10:00:00Z",
};

describe("QuestionContent", () => {
  it("renders authored markup-like content only as text", () => {
    const { container } = render(<QuestionContent question={question} />);

    expect(screen.getByText(/<script>window\.__questionExecuted/)).toBeInTheDocument();
    expect(screen.getByText(/<img src=x onerror/)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});
