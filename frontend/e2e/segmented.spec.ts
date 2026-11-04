import { expect, test } from "./fixtures/mock-api";

const indicator = (page: import("@playwright/test").Page, container: string) =>
  page.locator(`${container} > .slide-indicator`);

// offsetLeft / offsetWidth are whole pixels, boxes are sub-pixel.
const near = (a: number, b: number) => Math.abs(a - b) <= 1.5;

const offsetX = (locator: import("@playwright/test").Locator) =>
  locator.evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).m41);

test("Chat / Atelier: the active pill slides to the clicked segment (200 ms ease-out)", async ({ page }) => {
  await page.goto("/");
  const pill = indicator(page, ".mode-switch");
  await expect(pill).toBeVisible();
  const chat = page.getByRole("tab", { name: "Chat" });
  const workshop = page.getByRole("tab", { name: "Atelier" });
  const chatBox = (await chat.boundingBox())!;
  await expect.poll(async () => near((await pill.boundingBox())!.x, chatBox.x)).toBe(true);

  const transition = await pill.evaluate((el) => getComputedStyle(el));
  expect(transition.transitionProperty).toBe("transform");
  expect(transition.transitionDuration).toBe("0.2s");

  await workshop.click();
  await expect(page).toHaveURL(/\/workshop/);
  const workshopBox = (await workshop.boundingBox())!;
  await expect.poll(async () => near((await pill.boundingBox())!.x, workshopBox.x)).toBe(true);
  // Same pill element, moved: the segments are equal, only the transform changes.
  expect(near((await pill.boundingBox())!.width, workshopBox.width)).toBe(true);
  expect(await offsetX(pill)).toBeGreaterThan(0);
});

test("Reduced motion: the indicator jumps without a transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const pill = indicator(page, ".mode-switch");
  await expect(pill).toBeVisible();
  const duration = await pill.evaluate((el) => parseFloat(getComputedStyle(el).transitionDuration));
  expect(duration).toBeLessThan(0.01);
});

test("Benchmarks tabs and the options mode selector slide too", async ({ page }) => {
  await page.goto("/workshop/evaluation");
  const bar = indicator(page, ".tablist");
  await expect(bar).toBeAttached();
  const history = page.getByRole("tab", { name: "Historique" });
  await history.click();
  const target = (await history.boundingBox())!;
  await expect
    .poll(async () => {
      const box = (await bar.boundingBox())!;
      return near(box.x, target.x) && near(box.width, target.width);
    })
    .toBe(true);

  await page.goto("/");
  await page.getByRole("button", { name: /^Options/ }).click();
  const pill = indicator(page, ".segmented");
  const lexical = page.locator(".segmented label", { hasText: "Mots-clés" });
  await lexical.click();
  const box = (await lexical.boundingBox())!;
  await expect.poll(async () => near((await pill.boundingBox())!.x, box.x)).toBe(true);
});
