// One-shot Puppeteer script that snaps all the screenshots used in README.md.
// Prereq: `npm i --no-save puppeteer-core@21` at repo root, and the frontend
// running at http://localhost:8081 (Docker) or http://localhost:5173 (vite dev).
//
// Usage: node scripts/snap-screenshots.mjs [base-url]

import puppeteer from "puppeteer-core";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const CHROME =
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const BASE = process.argv[2] || "http://localhost:8081";
const OUT = resolve("docs/images");

const SHOTS = [
  { name: "chat-welcome", path: "/", post: pickCorpus("piaf_fr"), wait: 1500 },
  { name: "expert-dashboard", path: "/expert", wait: 1500 },
  { name: "expert-corpus", path: "/expert/corpus", wait: 800 },
  { name: "expert-corpus-bench", path: "/expert/corpus", post: clickTab("corpus_page.tab_bench"), wait: 800 },
  { name: "expert-index", path: "/expert/index", wait: 800 },
  { name: "expert-retrieval", path: "/expert/query", wait: 800 },
  { name: "expert-playground", path: "/expert/playground", wait: 800 },
  { name: "expert-benchmarks-launch", path: "/expert/benchmarks", wait: 1500 },
  { name: "expert-benchmarks-history", path: "/expert/benchmarks", post: clickBenchTab("history"), wait: 1500 },
  { name: "expert-benchmarks-custom", path: "/expert/benchmarks", post: clickBenchTab("custom"), wait: 1500 },
  { name: "expert-ollama", path: "/expert/ollama", wait: 1500 },
  { name: "expert-graph-index", path: "/expert/graph/index", wait: 1500 },
  { name: "expert-graph-query", path: "/expert/graph/query", wait: 1500 },
];

function pickCorpus(name) {
  return async (page) => {
    await page.evaluate((n) => {
      const select = document.querySelector(".settings-bar select");
      if (!select) return;
      const opt = Array.from(select.options).find((o) => o.value === n);
      if (!opt) return;
      select.value = n;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }, name);
  };
}

function clickTab(labelKey) {
  return async (page) => {
    await page.evaluate((key) => {
      const buttons = Array.from(document.querySelectorAll(".tabs button"));
      const idx = { "corpus_page.tab_bench": 1 }[key] ?? 0;
      buttons[idx]?.click();
    }, labelKey);
  };
}

function clickBenchTab(which) {
  return async (page) => {
    await page.evaluate((w) => {
      const buttons = Array.from(document.querySelectorAll(".tabs button"));
      const idx = { launch: 0, history: 1, custom: 2 }[w] ?? 0;
      buttons[idx]?.click();
    }, which);
  };
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    defaultViewport: { width: 1440, height: 900 },
    args: ["--no-sandbox", "--hide-scrollbars"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  // Seed localStorage so the app boots in French.
  await page.goto(BASE, { waitUntil: "networkidle2", timeout: 30000 });
  await page.evaluate(() => {
    localStorage.setItem("raglab.lang", "fr");
  });
  await page.reload({ waitUntil: "networkidle2" });

  for (const shot of SHOTS) {
    const url = BASE + shot.path;
    console.log(`→ ${shot.name} ${url}`);
    await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
    if (shot.post) {
      await shot.post(page);
    }
    await new Promise((r) => setTimeout(r, shot.wait ?? 500));
    const out = resolve(OUT, `${shot.name}.png`);
    await page.screenshot({ path: out, fullPage: false });
    console.log(`  saved ${out}`);
  }

  await browser.close();
  console.log("done");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
