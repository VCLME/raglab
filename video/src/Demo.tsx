/**
 * The cut. `Demo` is the full film for the site (history, learning mode in
 * the reopened conversation, its sources, the Workshop); `DemoShort` the
 * README GIF (the pipeline lighting up brick by brick).
 */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AppScene, type CameraKey, type CaptionCue } from "./AppScene";
import { AndMore, Intro, Metric, Outro, Paper, PlaceholderBadge } from "./Brand";
import { f } from "./theme";
import { at, clickAt, timeline, type Rect, type Segment } from "./timeline";

const { history, learning, sources, workshop } = timeline.segments;

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

/** The top `h` px of a rect. */
const top = (r: Rect | undefined, h: number): Rect | undefined => r && { ...r, h: Math.min(r.h, h) };

/** Drop the keys whose moment or element the journey did not produce. */
const keys = (list: (Partial<CameraKey> | false)[]): CameraKey[] =>
  list.filter(
    (k): k is CameraKey => !!k && k.at !== undefined && !Number.isNaN(k.at) && (!("focus" in k) || !!k.focus)
  );

// ---- 1. History -------------------------------------------------------------------
const historyCamera = keys([
  { at: 0, zoom: 1.04, tilt: -4 },
  { at: at(history, "history") + 700, focus: history.rects.sidebar, zoom: 1.6, dur: 1300 },
  { at: at(history, "search") - 300, focus: history.rects.search, zoom: 2.3, dur: 900 },
  { at: at(history, "hits") - 200, focus: top(history.rects.hits, 420), zoom: 1.9, dur: 900 },
  { at: after(history, "reopen", 500), focus: history.rects.reopened, dur: 1100 },
]);
const historyCaptions: CaptionCue[] = [
  { at: at(history, "history") + 300, kicker: "01 · History", text: "Every conversation, kept on your machine." },
  { at: at(history, "search"), kicker: "01 · History", text: "Search it, word by word." },
  { at: at(history, "reopened"), kicker: "01 · History", text: "Pick up where you left off." },
];

// ---- 2. Learning mode: the pipeline, brick by brick ---------------------------------
/** What each brick does, in one line (stage ids of the `stage` events). */
const BRICKS: Record<string, string> = {
  embed: "The question becomes a vector.",
  retrieval: "Vector search: passages close in meaning.",
  lexical: "BM25: passages that share its words.",
  fusion: "Both rankings, merged into one (RRF).",
  rerank: "A cross-encoder rereads the best candidates.",
  versions: "Only the article versions in force.",
  prompt: "The passages go into the prompt.",
  generation: "The local LLM writes, citing each passage.",
};
const bricks = Object.keys(learning.marks)
  .filter((m) => m.startsWith("brick-"))
  .map((m) => ({ id: m.slice("brick-".length), at: learning.marks[m], rect: learning.rects[m] }))
  .sort((a, b) => a.at - b.at);

const learningCamera = keys([
  { at: 0, focus: learning.rects.toggle, zoom: 1.6, dur: 1 },
  { at: after(learning, "learning", 600), zoom: 1.08, dur: 1000 },
  { at: at(learning, "strip") + 900, focus: learning.rects.strip, dur: 1000 },
  { at: at(learning, "follow-up") - 200, focus: learning.rects.composer, zoom: 1.5, dur: 900 },
  // The camera travels along the diagram as each brick lights up.
  ...bricks.map((b) => ({ at: b.at - 150, focus: b.rect, zoom: 2.4, dur: 650 })),
  { at: at(learning, "answered") - 2600, focus: learning.rects.answer, dur: 1100 },
  ...[0, 1, 2].flatMap((i) => [
    { at: at(learning, `lesson-${i}`, NaN) - 300, focus: learning.rects[`node-${i}`], zoom: 2.2, dur: 800 },
    { at: after(learning, `lesson-${i}`, 700), focus: learning.rects[`lesson-${i}`], dur: 1000 },
  ]),
]);
const learningCaptions: CaptionCue[] = [
  { at: at(learning, "toggle"), kicker: "02 · Learning mode", text: "Open the pipeline behind the answer." },
  { at: at(learning, "follow-up"), kicker: "02 · Learning mode", text: "Ask a follow-up and watch it run." },
  ...bricks
    .filter((b) => BRICKS[b.id])
    .map((b) => ({ at: b.at, kicker: "02 · Learning mode · slowed down", text: BRICKS[b.id] })),
  { at: at(learning, "answered") - 2400, kicker: "02 · Learning mode", text: "The answer, in the language of the question." },
  { at: at(learning, "lesson-0", NaN), kicker: "02 · BM25", text: "Exact words count: article numbers, names." },
  { at: at(learning, "lesson-1", NaN), kicker: "02 · Fusion", text: "Two rankings, merged into one." },
  { at: at(learning, "lesson-2", NaN), kicker: "02 · Re-ranking", text: "Before and after the cross-encoder." },
].filter((c) => !Number.isNaN(c.at));

