import { expect, test } from "@playwright/test";

// BUILD_PLAN Phase 8 acceptance: ask T1, see a citation chip, hover it, the matching source
// card turns rose-tinted; upload a file and see its status progress.

const T1 = "What is the price tolerance on a PO invoice line?";

test("T1: hovering a citation highlights its source card", async ({ page }) => {
  await page.goto(`/?q=${encodeURIComponent(T1)}`);
  const chip = page.locator("[data-citation]").first();
  await expect(chip).toBeVisible({ timeout: 120_000 });
  const n = await chip.getAttribute("data-citation");
  const second = page.locator("[data-citation]").nth(1);
  // Hover a different citation if there is one, so the change of highlight is observable.
  const target = (await second.count()) ? second : chip;
  const m = (await target.getAttribute("data-citation")) ?? n;
  await target.hover();
  const card = page.locator(`[data-source-card="${m}"]`);
  await expect(card).toHaveAttribute("data-active", "true");
  await expect(card).toHaveClass(/bg-rose-tint/);
  // The answer cites the current SOP and shows the rule text.
  await expect(page.getByText(/lower of 1%/i).first()).toBeVisible();
});

test("as of 1 Mar 2026: the older rule with the as-of chip and status line", async ({ page }) => {
  await page.goto(`/?q=${encodeURIComponent(T1)}&as_of=2026-03-01`);
  await expect(page.getByText(/Rule in force on 1 Mar 2026/)).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("as of 1 Mar 2026")).toBeVisible();
});

test("Sources: an uploaded file progresses to published", async ({ page }) => {
  await page.goto("/sources");
  await page.evaluate(() => localStorage.setItem("ps07.role", "owner"));
  const name = `smoke-note-${Date.now()}.md`;
  await page.locator('input[aria-label="Choose files to upload"]').setInputFiles({
    name,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# Smoke test note\n\nThis note was uploaded by the UI smoke test at ${new Date().toISOString()}.\n`),
  });
  const row = page.locator("[data-episode]", { hasText: name });
  await expect(row).toBeVisible({ timeout: 30_000 });
  // queued -> parsed -> extracted -> published (or held with a reason)
  await expect(row).toHaveAttribute("data-status", /parsed|extracted|published|pending_review|needs_attention/, {
    timeout: 120_000,
  });
  await expect(row).toHaveAttribute("data-status", /published|pending_review|needs_attention/, { timeout: 180_000 });
});
