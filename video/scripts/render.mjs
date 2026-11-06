/**
 * Renders the demo: out/demo.mp4 and out/demo.webm (the full film, for the
 * site) and out/demo.gif (the short cut, for the README), plus
 * out/demo.meta.json saying which shots they come from (publish.mjs checks
 * it). Takes the shots first when there are none, when the fixture is newer
 * than them, or with --shots.
 *
 *   node scripts/render.mjs [--shots] [--only mp4|webm|gif]
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, statSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { CAPTURED, PLACEHOLDER, VIDEO_DIR, arg } from "./common.mjs";

const run = (cmd, args) => {
  const r = spawnSync(cmd, args, { cwd: VIDEO_DIR, stdio: "inherit", shell: process.platform === "win32" });
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(" ")} failed`);
};

const TIMELINE = join(VIDEO_DIR, "public", "shots", "timeline.json");
const fixture = existsSync(CAPTURED) ? CAPTURED : PLACEHOLDER;
const stale = !existsSync(TIMELINE) || statSync(fixture).mtimeMs > statSync(TIMELINE).mtimeMs;
if (arg("shots") || stale) run("node", ["scripts/shots.mjs"]);
await mkdir(join(VIDEO_DIR, "out"), { recursive: true });

const only = arg("only");
const outputs = {
  // H.264 for every browser; CRF 23 keeps UI text sharp at a site-friendly size.
  mp4: ["Demo", "out/demo.mp4", "--codec=h264", "--crf=23", "--pixel-format=yuv420p"],
  webm: ["Demo", "out/demo.webm", "--codec=vp9", "--crf=38"],
  // 15 fps, 1120 px wide, looping: the README GIF (under 8 MB).
  gif: ["DemoShort", "out/demo.gif", "--codec=gif", "--every-nth-frame=2", "--scale=0.5833", "--number-of-gif-loops=0"],
};
for (const [name, [composition, file, ...flags]] of Object.entries(outputs)) {
  if (only && only !== name) continue;
  run("npx", ["remotion", "render", "src/index.ts", composition, file, ...flags, "--log=warn"]);
}

const timeline = await readFile(TIMELINE, "utf8");
const { meta } = JSON.parse(timeline);
await writeFile(
  join(VIDEO_DIR, "out", "demo.meta.json"),
  JSON.stringify(
    { ...meta, timeline_sha256: createHash("sha256").update(timeline).digest("hex"), rendered_at: new Date().toISOString() },
    null,
    2
  ) + "\n"
);
