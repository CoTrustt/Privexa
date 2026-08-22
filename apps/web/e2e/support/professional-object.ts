import AxeBuilder from "@axe-core/playwright";
import { expect, type BrowserContext, type Page } from "@playwright/test";

export const fixtureClientName =
  "Apollo Finance Consumer Lending and Digital Support Services — India Client Workspace";

export function professionalObjectPath(scenario: string) {
  return `/ui-harness/professional-objects/${encodeURIComponent(scenario)}`;
}

export async function establishLocalSession(context: BrowserContext) {
  await context.addCookies([
    {
      name: "stytch_session",
      value: "e2e-session",
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}

export async function expectNoAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();

  expect(results.violations).toEqual([]);
}
