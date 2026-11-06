/**
 * One part of the app on screen: its screenshots played at their times,
 * inside a card the camera moves over, with the cursor; the captions sit in
 * a band of their own below, so they never cover the interface.
 */
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { C, FONT, FPS } from "./theme";
import type { Rect, Segment } from "./timeline";

const VW = 1440;
const VH = 900;
const FW = 1920;
// The caption band at the bottom of the frame; the app lives in the stage above.
const BAND = 200;
const SH = 1080 - BAND;
// Where the camera's point of interest lands: the middle of the stage.
const ANCHOR_X = 960;
const ANCHOR_Y = { overview: SH / 2, focus: SH / 2 };
// The whole window, with a margin of paper around it.
const OVERVIEW_ZOOM = Math.min((FW - 220) / VW, (SH - 70) / VH);
// Below this zoom the card would not fill the stage.
const MIN_FOCUS_ZOOM = Math.max(FW / VW, SH / VH);
// Above it, the interface reads as pixels and the viewer loses the context.
const MAX_ZOOM = 2.0;

export type CameraKey = {
  at: number;
  /** Element to look at; none = the whole screen. */
  focus?: Rect;
  zoom?: number;
  /** Shift the point of interest down (px of the screen), e.g. to see a menu below a field. */
  dy?: number;
  /** Turn of the card (deg), for the establishing shots. */
  tilt?: number;
  dur?: number;
};

export type CaptionCue = { at: number; kicker: string; text: string };

type Cam = { s: number; cx: number; cy: number; rot: number; ay: number };

const ease = Easing.bezier(0.65, 0, 0.35, 1);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const mix = (a: Cam, b: Cam, p: number): Cam => ({
  // Zoom in log space: equal steps feel equal.
  s: Math.exp(Math.log(a.s) + (Math.log(b.s) - Math.log(a.s)) * p),
  cx: a.cx + (b.cx - a.cx) * p,
  cy: a.cy + (b.cy - a.cy) * p,
  rot: a.rot + (b.rot - a.rot) * p,
  ay: a.ay + (b.ay - a.ay) * p,
});

const clampTo = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function target(k: CameraKey): Cam {
  if (!k.focus) {
    return { s: k.zoom ?? OVERVIEW_ZOOM, cx: VW / 2, cy: VH / 2 + (k.dy ?? 0), rot: k.tilt ?? 0, ay: ANCHOR_Y.overview };
  }
  const { x, y, w, h } = k.focus;
  const ay = ANCHOR_Y.focus;
  const s = clampTo(k.zoom ?? Math.min(1600 / w, 760 / h), MIN_FOCUS_ZOOM, MAX_ZOOM);
  // On a detail the card always fills the stage: no paper at the edges.
  const cx = clampTo(x + w / 2, ANCHOR_X / s, VW - (FW - ANCHOR_X) / s);
  const cy = clampTo(y + h / 2 + (k.dy ?? 0), ay / s, VH - (SH - ay) / s);
  return { s, cx, cy, rot: k.tilt ?? 0, ay };
}

function cameraAt(keys: CameraKey[], ms: number): Cam {
  const sorted = [...keys].sort((a, b) => a.at - b.at);
  let from = target(sorted[0]);
  let to = from;
  let t0 = sorted[0].at;
  let dur = 1;
  for (const k of sorted.slice(1)) {
    if (ms < k.at) break;
    from = mix(from, to, ease(clamp01((k.at - t0) / dur)));
    to = target(k);
    t0 = k.at;
    dur = k.dur ?? 1400;
  }
  return mix(from, to, ease(clamp01((ms - t0) / dur)));
}

/** Screen point -> frame point, for the camera `cam`. */
function project(cam: Cam, x: number, y: number) {
  return { x: ANCHOR_X + cam.s * (x - cam.cx), y: cam.ay + cam.s * (y - cam.cy) };
}

/** How long a page change blurs inside a `whip` range (ms). */
const WHIP_MS = 320;

function Screen({ seg, ms, whip }: { seg: Segment; ms: number; whip: [number, number][] }) {
  const states = seg.states;
  let i = 0;
  while (i + 1 < states.length && states[i + 1].t <= ms) i++;
  const cur = states[i];
  const prev = states[i - 1];
  // Inside a whip range, each page change dissolves through a sideways blur.
  const whipping = !!prev && whip.some(([a, b]) => cur.t >= a && cur.t <= b);
  // A short dissolve for in-place changes; a cut when the page scrolled.
  const cut = !prev || (prev.scroll !== cur.scroll && !whipping);
  const fade = cut ? 1 : whipping ? WHIP_MS : Math.min(80, cur.t - prev.t);
  const alpha = cut ? 1 : clamp01((ms - cur.t) / Math.max(1, fade));
  const blur = whipping ? 14 * Math.sin(Math.PI * clamp01((ms - cur.t) / WHIP_MS)) : 0;
  const style: React.CSSProperties = { position: "absolute", inset: 0, width: VW, height: VH };
  return (
    <div style={{ position: "absolute", inset: 0, filter: blur > 0.3 ? `blur(${blur}px)` : undefined }}>
      {prev && alpha < 1 ? <Img src={staticFile(prev.src)} style={style} /> : null}
      <Img src={staticFile(cur.src)} style={{ ...style, opacity: alpha }} />
    </div>
  );
}