// ---- 3. Sources -------------------------------------------------------------------------
const sourcesCamera = keys([
  { at: 0, focus: sources.rects.answer, dur: 1 },
  { at: after(sources, "details", 650), focus: sources.rects.details, dur: 1000 },
  { at: at(sources, "passages") + 200, focus: sources.rects.passages, zoom: 1.7, dur: 1100 },
]);
const sourcesCaptions: CaptionCue[] = [
  { at: 200, kicker: "03 · Sources", text: "Every claim cites its passage, in force today." },
];

// ---- 4. Workshop ------------------------------------------------------------------------
const W = workshop.rects;
const workshopCamera = keys([
  { at: 0, zoom: 1.04, tilt: -3 },
  { at: at(workshop, "overview") + 600, focus: W.flow, zoom: 1.5, dur: 1200 },
  { at: at(workshop, "corpus"), focus: top(W.corpus, 520), zoom: 1.4, dur: 900 },
  { at: after(workshop, "official", 600), focus: top(W.official, 560), zoom: 1.4, dur: 900 },
  { at: at(workshop, "graph"), focus: top(W.graph, 520), zoom: 1.4, dur: 900 },
  { at: at(workshop, "graph-view", NaN), focus: W["graph-view"], dur: 1000 },
  { at: at(workshop, "evaluation"), focus: top(W.evaluation, 520), zoom: 1.4, dur: 900 },
  { at: at(workshop, "eval-table", NaN), focus: W["eval-table"], dur: 1000 },
  { at: at(workshop, "form") + 100, focus: top(W.form, 520), zoom: 1.5, dur: 900 },
  { at: clickAt(workshop, "mode-hybrid-open"), focus: around(workshop, "mode-hybrid-open", 440, 300), zoom: 1.7 },
  { at: clickAt(workshop, "run-1"), focus: around(workshop, "run-1"), zoom: 1.6, dur: 600 },
  { at: at(workshop, "results-1") - 100, focus: W["results-1"], dur: 900 },
  { at: clickAt(workshop, "rerank-on-open"), focus: around(workshop, "rerank-on-open", 440, 300), zoom: 1.7 },
  { at: clickAt(workshop, "run-2"), focus: around(workshop, "run-2"), zoom: 1.6, dur: 600 },
  { at: at(workshop, "results-2") - 100, focus: W["results-2"], dur: 900 },
]);
const workshopCaptions: CaptionCue[] = [
  { at: at(workshop, "overview") + 300, kicker: "04 · Workshop", text: "Control every step, from your data to the answer." },
  { at: at(workshop, "corpus"), kicker: "04 · Workshop · Corpus", text: "Import your data: a folder, official sources, LexML." },
  { at: at(workshop, "graph"), kicker: "04 · Workshop · Graph", text: "Cross-references between laws, as a graph." },
  { at: at(workshop, "evaluation"), kicker: "04 · Workshop · Evaluation", text: "Every change measured on frozen question sets." },
  { at: at(workshop, "retrieval"), kicker: "04 · Workshop · Retrieval", text: "Every setting, every intermediate score." },
  { at: at(workshop, "setting-2"), kicker: "04 · Workshop · Retrieval", text: "Turn re-ranking on: the order changes." },
];

// Scenes overlap by this much: one fades out while the next comes in.
const OVERLAP = 10;

export const LEN = {
  intro: 90,
  history: f(history.duration),
  learning: f(learning.duration),
  sources: f(sources.duration),
  workshop: f(workshop.duration),
  more: 190,
  metric: 160,
  outro: 120,
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
      {scene(learning, LEN.learning, learningCamera, learningCaptions)}
      {scene(sources, LEN.sources, sourcesCamera, sourcesCaptions)}
      {scene(workshop, LEN.workshop, workshopCamera, workshopCaptions)}
      <Sequence from={next(LEN.more)} durationInFrames={LEN.more}>
        <AndMore duration={LEN.more} />
      </Sequence>
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

// The GIF: the follow-up question and the pipeline lighting up, brick by
// brick, until the answer (the README budget is 8 MB).
const SHORT_FROM = Math.max(0, at(learning, "follow-up") - 400);
const SHORT_TO = at(learning, "answered", learning.duration) + 1200;
const SHORT = { intro: 45, learning: f(SHORT_TO - SHORT_FROM), outro: 70 };
export const SHORT_FRAMES = SHORT.intro + SHORT.learning + SHORT.outro - 2 * OVERLAP;

export function DemoShort() {
  const learningFrom = SHORT.intro - OVERLAP;
  const outroFrom = learningFrom + SHORT.learning - OVERLAP;
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence durationInFrames={SHORT.intro}>
        <Intro duration={SHORT.intro} />
      </Sequence>
      <Sequence from={learningFrom} durationInFrames={SHORT.learning}>
        <AppScene
          seg={learning}
          camera={learningCamera}
          captions={learningCaptions}
          from={SHORT_FROM}
          duration={SHORT.learning}
        />
      </Sequence>
      <Sequence from={outroFrom} durationInFrames={SHORT.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}
