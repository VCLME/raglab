/**
 * The cut. `Demo` is the full film for the site; `DemoShort` the README GIF
 * (intro, the first question and its sources, the end card).
 */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AppScene, type CameraKey, type CaptionCue } from "./AppScene";
import { Intro, Metric, Outro, Paper, PlaceholderBadge } from "./Brand";
import { f } from "./theme";
import { at, chat, clickAt, workshop, type Rect, type Segment } from "./timeline";

/** Time of a click plus `ms`, or undefined when the journey skipped it. */
const after = (seg: Segment, click: string, ms: number) => {
  const t = clickAt(seg, click);
  return t === undefined ? undefined : t + ms;
};

/** A box around a click, for the camera. */
const around = (seg: Segment, click: string): Rect | undefined => {
  const c = seg.clicks.find((x) => x.name === click);
  return c && { x: c.x - 200, y: c.y - 90, w: 400, h: 180, t: c.t };
};

/** Drop the keys whose moment or element the journey did not produce. */
const keys = (list: (Partial<CameraKey> | false)[]): CameraKey[] =>
  list.filter((k): k is CameraKey => !!k && k.at !== undefined && !Number.isNaN(k.at) && (!("focus" in k) || !!k.focus));

function chatCamera(): CameraKey[] {
  const r = chat.rects;
  return keys([
    { at: 0, zoom: 1.04, tilt: -4 },
    { at: at(chat, "ask") + 150, focus: r.composer, zoom: 1.55, dur: 1100 },
    { at: after(chat, "send", 450), focus: r.answer, dur: 1000 },
    { at: at(chat, "sources"), focus: r.citation, zoom: 2.1, dur: 800 },
    { at: after(chat, "citation", 650), focus: r.details, dur: 900 },
    { at: at(chat, "corpus"), focus: r.corpus, zoom: 1.6, dy: 140 },
    { at: at(chat, "typing-2") - 100, focus: r["composer-2"], zoom: 1.55, dur: 800 },
    { at: after(chat, "send-2", 450), focus: r["answer-2"], dur: 1000 },
    !!r.stamp && { at: at(chat, "answered-2") + 300, focus: r.stamp, zoom: 2.0 },
    { at: at(chat, "learning") - 100, zoom: 1.04 },
    { at: after(chat, "learning", 600), focus: r["composer-3"], zoom: 1.45 },
    // On the strip before the question leaves, so every stage is seen lighting up.
    { at: at(chat, "send-3") - 250, focus: r.strip, dur: 700 },
    { at: at(chat, "lesson"), focus: r["lesson-node"], zoom: 1.9, dur: 800 },
    { at: after(chat, "lesson", 650), focus: r.lesson, dur: 900 },
  ]);
}

const chatCaptions: CaptionCue[] = [
  { at: at(chat, "ask"), kicker: "01 · Chat", text: "Answers only from your documents." },
  { at: at(chat, "sources"), kicker: "02 · Sources", text: "Every claim cites its passage." },
  { at: at(chat, "corpus"), kicker: "03 · Versions", text: "The law changes. raglab knows what is in force." },
  { at: at(chat, "learning"), kicker: "04 · Learning mode", text: "Watch each stage of the pipeline work." },
];

function workshopCamera(): CameraKey[] {
  const r = workshop.rects;
  // The settings: question, corpus, hybrid search, re-ranking (top of the form).
  const settings = r.settings && { ...r.settings, h: Math.min(r.settings.h, 520) };
  return keys([
    { at: 0, zoom: 1.04, tilt: -3 },
    { at: at(workshop, "workshop") + 100, focus: settings, zoom: 1.5, dur: 900 },
    { at: clickAt(workshop, "run"), focus: around(workshop, "run"), zoom: 1.6, dur: 600 },
    { at: at(workshop, "scores") - 100, focus: r.chunks, dur: 1000 },
  ]);
}
const workshopCaptions: CaptionCue[] = [
  { at: 300, kicker: "05 · Workshop", text: "Every intermediate score, inspectable." },
];

// Scenes overlap by this much: one fades out while the next comes in.
const OVERLAP = 10;

export const LEN = {
  intro: 78,
  chat: f(chat.duration),
  workshop: f(workshop.duration),
  metric: 140,
  outro: 105,
};
export const DEMO_FRAMES = Object.values(LEN).reduce((a, b) => a + b, 0) - OVERLAP * (Object.keys(LEN).length - 1);

export function Demo() {
  let start = 0;
  const next = (len: number) => {
    const s = start;
    start += len - OVERLAP;
    return s;
  };
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence from={next(LEN.intro)} durationInFrames={LEN.intro}>
        <Intro duration={LEN.intro} />
      </Sequence>
      <Sequence from={next(LEN.chat)} durationInFrames={LEN.chat}>
        <AppScene seg={chat} camera={chatCamera()} captions={chatCaptions} duration={LEN.chat} />
      </Sequence>
      <Sequence from={next(LEN.workshop)} durationInFrames={LEN.workshop}>
        <AppScene seg={workshop} camera={workshopCamera()} captions={workshopCaptions} duration={LEN.workshop} />
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

// The GIF stops on the sources, before the corpus changes.
const SHORT = { intro: 54, chat: f(at(chat, "corpus", chat.duration)), outro: 80 };
export const SHORT_FRAMES = SHORT.intro + SHORT.chat + SHORT.outro - 2 * OVERLAP;

export function DemoShort() {
  const chatFrom = SHORT.intro - OVERLAP;
  const outroFrom = chatFrom + SHORT.chat - OVERLAP;
  return (
    <AbsoluteFill>
      <Paper />
      <Sequence durationInFrames={SHORT.intro}>
        <Intro duration={SHORT.intro} />
      </Sequence>
      <Sequence from={chatFrom} durationInFrames={SHORT.chat}>
        <AppScene seg={chat} camera={chatCamera()} captions={chatCaptions.slice(0, 2)} duration={SHORT.chat} />
      </Sequence>
      <Sequence from={outroFrom} durationInFrames={SHORT.outro}>
        <Outro />
      </Sequence>
      <PlaceholderBadge />
    </AbsoluteFill>
  );
}
