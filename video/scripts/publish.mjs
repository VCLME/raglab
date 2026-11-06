/**
 * Copies the rendered demo where the README and the site read it, and puts
 * it in their hero (between the `demo:start` / `demo:end` comments):
 *   out/demo.webp -> docs/images/demo.webp  (README)
 *   out/demo.mp4  -> site/assets/demo.mp4   (site, Safari)
 *   out/demo.webm -> site/assets/demo.webm  (site)
 * Refuses a render made from placeholder data.
 *
 *   node scripts/publish.mjs
 */
import { createHash } from "node:crypto";
import { copyFile, readFile, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { ROOT, VIDEO_DIR } from "./common.mjs";

const README_DEMO = `[![raglab in action: a plain question answered from several articles, a follow-up in learning mode with the pipeline lighting up brick by brick, then the Workshop and its citation graph](docs/images/demo.webp)](https://vclme.github.io/raglab/)`;

const SITE_DEMO = `  <figure>
    <video class="shot-media" width="1920" height="1080" autoplay muted loop playsinline preload="metadata" poster="assets/chat-welcome.png"
      aria-label="raglab in use: a plain question answered from several articles and its sources, a follow-up in learning mode with the pipeline lighting up brick by brick and the BM25, Fusion and Re-ranking lessons, then the Workshop (expert mode): a run through its menus, the citation graph of a law, and three ways to import data.">
      <source src="assets/demo.webm" type="video/webm">
      <source src="assets/demo.mp4" type="video/mp4">
    </video>
    <figcaption>Chat, sources, learning mode and the Workshop, replayed from a real session on local models.</figcaption>
  </figure>`;

/** Replace what sits between the demo:start and demo:end comments of `file`. */
async function swap(file, content) {
  const path = join(ROOT, file);
  const text = await readFile(path, "utf8");
  const start = text.indexOf("<!-- demo:start");
  const end = text.indexOf("<!-- demo:end -->");
  if (start === -1 || end === -1) throw new Error(`${file}: demo:start / demo:end comments not found`);
  const open = text.indexOf("-->", start) + 3;
  const indent = text.slice(text.lastIndexOf("\n", end) + 1, end);
  await writeFile(path, `${text.slice(0, open)}\n${content}\n${indent}${text.slice(end)}`);
  console.log(`${file}: demo in place`);
}

// The render must come from a real capture, and from the shots now on disk.
const meta = JSON.parse(await readFile(join(VIDEO_DIR, "out", "demo.meta.json"), "utf8"));
const timeline = await readFile(join(VIDEO_DIR, "public", "shots", "timeline.json"), "utf8");
if (meta.placeholder || meta.fixture !== "fixtures/demo.json" || !meta.captured_at) {
  throw new Error("this render uses placeholder data: run `npm run capture` against a live API, then `npm run render`");
}
if (meta.timeline_sha256 !== createHash("sha256").update(timeline).digest("hex")) {
  throw new Error("out/ was rendered from other shots: run `npm run render` again");
}
const anim = await stat(join(VIDEO_DIR, "out", "demo.webp"));
if (anim.size > 8e6) throw new Error(`out/demo.webp is ${(anim.size / 1e6).toFixed(1)} MB, over the README's 8 MB budget`);
const targets = [
  ["out/demo.webp", "docs/images/demo.webp"],
  ["out/demo.mp4", "site/assets/demo.mp4"],
  ["out/demo.webm", "site/assets/demo.webm"],
];
for (const [from, to] of targets) {
  await copyFile(join(VIDEO_DIR, from), join(ROOT, to));
  const { size } = await stat(join(ROOT, to));
  console.log(`${to}  ${(size / 1e6).toFixed(1)} MB`);
}
await swap("README.md", README_DEMO);
await swap("site/pages/index.html", SITE_DEMO);
console.log("Next: python scripts/build_site.py to check the site, then commit.");
