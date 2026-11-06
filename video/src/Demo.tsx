/**
 * The cut. `Demo` is the full film for the site (history, a plain question
 * and its sources, learning mode, the Workshop); `DemoShort` the README GIF
 * (the plain question and its sources).
 */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AppScene, type CameraKey, type CaptionCue } from "./AppScene";
import { Intro, Metric, Outro, Paper, PlaceholderBadge } from "./Brand";
import { f } from "./theme";
import { at, clickAt, timeline, type Rect, type Segment } from "./timeline";

const { history, ask, learning, workshop } = timeline.segments;

/** Time of a click plus `ms`, or undefined when the journey skipped it. */
const after = (seg: Segment, click: string, ms: number) => {
  const t = clickAt(seg, click);
  return t === undefined ? undefined : t + ms;
};

/** A box around a click (where the element was once scrolled into view). */
const around = (seg: Segment, click: string, w = 440, h = 220): Rect | undefined => {
  const c = seg.clicks.find((x) => x.name === click);
  return c && { x: c.x - w / 2, y: c.y - h / 2, w, h, t: c.t };
};

/** Part of a rect: its top `h` px, or a horizontal slice. */
const top = (r: Rect | undefined, h: number): Rect | undefined => r && { ...r, h: Math.min(r.h, h) };
const slice = (r: Rect | undefined, from: number, to: number): Rect | undefined =>
  r && { ...r, x: r.x + r.w * from, w: r.w * (to - from) };

/** Drop the keys whose moment or element the journey did not produce. */
const keys = (list: (Partial<CameraKey> | false)[]): CameraKey[] =>
  list.filter(
    (k): k is CameraKey => !!k && k.at !== undefined && !Number.isNaN(k.at) && (!("focus" in k) || !!k.focus)
  );

// ---- 1. History ---------------------------------------------------------------
const historyCamera = keys([
  { at: 0, zoom: 1.04, tilt: -4 },
  { at: at(history, "history") + 500, focus: history.rects.sidebar, zoom: 1.7, dur: 1100 },
  { at: at(history, "search") - 200, focus: history.rects.search, zoom: 2.0, dur: 800 },
  { at: at(history, "search") + 1400, focus: top(history.rects.hits, 300), zoom: 1.9 },
  { at: after(history, "reopen", 500), focus: history.rects.reopened, dur: 1000 },
]);
const historyCaptions: CaptionCue[] = [
  { at: at(history, "history") + 300, kicker: "01 · History", text: "Every conversation, kept and searchable." },
];

// ---- 2. A plain question and its sources ---------------------------------------
const askCamera = keys([
  { at: 0, zoom: 1.04 },
  { at: at(ask, "ask") - 200, focus: ask.rects.composer, zoom: 1.5, dur: 1000 },
  { at: after(ask, "send", 450), focus: ask.rects.answer, dur: 1000 },
  { at: at(ask, "sources") - 300, focus: ask.rects.sources, zoom: 1.9, dur: 900 },
  { at: after(ask, "details", 650), focus: ask.rects.details, dur: 900 },
  { at: at(ask, "passages") + 300, focus: ask.rects.passages, zoom: 1.7, dur: 1100 },
]);
const askCaptions: CaptionCue[] = [
  { at: at(ask, "ask"), kicker: "02 · Chat", text: "Ask in plain words. Answers only from your documents." },
  { at: at(ask, "sources"), kicker: "03 · Sources", text: "Every claim cites its passage." },
];

// ---- 3. Learning mode ------------------------------------------------------------
const lit = at(learning, "lit");
const sent = at(learning, "send");
const learningCamera = keys([
  { at: 0, zoom: 1.04, tilt: -3 },
  { at: at(learning, "learning") + 200, focus: learning.rects.composer, zoom: 1.4, dur: 900 },
  // Follow the stages as they light up: first half of the track, then the rest.
  { at: sent - 200, focus: slice(learning.rects.track, 0, 0.5), zoom: 1.9, dur: 800 },
  { at: sent + (lit - sent) * 0.55, focus: slice(learning.rects.track, 0.45, 1), zoom: 1.9, dur: 1200 },
  { at: lit + 300, focus: learning.rects.strip, dur: 1000 },
  { at: at(learning, "lesson-0") - 300, focus: learning.rects["node-0"], zoom: 2.0, dur: 800 },
  { at: after(learning, "lesson-0", 650), focus: learning.rects["lesson-0"], dur: 900 },
  { at: at(learning, "lesson-1") - 300, focus: learning.rects["node-1"], zoom: 2.0, dur: 800 },
  { at: after(learning, "lesson-1", 650), focus: learning.rects["lesson-1"], dur: 900 },
]);
const learningCaptions: CaptionCue[] = [
  { at: at(learning, "learning"), kicker: "04 · Learning mode", text: "Watch each stage work, on your own question." },
  { at: at(learning, "lesson-0"), kicker: "04 · Fusion", text: "Keyword and vector rankings, merged into one." },
  { at: at(learning, "lesson-1"), kicker: "04 · Re-ranking", text: "A cross-encoder rereads the best candidates." },
];

