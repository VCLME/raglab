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
const EU = /eurlex|compliance/i;
const LEXML = /lexml_pt/i;
const EXPAT = /expat/i;

const DAY = 86_400_000;

/**
 * Earlier conversations, asked off camera before the film starts so the
 * history has something to show. Real questions and answers; only their
 * dates are staged (`ago`, before the capture's clock).
 */
export const HISTORY = [
  { corpus: EU, question: "What is a high-risk AI system?", ago: 24 * DAY },
  { corpus: EXPAT, question: "Do foreigners need a CPF to open a bank account in Brazil?", ago: 19 * DAY },
  { corpus: LEXML, question: "Who can apply for a humanitarian visa in Brazil?", ago: 15 * DAY },
  { corpus: CONSUMER, question: "Are late payment penalties capped for consumers?", ago: 11 * DAY },
  { corpus: EU, question: "When does DORA require reporting an ICT incident?", ago: 6 * DAY },
  { corpus: EXPAT, question: "Can I get a residence permit in Brazil if my spouse is Brazilian?", ago: 5 * DAY },
  { corpus: CONSUMER, question: "How do I withdraw from a distance contract?", ago: 4 * DAY },
  { corpus: EU, question: "Which AI practices are prohibited under the AI Act?", ago: 3 * DAY },
  { corpus: LEXML, question: "Which rights does the Migration Law guarantee to migrants?", ago: 1 * DAY + 3_600_000 },
  { corpus: CONSUMER, question: "Can I cancel a gym membership I signed at a trade fair?", ago: 1 * DAY },
  { corpus: EU, question: "What must a company do after a personal data breach?", ago: 5 * 3_600_000 },
  { corpus: CONSUMER, question: "How long is the legal guarantee of conformity?", ago: 2 * 3_600_000 },
];

export const SCENARIO = {
  // 1. The history: scrolled, searched, an old conversation reopened.
  history: { search: "withdraw" },
  // 2. A plain question, no article cited: the answer draws on several passages.
  ask: {
    corpus: CONSUMER,
    question:
      "I bought a laptop online last week and changed my mind. Can I still return it, and who pays for shipping?",
  },
  // 3. Learning mode: another question, the pipeline lights up stage by
  //    stage, then two lessons.
  learning: {
    corpus: CONSUMER,
    question: "Can a seller refuse to refund me after I cancel?",
    lessons: [/^Fusion/, /^Re-ranking/],
  },
  // 4. Workshop > Retrieval: one question, three settings, no generation.
  //    In French, the corpus' language, so BM25 matches its words.
  workshop: {
    corpus: CONSUMER,
    question: "Quel est le délai de rétractation pour un achat en ligne ?",
    lexicalWeight: "0.4",
  },
};
