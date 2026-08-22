import { expect, test } from "@playwright/test";

import {
  establishLocalSession,
  expectNoAccessibilityViolations,
  fixtureClientName,
} from "./support/professional-object";

test.beforeEach(async ({ context, request }) => {
  await request.post("http://127.0.0.1:4010/__test__/reset-questions");
  await establishLocalSession(context);
});

test("creates, reopens, edits, resolves, and reopens a persisted client Question", async ({
  page,
}) => {
  const originalQuestion = "May Apollo Finance retain customer-support recordings for quality review?";
  const editedQuestion = "May Apollo Finance retain support recordings for quality and dispute review?";

  await page.goto("/");
  const questions = page.getByRole("region", { name: "Questions" });
  await expect(questions.getByText("No open privacy questions.")).toBeVisible();
  await questions.getByRole("button", { name: "Add question" }).click();

  const createPrompt = page.getByLabel(`What does ${fixtureClientName} need help with?`);
  await expect(createPrompt).toBeFocused();
  await createPrompt.fill(originalQuestion);
  await page.getByLabel(/Additional context/).fill(
    "The support team proposes a twelve-month retention period for Indian customer calls.",
  );
  await page.getByRole("button", { name: "Add question" }).last().click();

  await expect(page).toHaveURL(/\/clients\/[^/]+\/questions\/[^/]+$/);
  const questionUrl = page.url();
  await expect(page.getByRole("heading", { level: 1, name: originalQuestion })).toBeVisible();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
  await expect(page.getByText(/twelve-month retention period/)).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: originalQuestion })).toBeVisible();

  await page.goto("/");
  await questions.getByRole("link", { name: new RegExp(originalQuestion) }).click();
  await expect(page).toHaveURL(questionUrl);
  await page.getByRole("button", { name: "Edit" }).click();
  const editor = page.getByLabel("Question");
  await editor.fill(editedQuestion);
  await page.getByLabel(/Additional context/).fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { level: 1, name: editedQuestion })).toBeVisible();
  await expect(page.getByText("No additional context was added.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: editedQuestion })).toBeVisible();
  await expect(page.getByText("No additional context was added.")).toBeVisible();
  await page.getByRole("button", { name: "Resolve question" }).click();
  await expect(page.getByLabel("Status: Resolved").first()).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Status: Resolved").first()).toBeVisible();
  await page.goto("/");
  await expect(questions.getByText("No open privacy questions.")).toBeVisible();
  await questions.getByRole("link", { name: "View all questions" }).click();
  await page.getByRole("link", { name: new RegExp(editedQuestion) }).click();
  await page.getByRole("button", { name: "Reopen question" }).click();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();

  await expectNoAccessibilityViolations(page);

  const questionId = new URL(questionUrl).pathname.split("/").at(-1);
  await page.goto(`/clients/93000000-0000-4000-8000-000000000099/questions/${questionId}`);
  await expect(page.getByRole("heading", { name: "This question is not available" })).toBeVisible();
  await expect(page.getByText(editedQuestion)).toHaveCount(0);
});

test("keeps the creation workflow usable on a narrow mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/");
  await page.getByRole("region", { name: "Questions" }).getByRole("button", { name: "Add question" }).click();
  await expect(page.getByRole("dialog", { name: "Add question" })).toBeVisible();
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth);
  await expectNoAccessibilityViolations(page);
});

test("preserves a failed create for a single successful retry", async ({ page, request }) => {
  const questionText = "Can Apollo Finance retain unsuccessful application records?";
  const contextText = "The proposed retention period is eighteen months.";
  await request.post("http://127.0.0.1:4010/__test__/fail-next-question-mutation");

  await page.goto("/");
  await page.getByRole("region", { name: "Questions" }).getByRole("button", { name: "Add question" }).click();
  const question = page.getByLabel(`What does ${fixtureClientName} need help with?`);
  const context = page.getByLabel(/Additional context/);
  await question.fill(questionText);
  await context.fill(contextText);
  await page.getByRole("button", { name: "Add question" }).last().click();

  await expect(page.getByRole("alert")).toContainText("could not be saved");
  await expect(question).toHaveValue(questionText);
  await expect(context).toHaveValue(contextText);
  await page.getByRole("button", { name: "Add question" }).last().click();
  await expect(page).toHaveURL(/\/clients\/[^/]+\/questions\/[^/]+$/);

  await page.goto("/");
  await expect(page.getByRole("region", { name: "Questions" }).getByRole("link", { name: new RegExp(questionText) })).toHaveCount(1);
});

test("requires explicit confirmation before discarding a creation draft", async ({ page }) => {
  await page.goto("/");
  const questions = page.getByRole("region", { name: "Questions" });
  const addQuestion = questions.getByRole("button", { name: "Add question" });
  await addQuestion.click();
  await page.getByLabel(`What does ${fixtureClientName} need help with?`).fill("Unsaved privacy question");
  await page.getByRole("button", { name: "Cancel" }).click();

  const confirmation = page.getByRole("dialog", { name: "Discard this question?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog", { name: "Add question" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Discard question" }).click();

  await expect(page.getByRole("dialog", { name: "Add question" })).toHaveCount(0);
  await expect(addQuestion).toBeFocused();
  await expect(questions.getByText("No open privacy questions.")).toBeVisible();
});
