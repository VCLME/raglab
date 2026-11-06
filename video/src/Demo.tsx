/**
 * The cut. `Demo` is the full film for the site (raglab opening, a plain
 * question and its sources, a follow-up in learning mode, the Workshop);
 * `DemoShort` the README GIF (the question, then the follow-up brick by brick).
 */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AppScene, type CameraKey, type CaptionCue } from "./AppScene";
import { AndMore, Intro, Outro, Paper, PlaceholderBadge } from "./Brand";
import { f } from "./theme";
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
  { at: 0, zoom: 1.0, tilt: -4 },
  { at: at(ask, "home") + 1800, zoom: 1.06, tilt: 0, dur: 2200 },
  { at: at(ask, "corpus") - 300, focus: ask.rects.corpus, zoom: 2.0, dur: 1000 },
  { at: at(ask, "ask") - 200, focus: ask.rects.composer, zoom: 1.6, dur: 1000 },
  { at: after(ask, "send", 450), focus: ask.rects.answer, dur: 1100 },
  { at: at(ask, "sources") - 200, focus: ask.rects.chips, zoom: 2.0, dur: 900 },
  { at: after(ask, "details", 650), focus: ask.rects.details, dur: 1000 },
  { at: at(ask, "passages") + 200, focus: ask.rects.passages, zoom: 1.7, dur: 1100 },
]);
const askCaptions: CaptionCue[] = [
  { at: at(ask, "home") + 1200, kicker: "01 · Chat", text: "Your legal documents, one question away." },
  { at: at(ask, "corpus"), kicker: "01 · Chat", text: "Pick a corpus: French consumer law." },
  { at: at(ask, "ask"), kicker: "01 · Chat", text: "Ask in plain words, no article number needed." },
  { at: at(ask, "answered") - 1500, kicker: "01 · Chat", text: "One answer, built from several articles." },
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
  { at: 0, zoom: 1.04 },
  { at: after(learning, "learning", -300), focus: learning.rects.toggle, zoom: 1.7, dur: 1000 },
  { at: after(learning, "learning", 700), zoom: 1.08, dur: 1000 },
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
  { at: at(learning, "toggle"), kicker: "03 · Learning mode", text: "Now open the pipeline behind the answers." },
  { at: at(learning, "follow-up"), kicker: "03 · Learning mode", text: "Ask a follow-up in the same conversation, and watch it run." },
  ...bricks
    .filter((b) => BRICKS[b.id])
    .map((b) => ({ at: b.at, kicker: "03 · Learning mode · slowed down", text: BRICKS[b.id] })),
  { at: at(learning, "answered") - 2400, kicker: "03 · Learning mode", text: "The answer, in the language of the question." },
  { at: at(learning, "lesson-0", NaN), kicker: "03 · BM25", text: "Exact words count: article numbers, names." },
  { at: at(learning, "lesson-1", NaN), kicker: "03 · Fusion", text: "Two rankings, merged into one." },
  { at: at(learning, "lesson-2", NaN), kicker: "03 · Re-ranking", text: "Before and after the cross-encoder." },
].filter((c) => !Number.isNaN(c.at));

