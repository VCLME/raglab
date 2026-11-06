/**
 * The cut. `DemoShort` is the demo on the site and in the README (a plain
 * question, a follow-up in learning mode, the Workshop to its graph);
 * `Demo` the longer cut (sources, lessons, import), kept for reference.
 */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AppScene, type CameraKey, type CaptionCue } from "./AppScene";
import { AndMore, Intro, Outro, Paper, PlaceholderBadge } from "./Brand";
import { fApp } from "./theme";
import { at, clickAt, timeline, type Rect, type Segment } from "./timeline";

const { ask, learning, workshop } = timeline.segments;

/** Time of a click plus `ms`, or undefined when the journey skipped it. */
const after = (seg: Segment, click: string, ms: number) => {
  const t = clickAt(seg, click);
  return t === undefined ? undefined : t + ms;
};

/** The top `h` px of a rect. */
const top = (r: Rect | undefined, h: number): Rect | undefined => r && { ...r, h: Math.min(r.h, h) };

/** Drop the keys whose moment or element the journey did not produce. */
const keys = (list: (Partial<CameraKey> | false)[]): CameraKey[] =>
  list.filter(
    (k): k is CameraKey => !!k && k.at !== undefined && !Number.isNaN(k.at) && (!("focus" in k) || !!k.focus)
  );

// ---- 1. raglab opens; a plain question and its sources ---------------------------------
const askCamera = keys([
  // The whole window first, still, then a slow push in.
  { at: 0 },
  { at: at(ask, "home") + 2500, zoom: 1.0, dur: 3000 },
  { at: at(ask, "corpus") - 400, focus: ask.rects.corpus, zoom: 1.7 },
  { at: at(ask, "ask") - 300, focus: ask.rects.composer, zoom: 1.45 },
  { at: after(ask, "send", 600), focus: ask.rects.answer, zoom: 1.45, dur: 1800 },
  { at: at(ask, "sources") - 300, focus: ask.rects.chips, zoom: 1.8 },
  { at: after(ask, "details", 800), focus: ask.rects.details, zoom: 1.45 },
  { at: at(ask, "passages") + 300, focus: ask.rects.passages, zoom: 1.6, dur: 1800 },
  // Back to the whole window, so the next scene opens on the same shot.
  { at: ask.duration - 2600, dur: 2000 },
]);
const askCaptions: CaptionCue[] = [
  { at: at(ask, "home") + 1500, kicker: "01 · Chat", text: "Your legal documents, one question away." },
  { at: at(ask, "corpus"), kicker: "01 · Chat", text: "Pick a corpus: the French Consumer Code." },
  { at: at(ask, "ask"), kicker: "01 · Chat", text: "Ask in plain words, as you would ask a lawyer." },
  { at: at(ask, "answered") - 1500, kicker: "01 · Chat", text: "Not the obvious answer: no withdrawal at a fair." },
  { at: at(ask, "sources"), kicker: "02 · Sources", text: "Every claim cites its passage." },
  { at: at(ask, "passages"), kicker: "02 · Sources", text: "The exact text, in force today." },
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
  // Wide enough to see the cursor travel up to the toggle.
  { at: 0 },
  { at: after(learning, "learning", -200), focus: learning.rects.toggle, zoom: 1.6, dur: 1200 },
  { at: at(learning, "strip") + 600, focus: learning.rects.strip, zoom: 1.4, dur: 1600 },
  { at: at(learning, "follow-up") - 300, focus: learning.rects.composer, zoom: 1.34 },
  // The camera travels along the diagram as each brick lights up.
  ...bricks.map((b) => ({ at: b.at - 200, focus: b.rect, zoom: 1.8, dur: 1100 })),
  { at: at(learning, "answered") - 3200, focus: learning.rects.answer, zoom: 1.45, dur: 1800 },
  ...[0, 1, 2].flatMap((i) => [
    { at: at(learning, `lesson-${i}`, NaN) - 400, focus: learning.rects[`node-${i}`], zoom: 1.8 },
    { at: after(learning, `lesson-${i}`, 900), focus: learning.rects[`lesson-${i}`], zoom: 1.45, dur: 1600 },
  ]),
  { at: learning.duration - 2600, dur: 2000 },
]);
const learningCaptions: CaptionCue[] = [
  { at: at(learning, "toggle"), kicker: "03 · Learning mode", text: "Now open the pipeline behind the answers." },
  { at: at(learning, "follow-up"), kicker: "03 · Learning mode", text: "Ask a follow-up in the same conversation, and watch it run." },
  ...bricks
    .filter((b) => BRICKS[b.id])
    .map((b) => ({ at: b.at, kicker: "03 · Learning mode · slowed down", text: BRICKS[b.id] })),
  { at: at(learning, "answered") - 3000, kicker: "03 · Learning mode", text: "The answer, in the language of the question." },
  { at: at(learning, "lesson-0", NaN), kicker: "03 · BM25", text: "Exact words count: article numbers, names." },
  { at: at(learning, "lesson-1", NaN), kicker: "03 · Fusion", text: "Two rankings, merged into one." },
  { at: at(learning, "lesson-2", NaN), kicker: "03 · Re-ranking", text: "Before and after the cross-encoder." },
].filter((c) => !Number.isNaN(c.at));

