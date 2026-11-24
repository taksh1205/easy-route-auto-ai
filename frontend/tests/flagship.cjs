// Flagship interview demo, end to end in Chromium, from a brand-new session:
// seven seats at $950 → honest no-match → explicit raise → select → quote →
// customer acceptance → individual staff approval → reload shows the same record.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const shots = process.env.SCREENSHOT_DIR;
const year = new Date().getFullYear() + 1;

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
    const snap = async (name) => shots && page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
    const answer = page.locator("p[aria-live]");
    const ask = async (message, visible) => {
      await page.getByLabel("Ask about these results").fill(message);
      await page.getByRole("button", { name: "Ask", exact: true }).click();
      await answer.filter({ hasText: visible }).waitFor();
    };

    await page.goto("http://localhost:3000/rentals");
    await page.getByText(/Offline grammar/).waitFor();
    await page.getByLabel("Describe your rental").fill(
      `Seven-seat SUV in Tempe from ${year}-04-01 to ${year}-04-08 under $950 monthly`,
    );
    await page.getByRole("button", { name: "Find rentals" }).click();
    await page.getByText("No exact matches for the current search.").waitFor();
    const chips = await page.getByLabel("Saved search").innerText();
    assert.match(chips, /≥ 7 seats/);
    assert.match(chips, /\$949\.99 monthly/); // strict "under $950" → exact inclusive ceiling
    await snap("1-no-match");

    await ask("Raise my budget to $1,200 monthly", "Search updated");
    await page.getByRole("heading", { name: /1\. 2021 Kia Sorento/ }).waitFor();
    assert.equal(await page.getByRole("heading", { level: 3 }).count(), 1);
    // The structured form must mirror the saved search, not a stale earlier value.
    assert.equal(await page.getByLabel("Maximum USD per selected period").inputValue(), "1200");
    assert.equal(await page.getByLabel("Minimum seats").inputValue(), "7");
    await ask("Quote that vehicle", "select a vehicle");
    assert.equal(await page.getByRole("button", { name: /Accept these terms/ }).count(), 0);
    await ask("Select the first car", "Selected 2021 Kia Sorento");
    await ask("Quote the selected vehicle", "vehicle 5");
    await snap("2-quote");

    await page.getByRole("button", { name: /Accept these terms/ }).click();
    const pending = page.locator("strong").filter({ hasText: "pending ·" });
    await pending.waitFor();
    const id = (await pending.innerText()).split(" · ")[1];

    await page.getByText("Staff review", { exact: true }).click();
    await page.getByLabel("Individual employee token").fill(process.env.DEMO_EMPLOYEE_TOKEN);
    await page.getByRole("button", { name: "Load requests" }).click();
    await page.locator("details article").filter({ hasText: id }).getByRole("button", { name: "approve", exact: true }).click();
    await page.locator("strong").filter({ hasText: "confirmed · " + id }).waitFor();
    await page.reload();
    await page.locator("strong").filter({ hasText: "confirmed · " + id }).waitFor();
    await snap("3-confirmed");
    console.log("PASS: flagship demo — 7 seats at $950 no-match, explicit raise, ambiguous quote refused, explicit selection, exact quote, acceptance, staff approval, reload " + id);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
