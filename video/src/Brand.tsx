/** The title cards: paper, the four citation-chip squares, the wordmark, the number. */
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

export function Metric({ duration }: { duration: number }) {
  const frame = useCurrentFrame();
  const { before, after } = timeline.metrics;
  const from = Math.round(before.recall5 * 100);
  const to = Math.round(after.recall5 * 100);
  const roll = Easing.out(Easing.cubic)(interpolate(frame, [18, 62], [0, 1], clamp));
  const value = Math.round(from + (to - from) * roll);
  const exit = useExit(duration);
  return (
    <AbsoluteFill style={{ padding: "0 150px", justifyContent: "center", opacity: exit }}>
      <Rise at={0}>
        <div style={{ fontFamily: FONT.code, fontSize: 24, letterSpacing: "0.16em", textTransform: "uppercase", color: C.accent }}>
          06 · Measured
        </div>
      </Rise>
      <div style={{ display: "flex", alignItems: "baseline", gap: 44, margin: "26px 0 34px", fontFamily: FONT.code, fontWeight: 500 }}>
        <Rise at={4}>
          <span style={{ fontSize: 130, color: C.ink3, letterSpacing: "-0.03em" }}>{from}%</span>
        </Rise>
        <Rise at={10}>
          <span style={{ fontSize: 96, color: C.ink3 }}>→</span>
        </Rise>
        <Rise at={14}>
          <span style={{ fontSize: 250, color: C.accent, letterSpacing: "-0.03em", lineHeight: 0.9 }}>{value}%</span>
        </Rise>
      </div>
      <Rise at={26}>
        <div style={{ fontFamily: FONT.text, fontWeight: 600, fontSize: 54, letterSpacing: "-0.02em", lineHeight: 1.1, color: C.ink }}>
          Questions citing an article number:
          <br />
          the right passage in the top 5.
        </div>
      </Rise>
      <Rise at={34}>
        <div style={{ marginTop: 28, fontFamily: FONT.code, fontSize: 22, color: C.ink3 }}>
          LexML · {after.cases} questions · Recall@5 · {before.label} → {after.label}
        </div>
      </Rise>
      <div style={{ position: "absolute", left: 1140, top: 430, width: 640, display: "grid", gap: 46 }}>
        <Bar label={`${before.label} · dense search`} value={before.recall5} grow={[16, 40]} color={C.ink3} />
        <Bar label={`${after.label} · full pipeline`} value={after.recall5} grow={[24, 64]} color={C.accent} />
      </div>
    </AbsoluteFill>
  );
}

/** One run's Recall@5 as a bar, like the latency receipt under each answer. */
function Bar({ label, value, grow, color }: { label: string; value: number; grow: [number, number]; color: string }) {
  const frame = useCurrentFrame();
  const p = out(interpolate(frame, grow, [0, 1], clamp));
  return (
    <div style={{ opacity: interpolate(frame, [grow[0] - 6, grow[0]], [0, 1], clamp) }}>
      <div style={{ fontFamily: FONT.code, fontSize: 22, color: C.ink2, marginBottom: 14 }}>{label}</div>
      <div style={{ height: 20, borderRadius: 10, background: C.paper2, boxShadow: `inset 0 0 0 1px ${C.rule}` }}>
        <div style={{ width: `${value * 100 * p}%`, height: "100%", borderRadius: 10, background: color }} />
      </div>
    </div>
  );
}

/** Everything the film could not stop on, as one card. */
const MORE = [
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