// ---- 3. Expert mode: the Workshop ------------------------------------------------------
const W = workshop.rects;
const tour: [number, number] = [at(workshop, "tour"), at(workshop, "tour-end")];
const workshopCamera = keys([
  { at: 0 },
  { at: after(workshop, "workshop", -200), focus: W.tab, zoom: 1.6, dur: 1200 },
  { at: at(workshop, "overview"), dur: 1600 },
  { at: at(workshop, "overview") + 1800, focus: W.flow, zoom: 1.4, dur: 1800 },
  // The run through the menus: the whole window, steady.
  { at: tour[0], dur: 1000 },
  { at: at(workshop, "graph"), focus: top(W.graph, 560), zoom: 1.4 },
  { at: at(workshop, "graph-view", NaN), focus: W["graph-view"], zoom: 1.4, dur: 1600 },
  { at: at(workshop, "graph-view", NaN) + 2600, focus: W["graph-view"], zoom: 1.6, dur: 4000 },
  { at: at(workshop, "corpus"), focus: top(W.corpus, 600), zoom: 1.35 },
  { at: workshop.duration - 2600, dur: 2000 },
]);
const workshopCaptions: CaptionCue[] = [
  { at: at(workshop, "tab"), kicker: "04 · Expert mode", text: "One click to the Workshop." },
  { at: at(workshop, "overview") + 300, kicker: "04 · Workshop", text: "Control every step, from your data to the answer." },
  { at: tour[0], kicker: "04 · Workshop", text: "Chunking, vectors, evaluation, retrieval, models, databases." },
  { at: at(workshop, "graph"), kicker: "04 · Workshop · Graph", text: "The citation graph, built from the texts." },
  { at: at(workshop, "graph-view", NaN), kicker: "04 · Graph · Lei 13.445", text: "Each dot is an article; each arc, one citing another." },
  { at: at(workshop, "corpus"), kicker: "04 · Workshop · Corpus", text: "Import your data." },
  { at: at(workshop, "folder"), kicker: "04 · Import", text: "From a local folder." },
  { at: at(workshop, "lexml"), kicker: "04 · Import", text: "From LexML, Brazil's law portal." },
  { at: at(workshop, "official"), kicker: "04 · Import", text: "From official sources: Légifrance, EUR-Lex." },
];

// Scenes overlap by this much: one fades out (or dissolves) while the next comes in.
const OVERLAP = 16;

export const LEN = {
  intro: 180,
  ask: fApp(ask.duration),
  learning: fApp(learning.duration),
  workshop: fApp(workshop.duration),
  more: 270,
  outro: 180,
};
export const DEMO_FRAMES = Object.values(LEN).reduce((a, b) => a + b, 0) - OVERLAP * (Object.keys(LEN).length - 1);

export function Demo() {
  let start = 0;
  const next = (len: number) => {
    const s = start;
    start += len - OVERLAP;
    return s;
  };
  // Scene to scene, the window stays put: each scene ends on the whole window,
  // the next starts there, and only the page dissolves.
  const scene = (seg: Segment, len: number, camera: CameraKey[], captions: CaptionCue[], { joined = false, last = false } = {}) => (
    <Sequence from={next(len)} durationInFrames={len}>
      <AppScene
        seg={seg}
        camera={camera}
        captions={captions}
        duration={len}
        joined={joined}
        enterFrames={joined ? OVERLAP : undefined}
        exitFrames={last ? undefined : 0}
      />
    </Sequence>
  );
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence from={next(LEN.intro)} durationInFrames={LEN.intro}>
        <Intro duration={LEN.intro} />
      </Sequence>
      {scene(ask, LEN.ask, askCamera, askCaptions)}
      {scene(learning, LEN.learning, learningCamera, learningCaptions, { joined: true })}
      {scene(workshop, LEN.workshop, workshopCamera, workshopCaptions, { joined: true, last: true })}
      <Sequence from={next(LEN.more)} durationInFrames={LEN.more}>
        <AndMore duration={LEN.more} />
      </Sequence>
      <Sequence from={next(LEN.outro)} durationInFrames={LEN.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}

// The README animation: the whole story, shortened: the question and its answer, the
// follow-up brick by brick, the Workshop to its graph (the README budget is 8 MB).
const ASK_FROM = Math.max(0, at(ask, "ask") - 600);
const ASK_TO = at(ask, "answered", ask.duration) + 2500;
const LEARN_FROM = Math.max(0, at(learning, "toggle") - 200);
const LEARN_TO = at(learning, "answered", learning.duration) + 2000;
const WORK_FROM = 0;
const WORK_TO = at(workshop, "graph-view", workshop.duration) + 3500;
const SHORT = {
  intro: 60,
  ask: fApp(ASK_TO - ASK_FROM),
  learning: fApp(LEARN_TO - LEARN_FROM),
  workshop: fApp(WORK_TO - WORK_FROM),
  outro: 110,
};
export const SHORT_FRAMES = Object.values(SHORT).reduce((a, b) => a + b, 0) - 4 * OVERLAP;

export function DemoShort() {
  const askFrom = SHORT.intro - OVERLAP;
  const learningFrom = askFrom + SHORT.ask - OVERLAP;
  const workshopFrom = learningFrom + SHORT.learning - OVERLAP;
  const outroFrom = workshopFrom + SHORT.workshop - OVERLAP;
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence durationInFrames={SHORT.intro}>
        <Intro duration={SHORT.intro} />
      </Sequence>
      <Sequence from={askFrom} durationInFrames={SHORT.ask}>
        <AppScene seg={ask} camera={askCamera} captions={askCaptions} from={ASK_FROM} duration={SHORT.ask} />
      </Sequence>
      <Sequence from={learningFrom} durationInFrames={SHORT.learning}>
        <AppScene
          seg={learning}
          camera={learningCamera}
          captions={learningCaptions}
          from={LEARN_FROM}
          duration={SHORT.learning}
        />
      </Sequence>
      <Sequence from={workshopFrom} durationInFrames={SHORT.workshop}>
        <AppScene
          seg={workshop}
          camera={workshopCamera}
          captions={workshopCaptions}
          from={WORK_FROM}
          duration={SHORT.workshop}
        />
      </Sequence>
      <Sequence from={outroFrom} durationInFrames={SHORT.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}
