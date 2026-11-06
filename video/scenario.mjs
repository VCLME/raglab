/**
 * What the demo asks, shared by the capture (live API) and the shots
 * (replayed API). Corpora are picked by matching their name in the Corpus
 * menu, so the same scenario works whatever the local corpus names are.
 */
export const VIEWPORT = { width: 1440, height: 900 };
export const LANGUAGE = "en";
// The fixed sentence the generator gives when it will not answer (English,
// src/raglab/generation/prompts.py): a take where it shows is not kept.
export const NO_ANSWER = /^"?I cannot answer reliably from the retrieved context/;

const CONSUMER = /consommation/i;
const LEXML = /lexml_pt/i;

export const SCENARIO = {
  // 1. A plain question in the Chat whose answer is not the obvious one (no
  //    withdrawal period at a fair, unlike online), from several articles.
  ask: {
    corpus: CONSUMER,
    question: "I bought a sofa at a trade fair and I regret it. Can I withdraw, like for an online purchase?",
  },
  // 2. Learning mode, in the same conversation: a follow-up question, the
  //    pipeline followed brick by brick, then three lessons.
  learning: {
    // Names the fair: the Chat sends each question on its own.
    question: "And if the seller at the fair never told me there was no withdrawal period?",
    lessons: [/^BM25/, /^Fusion/, /^Re-ranking/],
  },
  // 3. The Workshop (expert mode): a run through its menus, the citation
  //    graph of one law, then the three ways to import data. It follows the
  //    LexML corpus, whose citation graph is built.
  workshop: { corpus: LEXML, law: /13\.445|Migra/i },
};
