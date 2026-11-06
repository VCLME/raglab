/**
 * One part of the app on screen: its screenshots played at their times,
 * inside a card the camera moves over, with the cursor and the captions.
 */
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { C, FONT, FPS } from "./theme";
import type { Rect, Segment } from "./timeline";

const VW = 1440;
const VH = 900;
const FW = 1920;
const FH = 1080;
// Where the camera's point of interest lands in the frame: centred for the
// establishing shots, a little higher on a detail so the caption band stays clear.
const ANCHOR_X = 960;
const ANCHOR_Y = { overview: 540, focus: 470 };
// Below this zoom the card would not fill the frame.
const MIN_FOCUS_ZOOM = Math.max(FW / VW, FH / VH);

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
    return { s: k.zoom ?? 1.1, cx: VW / 2, cy: VH / 2 + (k.dy ?? 0), rot: k.tilt ?? 0, ay: ANCHOR_Y.overview };
  }
  const { x, y, w, h } = k.focus;
  const ay = ANCHOR_Y.focus;
  const s = Math.max(MIN_FOCUS_ZOOM, k.zoom ?? Math.min(2.3, 1400 / w, 640 / h));
  // On a detail the card always fills the frame: no paper at the edges.
  const cx = clampTo(x + w / 2, ANCHOR_X / s, VW - (FW - ANCHOR_X) / s);
  const cy = clampTo(y + h / 2 + (k.dy ?? 0), ay / s, VH - (FH - ay) / s);
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
    dur = k.dur ?? 950;
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
  const travel = c.y < 120 ? 900 : 430;
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

export function Caption({ cues, ms }: { cues: CaptionCue[]; ms: number }) {
  const shown = cues.filter((c) => c.at <= ms + 1);
  return (
    <>
      {shown.slice(-2).map((cue, k, arr) => {
        const isLast = k === arr.length - 1;
        const inP = Easing.out(Easing.cubic)(clamp01((ms - cue.at) / 520));
        const next = cues.find((c) => c.at > cue.at);
        const outP = next ? clamp01((ms - next.at) / 300) : 0;
        if (!isLast && outP >= 1) return null;
        return (
          <div
            key={cue.at + cue.text}
            style={{
              position: "absolute",
              left: 96,
              bottom: 84,
              maxWidth: 1240,
              whiteSpace: "nowrap",
              padding: "22px 30px 24px",
              background: "oklch(0.975 0.006 85 / 0.95)",
              border: `1px solid ${C.rule}`,
              borderRadius: 14,
              boxShadow: "0 18px 40px -22px oklch(0.2 0.02 60 / 0.35)",
              opacity: inP * (1 - outP),
              transform: `translateY(${(1 - inP) * 18}px)`,
            }}
          >
            <div
              style={{
                fontFamily: FONT.code,
                fontSize: 21,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: C.accent,
                marginBottom: 10,
              }}
            >
              {cue.kicker}
            </div>
            <div style={{ fontFamily: FONT.text, fontWeight: 600, fontSize: 46, letterSpacing: "-0.02em", lineHeight: 1.1, color: C.ink }}>
              {cue.text}
            </div>
          </div>
        );
      })}
    </>
  );
}

export function AppScene({
  seg,
  camera,
  captions,
  from = 0,
  enterFrames = 18,
  duration,
  exitFrames = 10,
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
  const ty = cam.ay - VH / 2 - cam.s * (cam.cy - VH / 2) + (1 - enter) * 70;
  return (
    <AbsoluteFill style={{ perspective: 2600, opacity: exit }}>
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
          boxShadow: `0 0 0 1px ${C.rule}, 0 50px 110px -40px oklch(0.2 0.02 60 / 0.45)`,
        }}
      >
        <Screen seg={seg} ms={ms} whip={whip} />
      </div>
      <Cursor seg={seg} ms={ms} cam={cam} />
      <Caption cues={captions} ms={ms} />
    </AbsoluteFill>
  );
}
