import { expect, test } from "@playwright/test";

import {
  establishLocalSession,
  expectNoAccessibilityViolations,
  fixtureClientName,
  professionalObjectPath,
} from "./support/professional-object";

test.beforeEach(async ({ context }) => {
  await establishLocalSession(context);
});

test("opens a standard object with one coherent professional frame", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(professionalObjectPath("evidence"));

  await expect(
    page.getByLabel(`Active client: ${fixtureClientName}`),
  ).toBeVisible();
  await expect(page.getByText(fixtureClientName, { exact: true }).last()).toBeVisible();
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Customer support platform retention and analytics configuration",
    }),
  ).toBeVisible();
  await expect(page.getByText("Evidence", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Status: In review").first()).toBeVisible();
  await expect(page.getByRole("article")).toContainText("Professional content");
  await expect(page.getByRole("complementary", { name: "Record inspector" })).toBeVisible();

  const relatedLink = page.getByRole("link", {
    name: /Customer support conversation analytics/,
  });
  await expect(relatedLink).toHaveAttribute(
    "href",
    /\/clients\/90000000-0000-4000-8000-000000000003\/processing-activities\//,
  );

  const edit = page.getByRole("button", { name: "Edit" });
  await edit.focus();
  await expect(edit).toBeFocused();
  expect(await edit.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none");

  await expectNoAccessibilityViolations(page);
});

test("keeps Evidence, Decision, and Action in the same shell without stale fixture state", async ({
  page,
}) => {
  await page.goto(professionalObjectPath("evidence"));
  await expect(page.getByRole("main").getByText("Evidence", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Decision with relationships" }).click();
  await expect(page.getByRole("main").getByText("Decision", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Status: Approved").first()).toBeVisible();

  await page.getByRole("link", { name: "Empty related and history" }).click();
  await expect(page.getByRole("main").getByText("Action", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Status: Open").first()).toBeVisible();
  await expect(page.getByText("No related records have been linked yet.").first()).toBeVisible();
  await expect(page.getByText("No changes have been recorded since creation.").first()).toBeVisible();
});

test("keeps the primary object usable through sectional failure and retry", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(professionalObjectPath("section-error"));

  await expect(page.getByRole("article")).toContainText("Professional content");
  await expect(page.getByText("Related records could not be loaded. The decision remains available.")).toBeVisible();
  const retry = page.getByRole("button", { name: "Try again" });
  await retry.click();
  await expect(page.getByRole("button", { name: "Retrying…" })).toBeDisabled();
  const recoveredRelatedLink = page.getByRole("link", {
    name: /Customer support conversation analytics/,
  });
  await expect(recoveredRelatedLink).toBeVisible();
  await expect(recoveredRelatedLink).toHaveAttribute(
    "href",
    /\/clients\/90000000-0000-4000-8000-000000000003\/processing-activities\//,
  );
});

test("recovers from a blocking object error without exposing server details", async ({ page }) => {
  await page.goto(professionalObjectPath("object-error"));

  await expect(page.getByRole("heading", { name: "This record could not be opened" })).toBeVisible();
  await expect(page.getByText("This professional record could not be loaded right now.")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Professional content restored" })).toBeVisible();
});

test("presents read-only and action-forbidden states deliberately", async ({ page }) => {
  await page.goto(professionalObjectPath("read-only"));
  await expect(page.getByText("Read-only", { exact: true }).last()).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toBeDisabled();
  await expect(page.getByText("Your current access is read-only.")).toBeVisible();

  await page.goto(professionalObjectPath("action-forbidden"));
  await expect(page.getByRole("button", { name: "Edit" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Publish as precedent" })).toBeDisabled();
  await expect(
    page.getByText("Only authorised firm reviewers can publish precedent."),
  ).toBeVisible();
});

test("shows persistent action failure and permits a retry", async ({ page }) => {
  await page.goto(professionalObjectPath("action-failure"));
  const edit = page.getByRole("button", { name: "Edit" });

  await edit.click();
  await expect(page.getByRole("button", { name: "Working…" })).toBeDisabled();
  await expect(
    page.getByText("The fixture action could not be completed. Review the record and try again."),
  ).toBeVisible();
  await expect(edit).toBeEnabled();
  await edit.click();
  await expect(
    page.getByText("The fixture action could not be completed. Review the record and try again."),
  ).toBeVisible();
});

test("confirms consequential actions with cancel, focus restoration, and explicit fixture outcome", async ({
  page,
}) => {
  await page.goto(professionalObjectPath("evidence"));
  const moreActions = page.getByRole("button", { name: "More object actions" });

  await moreActions.click();
  await page.getByRole("menuitem", { name: "Preview archive confirmation" }).click();
  const dialog = page.getByRole("dialog", { name: "Archive this professional record?" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(moreActions).toBeFocused();

  await moreActions.click();
  await page.getByRole("menuitem", { name: "Preview archive confirmation" }).click();
  await page.getByRole("button", { name: "Archive record" }).click();
  await expect(page.getByRole("button", { name: "Working…" })).toBeDisabled();
  await expect(
    page.getByText("Confirmation completed in the fixture harness. No authoritative record was changed."),
  ).toBeVisible();
});

test("rolls an optimistic failure back completely while preserving the draft", async ({ page }) => {
  await page.goto(professionalObjectPath("optimistic-failure"));
  const originalTitle = "Customer support platform retention and analytics configuration";
  const proposedTitle = "Updated retention configuration under review";
  const input = page.getByLabel("Proposed title");

  await input.fill(proposedTitle);
  await page.getByRole("button", { name: "Apply title update" }).click();
  await expect(page.getByRole("heading", { level: 1, name: proposedTitle })).toBeVisible();
  await expect(page.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await expect(
    page.getByText(
      "The title update could not be saved. The previous title has been restored and your draft is still available.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: originalTitle })).toBeVisible();
  await expect(input).toHaveValue(proposedTitle);
  await expect(page.getByRole("button", { name: "Apply title update" })).toBeEnabled();
});

test("keeps the mobile inspector keyboard reachable and focus-contained", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(professionalObjectPath("evidence"));
  const trigger = page.getByRole("button", { name: /Record details/ });

  await trigger.focus();
  await trigger.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Record inspector" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("heading", { name: "Details" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Related items" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page.getByRole("button", { name: "Close dialog" }).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.press("Enter");
  await expect(dialog).toBeVisible();
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("renders unsafe source strings as text and handles substantial inspector lists", async ({ page }) => {
  await page.goto(professionalObjectPath("unsafe-text"));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText('<script>alert("xss")</script>');
  await expect(page.locator('main img[src="x"]')).toHaveCount(0);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(professionalObjectPath("large-lists"));
  await expect(page.getByRole("complementary").getByRole("link")).toHaveCount(50);
  await expect(page.getByText("Professional assessment expanded")).toBeVisible();
});

test("has no automated accessibility violations in denied, error, and confirmation states", async ({
  page,
}) => {
  await page.goto(professionalObjectPath("permission-denied"));
  await expectNoAccessibilityViolations(page);

  await page.goto(professionalObjectPath("object-error"));
  await expectNoAccessibilityViolations(page);

  await page.goto(professionalObjectPath("evidence"));
  await page.getByRole("button", { name: "More object actions" }).click();
  await page.getByRole("menuitem", { name: "Preview archive confirmation" }).click();
  await expectNoAccessibilityViolations(page);
});

test("reflows without horizontal scrolling across the required viewport matrix", async ({ page }) => {
  const viewports = [
    { width: 1440, height: 1000 },
    { width: 1280, height: 900 },
    { width: 1024, height: 900 },
    { width: 900, height: 900 },
    { width: 768, height: 900 },
    { width: 430, height: 932 },
    { width: 390, height: 844 },
    { width: 375, height: 812 },
    { width: 320, height: 720 },
  ];

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto(professionalObjectPath("long-content"));
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /Assessment of the customer-support transcription/,
      }),
    ).toBeVisible();

    const layout = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(layout.scrollWidth, `${viewport.width}px page width`).toBeLessThanOrEqual(
      layout.clientWidth,
    );

    const desktopInspector = page.getByRole("complementary", { name: "Record inspector" });
    const mobileInspectorTrigger = page.getByRole("button", { name: /Record details/ });
    if (viewport.width >= 1180) {
      await expect(desktopInspector).toBeVisible();
      await expect(mobileInspectorTrigger).toBeHidden();
    } else {
      await expect(desktopInspector).toBeHidden();
      await expect(mobileInspectorTrigger).toBeVisible();
    }
  }

  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto(professionalObjectPath("evidence"));
  await page.getByRole("button", { name: "More object actions" }).click();
  await page.getByRole("menuitem", { name: "Preview archive confirmation" }).click();
  const confirmationDialog = page.getByRole("dialog", {
    name: "Archive this professional record?",
  });
  await expect(confirmationDialog).toBeVisible();
  const confirmationBounds = await confirmationDialog.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, viewportWidth: window.innerWidth };
  });
  expect(confirmationBounds.left).toBeGreaterThanOrEqual(0);
  expect(confirmationBounds.right).toBeLessThanOrEqual(confirmationBounds.viewportWidth);
});
