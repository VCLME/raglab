import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";
import { loadFont as loadHanken } from "@remotion/google-fonts/HankenGrotesk";

/** Tokens of the GitHub Pages site (site/assets/style.css): paper, ink, one green. */
export const C = {
  paper: "oklch(0.975 0.006 85)",
  paper2: "oklch(0.950 0.008 85)",
  rule: "oklch(0.860 0.008 85)",
  ink: "oklch(0.200 0.012 60)",
  ink2: "oklch(0.420 0.012 60)",
  ink3: "oklch(0.520 0.010 60)",
  accent: "oklch(0.480 0.100 158)",
  accentDeep: "oklch(0.420 0.090 160)",
  accentWash: "oklch(0.950 0.030 155)",
  accentTint: "oklch(0.88 0.06 155)",
  err: "oklch(0.52 0.18 27)",
};

export const FONT = {
  text: loadHanken("normal", { weights: ["400", "600"], subsets: ["latin"] }).fontFamily,
  code: loadGeistMono("normal", { weights: ["400", "500"], subsets: ["latin"] }).fontFamily,
};

export const FPS = 30;
export const W = 1920;
export const H = 1080;

/** ms -> frames at the composition rate. */
export const f = (ms: number) => Math.round((ms / 1000) * FPS);
