import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export const VIDEO_DIR = fileURLToPath(new URL("..", import.meta.url));
export const ROOT = fileURLToPath(new URL("../..", import.meta.url));
export const FRONTEND = fileURLToPath(new URL("../../frontend", import.meta.url));
export const DIST = fileURLToPath(new URL("../../frontend/dist", import.meta.url));
export const CAPTURED = fileURLToPath(new URL("../fixtures/demo.json", import.meta.url));
export const PLACEHOLDER = fileURLToPath(new URL("../fixtures/placeholder.json", import.meta.url));

/** The production bundle the demo drives (vite build, like the e2e suite). */
export function buildFrontend() {
  console.log("building the frontend (vite build)…");
  const result = spawnSync("npx", ["vite", "build", "--logLevel", "warn"], {
    cwd: FRONTEND,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) throw new Error("vite build failed");
}

/** The captured fixture when there is one, else the placeholder. */
export async function loadFixture(path) {
  const file = path ?? (existsSync(CAPTURED) ? CAPTURED : PLACEHOLDER);
  return { file, fixture: JSON.parse(await readFile(file, "utf8")) };
}

export function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return fallback;
  const next = process.argv[i + 1];
  return next === undefined || next.startsWith("--") ? true : next;
}

export function gitCommit() {
  const r = spawnSync("git", ["rev-parse", "--short", "HEAD"], { cwd: ROOT, encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}
