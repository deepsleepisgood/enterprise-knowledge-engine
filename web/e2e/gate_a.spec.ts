import { expect, test, type Page } from "@playwright/test";

// TEST_PLAN gate A: T1, T5 and T8 must pass in the UI at 1440 px and at 390 px (phone).
// Runs against a live stack (see playwright.config.ts); answers come from the configured LLM.

const T1 = "What is the price tolerance on a PO invoice line?";
const T5 = "The PO price is ₹395 per unit for 500 units and the invoice charges ₹400 per unit. Can the line pass the price match?";
const T8 = "Is there a canteen subsidy for night shifts?";

const WIDTHS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
];

async function ask(page: Page, question: string) {
  await page.goto(`/?q=${encodeURIComponent(question)}`);
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page scrolls sideways").toBeLessThanOrEqual(1);
}

test.setTimeout(480_000);

for (const vp of WIDTHS) {
  test.describe(`${vp.name} ${vp.width}px`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("T1 price tolerance: current rule, cited, older versions labelled", async ({ page }) => {
      await ask(page, T1);
      await expect(page.locator("[data-citation]").first()).toBeVisible({ timeout: 420_000 });
      await expect(page.getByText(/lower of 1%/i).first()).toBeVisible();
      await expect(page.getByText(/₹500/).first()).toBeVisible();
      await expect(page.getByText(/SOP v4\.0/).first()).toBeVisible();
      // The superseded values (2%, ₹1,000) never appear in the answer itself; where they are
      // shown (the NOW / BEFORE comparison, older sources) they are labelled superseded.
      await expect(page.locator(":text-matches(\"Older sources\", \"i\"):visible").first()).toBeVisible();
      const all = await page.locator("main").innerText();
      const answer = all.split(/Decision:|Older sources/i)[0];
      expect(answer).not.toMatch(/\b2%|₹1,000/);
      for (const m of all.matchAll(/BEFORE\s*(₹1,000|2%)([^\n]*\n[^\n]*)/g)) {
        expect(m[2], `old value ${m[1]} must be labelled`).toMatch(/superseded/i);
      }
      await noSidewaysScroll(page);
    });

    test("T5 ₹395 vs ₹400 × 500: excess ₹2,500 over the ₹500 limit, PRICE_VAR", async ({ page }) => {
      await ask(page, T5);
      await expect(page.getByText(/PRICE_VAR/).first()).toBeVisible({ timeout: 420_000 });
      await expect(page.getByText(/₹2,500/).first()).toBeVisible();
      await expect(page.getByText(/₹1,975/).first()).toBeVisible();
      await noSidewaysScroll(page);
    });

    test("T8 canteen subsidy: not covered, routed to a named role", async ({ page }) => {
      await ask(page, T8);
      await expect(page.getByText(/don.t cover this/i).first()).toBeVisible({ timeout: 420_000 });
      await expect(page.getByRole("button", { name: /Send to/i }).first()).toBeVisible();
      await noSidewaysScroll(page);
    });
  });
}