function Cursor({ seg, ms, cam }: { seg: Segment; ms: number; cam: Cam }) {
  const clicks = seg.clicks;
  const i = clicks.findLastIndex((c) => c.t <= ms + 150);
  if (i === -1) return null;
  const c = clicks[i];
  const prev = clicks[i - 1];
  const travel = c.y < 120 ? 900 : 600;
  // With no recent click, come from the page below (from further for the top bar).
  const fromPt = prev && c.t - prev.t < 4000 ? prev : c.y < 120 ? { x: c.x - 320, y: c.y + 460 } : { x: c.x + 160, y: c.y + 120 };
  const p = ease(clamp01((ms - c.t) / travel));
  const x = fromPt.x + (c.x - fromPt.x) * p;
  const y = fromPt.y + (c.y - fromPt.y) * p;
  const pressed = ms - c.t - travel;
  const opacity = interpolate(ms - c.t, [-150, 0, 1300, 1600], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const press = pressed > 0 && pressed < 160 ? 0.86 : 1;
  const ring = clamp01(pressed / 380);
  const pt = project(cam, x, y);
  return (
    <div style={{ position: "absolute", left: pt.x, top: pt.y, opacity, pointerEvents: "none" }}>
      {pressed > 0 && ring < 1 ? (
        <div
          style={{
            position: "absolute",
            left: -26,
            top: -26,
            width: 52,
            height: 52,
            borderRadius: 26,
            border: `3px solid ${C.accent}`,
            transform: `scale(${0.4 + ring * 0.9})`,
            opacity: 1 - ring,
          }}
        />
      ) : null}
      <svg
        width="30"
        height="38"
        viewBox="0 0 15 19"
        style={{ position: "absolute", left: -3, top: -2, transform: `scale(${press})`, transformOrigin: "3px 2px" }}
      >
        <path
          d="M1.5 1.5 L1.5 15 L5 11.6 L7.6 17.2 L10 16.1 L7.5 10.6 L12.4 10.6 Z"
          fill={C.ink}
          stroke="white"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

/** The caption band: one line at a time, crossfading, centred under the stage. */
export function Caption({ cues, ms }: { cues: CaptionCue[]; ms: number }) {
  const i = cues.findLastIndex((c) => c.at <= ms + 1);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: SH, height: BAND }}>
      {cues.map((cue, k) => {
        if (k !== i && k !== i - 1) return null;
        const inP = Easing.out(Easing.cubic)(clamp01((ms - cue.at) / 600));
        const next = cues[k + 1];
        const outP = next ? clamp01((ms - next.at) / 350) : 0;
        const opacity = k === i ? inP : 1 - outP;
        if (opacity <= 0) return null;
        return (
          <div
            key={cue.at + cue.text}
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
              opacity,
              transform: `translateY(${k === i ? (1 - inP) * 12 : 0}px)`,
            }}
          >
            <div style={{ fontFamily: FONT.code, fontSize: 22, letterSpacing: "0.16em", textTransform: "uppercase", color: C.accent }}>
              {cue.kicker}
            </div>
            <div style={{ fontFamily: FONT.text, fontWeight: 600, fontSize: 56, letterSpacing: "-0.02em", lineHeight: 1.1, color: C.ink, whiteSpace: "nowrap" }}>
              {cue.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AppScene({
  seg,
  camera,
  captions,
  from = 0,
  enterFrames = 24,
  duration,
  exitFrames = 14,
  whip = [],
}: {
  seg: Segment;
  camera: CameraKey[];
  captions: CaptionCue[];
  /** Segment time (ms) of this scene's first frame. */
  from?: number;
  enterFrames?: number;
  /** Length of the scene (frames): it fades out over its last `exitFrames`. */
  duration: number;
  exitFrames?: number;
  /** Segment time ranges (ms) where page changes blur, for a quick run through. */
  whip?: [number, number][];
}) {
  const frame = useCurrentFrame();
  const ms = from + (frame * 1000) / FPS;
  const cam = cameraAt(camera, ms);
  const enter = Easing.out(Easing.cubic)(clamp01(frame / enterFrames));
  const exit = clamp01((duration - frame) / exitFrames);
  const tx = ANCHOR_X - VW / 2 - cam.s * (cam.cx - VW / 2);
  const ty = cam.ay - VH / 2 - cam.s * (cam.cy - VH / 2) + (1 - enter) * 40;
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: FW, height: SH, overflow: "hidden", perspective: 2600 }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: VW,
            height: VH,
            transformOrigin: `${VW / 2}px ${VH / 2}px`,
            transform: `translate(${tx}px, ${ty}px) scale(${cam.s}) rotateY(${cam.rot}deg)`,
            borderRadius: 14,
            overflow: "hidden",
            background: "white",
            opacity: enter,
            boxShadow: `0 0 0 1px ${C.rule}, 0 40px 90px -40px oklch(0.2 0.02 60 / 0.4)`,
          }}
        >
          <Screen seg={seg} ms={ms} whip={whip} />
        </div>
        <Cursor seg={seg} ms={ms} cam={cam} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: SH, height: 1, background: C.rule }} />
      <Caption cues={captions} ms={ms} />
    </AbsoluteFill>
  );
}
