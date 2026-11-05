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

export const SCENARIO = {
  // 1. A question citing a Brazilian law (the Migration Law): the citation
  //    resolver pins the article.
  lexml: {
    corpus: /lexml_pt/i,
    question: "What does art. 1 of Lei nº 13.445 regulate?",
  },
  // 2. A versioned code: the French Code de la consommation, one document per
  //    article version; the answer cites the version in force.
  versions: {
    corpus: /consommation/i,
    question: "How many days does a consumer have to withdraw under art. L221-18 of the Consumer Code?",
  },
  // 3. Learning mode: a question without a citation, so hybrid search,
  //    fusion and re-ranking all light up.
  learning: {
    question: "Who bears the cost of returning goods after a withdrawal?",
    lesson: /^Re-ranking/,
  },
  // 4. Workshop > Retrieval: intermediate scores, no generation. No article
  //    cited, so no passage is pinned and every one carries its scores.
  workshop: {
    corpus: /lexml_pt/i,
    // In Portuguese, the corpus' language: BM25 matches its words directly.
    question: "Quais direitos a Lei de Migração garante aos migrantes?",
  },
};
