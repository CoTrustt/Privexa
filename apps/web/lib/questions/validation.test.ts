import { describe, expect, it } from "vitest";

import {
  deriveQuestionTitle,
  normalizeQuestionContext,
  questionDraftSchema,
  titleForEditedQuestion,
} from "./validation";

describe("Question validation", () => {
  it("requires meaningful question text while allowing empty optional context", () => {
    expect(questionDraftSchema.safeParse({ question_text: " \n\t ", context: "" }).success).toBe(false);
    expect(questionDraftSchema.safeParse({ question_text: "May we retain this data?", context: "" }).success).toBe(true);
  });

  it("uses backend-compatible Unicode code-point limits", () => {
    const accepted = "😀".repeat(20_000);
    expect(questionDraftSchema.safeParse({ question_text: accepted, context: "" }).success).toBe(true);
    expect(questionDraftSchema.safeParse({ question_text: `${accepted}😀`, context: "" }).success).toBe(false);
    expect(
      questionDraftSchema.safeParse({
        question_text: "May we retain this data?",
        context: " ".repeat(50_001),
      }).success,
    ).toBe(false);
  });

  it("derives a restrained title without changing authored text", () => {
    const text = `\n  ${"a".repeat(300)}  \nSecond line`;
    expect(Array.from(deriveQuestionTitle(text))).toHaveLength(255);
    expect(deriveQuestionTitle(text)).toBe("a".repeat(255));
  });

  it("preserves manual titles and updates UI-derived titles", () => {
    expect(titleForEditedQuestion("Old question", "Old question", "New question")).toBe("New question");
    expect(titleForEditedQuestion("Manual summary", "Old question", "New question")).toBe("Manual summary");
    expect(normalizeQuestionContext("   ")).toBeNull();
    expect(normalizeQuestionContext("  keep this  ")).toBe("  keep this  ");
  });
});