// ---- 4. Workshop -------------------------------------------------------------------
const results = (n: number) => workshop.rects[`results-${n}`];
const workshopCamera = keys([
  { at: 0, zoom: 1.04, tilt: -3 },
  { at: at(workshop, "overview") + 400, focus: top(workshop.rects.overview, 480), zoom: 1.45, dur: 1200 },
  { at: clickAt(workshop, "retrieval"), zoom: 1.04 },
  { at: at(workshop, "form") + 100, focus: top(workshop.rects.form, 520), zoom: 1.5, dur: 900 },
  { at: clickAt(workshop, "mode-dense-open"), focus: around(workshop, "mode-dense-open", 440, 300), zoom: 1.7 },
  { at: clickAt(workshop, "run-1"), focus: around(workshop, "run-1"), zoom: 1.6, dur: 600 },
  { at: at(workshop, "results-1") - 100, focus: results(1), dur: 900 },
  { at: clickAt(workshop, "mode-hybrid-open"), focus: around(workshop, "mode-hybrid-open", 440, 300), zoom: 1.7 },
  { at: clickAt(workshop, "weight"), focus: around(workshop, "weight"), zoom: 1.8, dur: 700 },
  { at: clickAt(workshop, "run-2"), focus: around(workshop, "run-2"), zoom: 1.6, dur: 600 },
  { at: at(workshop, "results-2") - 100, focus: results(2), dur: 900 },
  { at: clickAt(workshop, "rerank-on-open"), focus: around(workshop, "rerank-on-open", 440, 300), zoom: 1.7 },
  { at: clickAt(workshop, "run-3"), focus: around(workshop, "run-3"), zoom: 1.6, dur: 600 },
  { at: at(workshop, "results-3") - 100, focus: results(3), dur: 900 },
]);
const workshopCaptions: CaptionCue[] = [
  { at: at(workshop, "overview") + 300, kicker: "05 · Workshop", text: "Every step of the index, built and checked." },
  { at: at(workshop, "setting-1"), kicker: "05 · Workshop · 1/3", text: "Vector search only." },
  { at: at(workshop, "setting-2"), kicker: "05 · Workshop · 2/3", text: "Add BM25 keywords, fused with RRF." },
  { at: at(workshop, "setting-3"), kicker: "05 · Workshop · 3/3", text: "Then a cross-encoder re-ranks." },
];

// Scenes overlap by this much: one fades out while the next comes in.
const OVERLAP = 10;

export const LEN = {
  intro: 78,
  history: f(history.duration),
  ask: f(ask.duration),
  learning: f(learning.duration),
  workshop: f(workshop.duration),
  metric: 150,
  outro: 110,
};
export const DEMO_FRAMES = Object.values(LEN).reduce((a, b) => a + b, 0) - OVERLAP * (Object.keys(LEN).length - 1);

export function Demo() {
  let start = 0;
  const next = (len: number) => {
    const s = start;
    start += len - OVERLAP;
    return s;
  };
  const scene = (seg: Segment, len: number, camera: CameraKey[], captions: CaptionCue[]) => (
    <Sequence from={next(len)} durationInFrames={len}>
      <AppScene seg={seg} camera={camera} captions={captions} duration={len} />
    </Sequence>
  );
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence from={next(LEN.intro)} durationInFrames={LEN.intro}>
        <Intro duration={LEN.intro} />
      </Sequence>
      {scene(history, LEN.history, historyCamera, historyCaptions)}
      {scene(ask, LEN.ask, askCamera, askCaptions)}
      {scene(learning, LEN.learning, learningCamera, learningCaptions)}
      {scene(workshop, LEN.workshop, workshopCamera, workshopCaptions)}
      <Sequence from={next(LEN.metric)} durationInFrames={LEN.metric}>
        <Metric duration={LEN.metric} />
      </Sequence>
      <Sequence from={next(LEN.outro)} durationInFrames={LEN.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}

// The GIF: the plain question, from the first keystroke to the passages.
const SHORT_FROM = Math.max(0, at(ask, "ask") - 300);
const SHORT = { intro: 45, ask: f(ask.duration - SHORT_FROM), outro: 70 };
export const SHORT_FRAMES = SHORT.intro + SHORT.ask + SHORT.outro - 2 * OVERLAP;

export function DemoShort() {
  const askFrom = SHORT.intro - OVERLAP;
  const outroFrom = askFrom + SHORT.ask - OVERLAP;
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence durationInFrames={SHORT.intro}>
        <Intro duration={SHORT.intro} />
      </Sequence>
      <Sequence from={askFrom} durationInFrames={SHORT.ask}>
        <AppScene seg={ask} camera={askCamera} captions={askCaptions} from={SHORT_FROM} duration={SHORT.ask} />
      </Sequence>
      <Sequence from={outroFrom} durationInFrames={SHORT.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}