// ---- 3. Expert mode: the Workshop ------------------------------------------------------
const W = workshop.rects;
const tour: [number, number] = [at(workshop, "tour"), at(workshop, "tour-end")];
const workshopCamera = keys([
  { at: 0, zoom: 1.04 },
  { at: after(workshop, "workshop", -300), focus: W.tab, zoom: 1.7, dur: 1000 },
  { at: at(workshop, "overview"), zoom: 1.04, tilt: -3, dur: 900 },
  { at: at(workshop, "overview") + 1000, focus: W.flow, zoom: 1.5, dur: 1200 },
  // The run through the menus: wide and steady, the pages blur past.
  { at: tour[0], zoom: 1.0, tilt: 0, dur: 600 },
  { at: at(workshop, "graph"), focus: top(W.graph, 520), zoom: 1.4, dur: 900 },
  { at: at(workshop, "graph-view", NaN), focus: W["graph-view"], dur: 1100 },
  { at: at(workshop, "graph-view", NaN) + 2600, focus: W["graph-view"], zoom: 1.55, dur: 3000 },
  { at: at(workshop, "corpus"), focus: top(W.corpus, 560), zoom: 1.35, dur: 900 },
  { at: at(workshop, "folder"), focus: top(W.folder, 600), zoom: 1.35, dur: 700 },
  { at: at(workshop, "lexml"), focus: top(W.lexml, 600), zoom: 1.35, dur: 700 },
  { at: at(workshop, "official"), focus: top(W.official, 600), zoom: 1.35, dur: 700 },
]);
const workshopCaptions: CaptionCue[] = [
  { at: at(workshop, "tab"), kicker: "04 · Expert mode", text: "One click to the Workshop." },
  { at: at(workshop, "overview") + 300, kicker: "04 · Workshop", text: "Control every step, from your data to the answer." },
  { at: tour[0], kicker: "04 · Workshop", text: "Chunking, vectors, evaluation, retrieval, models, databases." },
  { at: at(workshop, "graph"), kicker: "04 · Workshop · Graph", text: "Cross-references between laws, as a graph." },
  { at: at(workshop, "corpus"), kicker: "04 · Workshop · Corpus", text: "Import your data." },
  { at: at(workshop, "folder"), kicker: "04 · Import", text: "From a local folder." },
  { at: at(workshop, "lexml"), kicker: "04 · Import", text: "From LexML, Brazil's law portal." },
  { at: at(workshop, "official"), kicker: "04 · Import", text: "From official sources: Légifrance, EUR-Lex." },
];

// Scenes overlap by this much: one fades out while the next comes in.
const OVERLAP = 10;

export const LEN = {
  intro: 120,
  ask: f(ask.duration),
  learning: f(learning.duration),
  workshop: f(workshop.duration),
  more: 210,
  outro: 150,
};
export const DEMO_FRAMES = Object.values(LEN).reduce((a, b) => a + b, 0) - OVERLAP * (Object.keys(LEN).length - 1);

export function Demo() {
  let start = 0;
  const next = (len: number) => {
    const s = start;
    start += len - OVERLAP;
    return s;
  };
  const scene = (seg: Segment, len: number, camera: CameraKey[], captions: CaptionCue[], whip: [number, number][] = []) => (
    <Sequence from={next(len)} durationInFrames={len}>
      <AppScene seg={seg} camera={camera} captions={captions} duration={len} whip={whip} />
    </Sequence>
  );
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence from={next(LEN.intro)} durationInFrames={LEN.intro}>
        <Intro duration={LEN.intro} />
      </Sequence>
      {scene(ask, LEN.ask, askCamera, askCaptions)}
      {scene(learning, LEN.learning, learningCamera, learningCaptions)}
      {scene(workshop, LEN.workshop, workshopCamera, workshopCaptions, [tour])}
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

// The GIF: the plain question and its answer, then the follow-up in learning
// mode, brick by brick, until its answer (the README budget is 8 MB).
const ASK_FROM = Math.max(0, at(ask, "ask") - 400);
const ASK_TO = at(ask, "answered", ask.duration) + 3000;
const LEARN_FROM = Math.max(0, at(learning, "toggle") - 200);
const LEARN_TO = at(learning, "answered", learning.duration) + 1600;
const SHORT = { intro: 45, ask: f(ASK_TO - ASK_FROM), learning: f(LEARN_TO - LEARN_FROM), outro: 70 };
export const SHORT_FRAMES = Object.values(SHORT).reduce((a, b) => a + b, 0) - 3 * OVERLAP;

export function DemoShort() {
  const askFrom = SHORT.intro - OVERLAP;
  const learningFrom = askFrom + SHORT.ask - OVERLAP;
  const outroFrom = learningFrom + SHORT.learning - OVERLAP;
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
      <Sequence from={outroFrom} durationInFrames={SHORT.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}
