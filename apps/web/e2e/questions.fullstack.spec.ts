import { expect, test } from "@playwright/test";

import { expectNoAccessibilityViolations } from "./support/professional-object";

const appOrigin = "http://127.0.0.1:3200";
const apolloClientId = "00000000-0000-4000-8000-000000000002";

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    {
      name: "stytch_session",
      value: "alice-token",
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
});

test("persists the complete Question workflow and blocks cross-client attacks", async ({ page }) => {
  const originalQuestion =
    "May Apollo Finance retain customer-support recordings for quality review?";
  const editedQuestion =
    "May Apollo Finance retain support recordings for quality and dispute review?";

  await page.goto("/");
  await page
    .getByRole("button", { name: /Active client: Choose a client\. Change client workspace/ })
    .click();
  await page.getByRole("option", { name: "Apollo Finance" }).click();

  const questions = page.getByRole("region", { name: "Questions" });
  await expect(questions.getByText("No open privacy questions.")).toBeVisible();
  await questions.getByRole("button", { name: "Add question" }).click();
  await page.getByLabel("What does Apollo Finance need help with?").fill(originalQuestion);
  await page
    .getByLabel(/Additional context/)
    .fill("The proposed retention period is twelve months for Indian customer calls.");
  await page.getByRole("button", { name: "Add question" }).last().click();

  await expect(page).toHaveURL(/\/clients\/[^/]+\/questions\/[^/]+$/);
  const questionUrl = page.url();
  const questionId = new URL(questionUrl).pathname.split("/").at(-1);
  expect(questionId).toBeTruthy();
  await expect(page.getByRole("heading", { level: 1, name: originalQuestion })).toBeVisible();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: originalQuestion })).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Question").fill(editedQuestion);
  await page.getByLabel(/Additional context/).fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { level: 1, name: editedQuestion })).toBeVisible();
  await expect(page.getByText("No additional context was added.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: editedQuestion })).toBeVisible();
  await page.getByRole("button", { name: "Resolve question" }).click();
  await expect(page.getByLabel("Status: Resolved").first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Status: Resolved").first()).toBeVisible();
  await page.getByRole("button", { name: "Reopen question" }).click();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page
    .getByRole("button", { name: /Active client: Apollo Finance\. Change client workspace/ })
    .click();
  await page.getByRole("option", { name: "Acme Healthcare" }).click();
  await expect(page.getByRole("heading", { name: "This question is not available" })).toBeVisible();
  await expect(page.getByText(editedQuestion)).toHaveCount(0);

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Acme Healthcare" })).toBeVisible();

  await page.goto(questionUrl);
  await expect(page.getByRole("heading", { name: "This question is not available" })).toBeVisible();
  await expect(page.getByText(editedQuestion)).toHaveCount(0);

  const attackHeaders = { Origin: appOrigin, "Content-Type": "application/json" };
  const editAttack = await page.request.patch(
    `${appOrigin}/api/clients/${apolloClientId}/questions/${questionId}`,
    {
      headers: attackHeaders,
      data: {
        expected_version: 4,
        title: "Compromised",
        question_text: "Compromised",
        context: null,
      },
    },
  );
  expect(editAttack.status()).toBe(404);
  const statusAttack = await page.request.post(
    `${appOrigin}/api/clients/${apolloClientId}/questions/${questionId}/resolve`,
    { headers: attackHeaders, data: { expected_version: 4 } },
  );
  expect(statusAttack.status()).toBe(404);

  await page.goto("/");
  await page
    .getByRole("button", { name: /Active client: Acme Healthcare\. Change client workspace/ })
    .click();
  await page.getByRole("option", { name: "Apollo Finance" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Apollo Finance" })).toBeVisible();
  await page.goto(questionUrl);
  await expect(page.getByRole("heading", { level: 1, name: editedQuestion })).toBeVisible();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
});
