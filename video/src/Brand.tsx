/** The title cards: paper, the four citation-chip squares, the wordmark. */
import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "./theme";
import { timeline } from "./timeline";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const out = Easing.out(Easing.cubic);

/** The lab-notebook page every scene sits on. */
export function Paper() {
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${C.rule} 1px, transparent 1px), linear-gradient(90deg, ${C.rule} 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          opacity: 0.28,
        }}
      />
    </AbsoluteFill>
  );
}

/** The loader's four squares (Chat.tsx), filling one after the other from `start`. */
function Chips({ start, step = 5, size = 44 }: { start: number; step?: number; size?: number }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ display: "flex", gap: size * 0.32 }}>
      {[0, 1, 2, 3].map((i) => {
        const pop = spring({ frame: frame - start - i * step, fps, config: { damping: 14, mass: 0.6 } });
        return (
          <div
            key={i}
            style={{
              width: size,
              height: size,
              borderRadius: size * 0.2,
              border: `${size * 0.057}px solid ${C.accent}`,
              transform: `scale(${0.82 + 0.18 * pop})`,
              opacity: interpolate(frame - start - i * step, [-4, 0], [0, 1], clamp),
              overflow: "hidden",
            }}
          >
            <div style={{ width: "100%", height: "100%", background: C.accent, opacity: Math.min(1, pop) }} />
          </div>
        );
      })}
    </div>
  );
}

function Rise({ at, children, dist = 22 }: { at: number; children: React.ReactNode; dist?: number }) {
  const frame = useCurrentFrame();
  const p = out(interpolate(frame - at, [0, 16], [0, 1], clamp));
  return <div style={{ opacity: p, transform: `translateY(${(1 - p) * dist}px)` }}>{children}</div>;
}

/** Fade the whole card out over its last `frames` frames. */
function useExit(duration: number, frames = 10) {
  const frame = useCurrentFrame();
  return interpolate(frame, [duration - frames, duration], [1, 0], clamp);
}

export function Intro({ duration }: { duration: number }) {
  const exit = useExit(duration);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 44, opacity: exit }}>
      <Chips start={4} />
      <Rise at={14}>
        <div style={{ fontFamily: FONT.code, fontWeight: 500, fontSize: 150, letterSpacing: "-0.04em", color: C.ink }}>raglab</div>
      </Rise>
      <Rise at={26}>
        <div style={{ fontFamily: FONT.text, fontSize: 40, color: C.ink2 }}>
          <b style={{ color: C.ink, fontWeight: 600 }}>Private RAG</b> you can measure.
        </div>
      </Rise>
    </AbsoluteFill>
  );
}

/** Everything the film could not stop on, as one card. */
const { before, after } = timeline.metrics;
const MORE = [
  `Every brick measured: Recall@5 ${Math.round(before.recall5 * 100)}% → ${Math.round(after.recall5 * 100)}% on article questions`,
  "Chunking strategies, compared",
  "Embedding models, swappable",
  "Local LLMs: Ollama, llama.cpp, vLLM",
  "Legal citations resolved to the article",
  "REST API, CLI and Prometheus metrics",
];

export function AndMore({ duration }: { duration: number }) {
  const exit = useExit(duration);
  return (
    <AbsoluteFill style={{ padding: "0 150px", justifyContent: "center", opacity: exit }}>
      <Rise at={0}>
        <div style={{ fontFamily: FONT.code, fontSize: 24, letterSpacing: "0.16em", textTransform: "uppercase", color: C.accent }}>
          05 · And more
        </div>
      </Rise>
      <Rise at={6}>
        <div style={{ fontFamily: FONT.text, fontWeight: 600, fontSize: 64, letterSpacing: "-0.02em", color: C.ink, margin: "22px 0 40px" }}>
          The whole lab, on your machine.
        </div>
      </Rise>
      <div style={{ display: "grid", gap: 20 }}>
        {MORE.map((line, i) => (
          <Rise key={line} at={16 + i * 7}>
            <div style={{ display: "flex", alignItems: "center", gap: 22, fontFamily: FONT.text, fontSize: 38, color: C.ink2 }}>
              <span style={{ width: 22, height: 22, borderRadius: 5, background: C.accent, flex: "none" }} />
              {line}
            </div>
          </Rise>
        ))}
      </div>
    </AbsoluteFill>
  );
}

export function Outro() {
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 36 }}>
      <Chips start={0} step={3} />
      <Rise at={6}>
        <div style={{ fontFamily: FONT.code, fontWeight: 500, fontSize: 124, letterSpacing: "-0.04em", color: C.ink }}>raglab</div>
      </Rise>
      <Rise at={14}>
        <div style={{ fontFamily: FONT.code, fontSize: 28, color: C.ink2, letterSpacing: "0.04em" }}>
          <span style={{ color: C.accent }}>100% local</span> · open source · measured
        </div>
      </Rise>
      <Rise at={22}>
        <div style={{ fontFamily: FONT.text, fontWeight: 600, fontSize: 36, color: C.ink, borderBottom: `2px solid ${C.accent}`, paddingBottom: 4 }}>
          github.com/VCLME/raglab
        </div>
      </Rise>
    </AbsoluteFill>
  );
}

/** Rendered from the e2e mocks instead of a real capture: say so on every frame. */
export function PlaceholderBadge() {
  if (!timeline.meta.placeholder) return null;
  return (
    <div
      style={{
        position: "absolute",
        right: 28,
        top: 24,
        padding: "8px 14px",
        borderRadius: 8,
        background: C.err,
        color: "white",
        fontFamily: FONT.code,
        fontSize: 20,
        letterSpacing: "0.08em",
      }}
    >
      PLACEHOLDER DATA · not a real capture
    </div>
  );
}
