import { data, expect, sse, test } from "./fixtures/mock-api";

test("Chat options: the query router is off by default and sent once turned on", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("POST /api/query/stream", async (route) => {
    bodies.push(route.request().postDataJSON());
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);

  const ask = async () => {
    await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
    await page.getByRole("button", { name: "Envoyer" }).click();
  };
  await ask();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0].routing).toBe(false);

  const trigger = page.getByRole("button", { name: /^Options/ });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  await dialog.getByRole("switch", { name: /^Routage/ }).check();
  await page.keyboard.press("Escape");
  await expect(trigger).toContainText("routeur");

  await ask();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1].routing).toBe(true);
});
