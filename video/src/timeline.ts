/**
 * public/shots/timeline.json, written by scripts/shots.mjs: the app's
 * screenshots, when each shows, where the cursor clicks, where elements are.
 */
import raw from "../public/shots/timeline.json";

export type Rect = { x: number; y: number; w: number; h: number; t: number };
export type Click = { name: string; t: number; x: number; y: number };
/** `scroll`: the page's scroll offsets; a change is a cut, not a fade. */
export type State = { src: string; t: number; scroll?: string };
export type Segment = {
  states: State[];
  marks: Record<string, number>;
  rects: Record<string, Rect>;
  clicks: Click[];
  duration: number;
};
type Metric = { label: string; recall5: number; cases: number };
export type Timeline = {
  meta: { placeholder: boolean; fixture: string; captured_at: string | null };
  viewport: { width: number; height: number };
  segments: Record<string, Segment>;
  metrics: { before: Metric; after: Metric };
};

export const timeline = raw as unknown as Timeline;
export const chat = timeline.segments.chat;
export const workshop = timeline.segments.workshop;

/** A mark's time, or `fallback` when the journey skipped it. */
export const at = (seg: Segment, name: string, fallback = 0) => seg.marks[name] ?? fallback;
/** A click's time (when the cursor starts travelling there). */
export const clickAt = (seg: Segment, name: string) => seg.clicks.find((c) => c.name === name)?.t;
