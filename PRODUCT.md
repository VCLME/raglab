# Product

## Register

product

## Users

Two audiences, in this order:

1. **Technical decision makers** (CTOs, lead engineers, hiring managers) looking at
   raglab as the centerpiece of a freelance enterprise-AI portfolio. They open the
   demo for a few minutes, usually on a laptop in daylight, and judge whether the
   author is rigorous: are the numbers measured, is retrieval explainable, does the
   tool feel like something a serious team would run.
2. **The owner**, using it as a working bench: ingest corpora, build indexes, run
   retrieval experiments and benchmarks, compare chunking strategies and scores.

## Product Purpose

raglab is a local RAG laboratory. It ingests document corpora, indexes them with
several chunking strategies and embedding models, answers questions with cited
sources (Chat mode) and exposes every intermediate step (Expert mode: retrieval
scores per chunk, benchmarks with Recall@k / MRR / latency, graph retrieval,
Ollama controls). Success: a visitor understands in seconds what the tool does,
trusts the measurements, and can drill into any score.

## Brand Personality

Precise, calm, transparent. Reads like a well-made developer tool (Linear,
Vercel dashboard, Raycast) in a light theme: tinted neutrals, one accent,
monospace for data, dense where the data is dense. Confidence comes from
exposed numbers, not decoration. UI copy is French first (fr, en, pt-BR).

## Anti-references

- Generic SaaS template: hero metrics, gradient accents, grids of identical cards.
- Dated Bootstrap admin panel look (heavy borders, default blue buttons, cramped tables).
- Dark "hacker" neon ambience (the previous dark theme).

## Design Principles

1. **Show the measurement.** Scores, latencies and run ids are first-class content,
   set in tabular monospace and never hidden behind decoration.
2. **Explainable by default.** Every answer leads to its sources and every source to
   its scores (dense, BM25, fused, reranker); layouts leave room for more columns.
3. **Earned familiarity.** Standard app patterns (top bar, side nav, tabs, forms);
   the tool disappears into the task.
4. **Honest states.** Empty, loading and error states say what happened and what to
   do next, especially when the API or Ollama is down.

## Accessibility & Inclusion

WCAG 2.1 AA: text contrast >= 4.5:1 (3:1 for large text and UI boundaries),
visible focus rings, full keyboard navigation, `prefers-reduced-motion` honoured,
status never conveyed by color alone. Layout must work down to 360 px wide.
