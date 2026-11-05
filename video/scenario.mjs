/**
 * What the demo asks, shared by the capture (live API) and the shots
 * (replayed API). Corpora are picked by matching their name in the Corpus
 * menu, so the same scenario works whatever the local corpus names are.
 */
export const VIEWPORT = { width: 1440, height: 900 };
export const LANGUAGE = "en";

export const SCENARIO = {
  // 1. A question citing a Brazilian law: the citation resolver pins the article.
  lexml: {
    corpus: /lexml/i,
    question: "What does art. 49 of Lei nº 8.078 say?",
  },
  // 2. EU law, versioned: the AI Act as amended by the Digital Omnibus.
  eurlex: {
    corpus: /eurlex|eu_?acts|compliance/i,
    question: "What does Article 4 of the AI Act require?",
  },
  // 3. Learning mode: a question without a citation, so hybrid search,
  //    fusion and re-ranking all light up.
  learning: {
    question: "Which AI practices are prohibited?",
    lesson: /^Re-ranking/,
  },
  // 4. Workshop > Retrieval: intermediate scores, no generation.
  workshop: {
    corpus: /lexml/i,
    question: "What does art. 49 of Lei nº 8.078 say?",
  },
};
