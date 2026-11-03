import type { CodeLanguage } from "./highlight";
import type { NodeId } from "./pipeline";

/** Strip nodes: the backend stages, plus the citation decision drawn by the UI. */
export type StripNode = NodeId | "citation";

export interface Snippet {
  /** Repository path the excerpt comes from. */
  source: string;
  language: CodeLanguage;
  /**
   * Trimmed excerpt of the real code. `@@key@@` is an explanatory comment,
   * translated from `edu.code.<stage>.<key>` so a non-expert can read each
   * line in their language.
   */
  code: string;
}

/**
 * Short excerpts of the code that runs each stage, trimmed from the
 * repository. Keep them in sync when the source changes: the learning mode
 * shows them as "how it is done".
 */
export const SNIPPETS: Partial<Record<StripNode, Snippet>> = {
  citation: {
    source: "src/raglab/retrieval/citations.py",
    language: "python",
    code: `# @@what@@
_LAW_RE = re.compile(
    r"\\blei(?:\\s+complementar)?\\s*(?:n(?:[º°o.]|úmero)?\\s*)?"
    # @@law@@
    r"(\\d{1,2}\\.?\\d{3}|\\d{2,3})\\b",
    re.IGNORECASE,
)
# @@article@@
_ARTICLE_RE = re.compile(r"\\bart(?:igo|\\.)?\\s*(\\d{1,4})")

# @@parse@@
citation = parse_citation(question)
if citation is not None:
    law = find_law_document(session, index_run, citation)
    # @@restrict@@
    filters = filters.model_copy(update={"document_ids": [law]})
    # @@pin@@
    pinned = article_chunks(session, index_run, law, citation.article)`,
  },
  embed: {
    source: "src/raglab/embeddings/transformers_provider.py",
    language: "python",
    code: `# @@prefix@@
def embed_query(self, text: str) -> list[float]:
    # @@encode@@
    return self._encode_batch([f"{self.settings.query_prefix}{text}"])[0]

# @@passage@@
#   embed_chunks(...) -> "passage: " + chunk text`,
  },
  retrieval: {
    source: "src/raglab/stores/vector/postgres.py",
    language: "sql",
    code: `-- @@what@@
SELECT chunk.id, chunk.text, document.file_name,
       -- @@distance@@
       embedding <=> :query_vec AS distance
FROM chunks chunk
JOIN documents document ON document.id = chunk.document_id
JOIN chunk_embeddings ON chunk_embeddings.chunk_id = chunk.id
-- @@run@@
WHERE chunk.index_run_id = :index_run_id
-- @@order@@
ORDER BY distance
LIMIT :top_k;
-- @@score@@`,
  },
  lexical: {
    source: "src/raglab/stores/lexical/postgres.py",
    language: "python",
    code: `# @@what@@
def bm25_idf(doc_count: int, doc_freq: int) -> float:
    # @@idf@@
    return math.log(1.0 + (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))

# @@candidates@@
#   chunk.lexical_tsv @@ to_tsquery('mandat | president')
# @@tf@@
tf = cast(func.coalesce(func.array_length(terms.c.positions, 1), 1), Float)
# @@norm@@
norm = k1 * (1.0 - b + b * doc_length / avgdl)
# @@sum@@
score = func.sum(query_terms.c.idf * tf * (k1 + 1.0) / (tf + norm))`,
  },
  graph: {
    source: "src/raglab/graph/structured.py",
    language: "cypher",
    code: `// @@seeds@@
UNWIND $chunks AS s
MATCH (c:Chunk {uid: s.id})-[:PART_OF]->(a:Article)
WITH a, min(s.rank) AS rank
ORDER BY rank LIMIT $max_seeds
// @@hop@@
MATCH (a)-[r:CITES]->(b:Article) WHERE b <> a
WITH a, rank, b, r ORDER BY rank, r.mentions DESC
// @@cap@@
WITH a, rank, collect(b)[..$per_seed] AS cited
UNWIND cited AS b
// @@chunks@@
MATCH (ch:Chunk)-[:PART_OF]->(b)
RETURN a.number, b.number, collect(ch.id)[..2] AS chunk_ids
// @@fusion@@`,
  },
  fusion: {
    source: "src/raglab/retrieval/fusion.py",
    language: "python",
    code: `# @@what@@
#   fused(d) = (1 - w) / (k + rank_dense(d)) + w / (k + rank_lexical(d))
#              + g / (k + rank_graph(d))
def fused_score(chunk: RetrievedChunk) -> float:
    score = 0.0
    # @@dense@@
    if chunk.dense_rank is not None:
        score += (1.0 - lexical_weight) / (k + chunk.dense_rank)
    # @@lexical@@
    if chunk.lexical_rank is not None:
        score += lexical_weight / (k + chunk.lexical_rank)
    # @@graph@@
    if chunk.graph_rank is not None:
        score += graph_weight / (k + chunk.graph_rank)
    # @@absent@@
    return score`,
  },
  rerank: {
    source: "src/raglab/retrieval/rerank.py",
    language: "python",
    code: `# @@what@@
encoded = self._tokenizer(
    # @@pairs@@
    [query] * len(batch), batch,
    padding=True, truncation=True,
    max_length=self.max_length, return_tensors="pt",
)
# @@logit@@
logits = self._model(**encoded).logits.view(-1)

# @@sort@@
order = sorted(range(len(chunks)),
               key=lambda i: (-scores[i], chunks[i].rank))
# @@keep@@
reranked = [chunks[i] for i in order][:top_k]`,
  },
  prompt: {
    source: "src/raglab/generation/prompts.py",
    language: "python",
    code: `# @@what@@
def build_context(chunks: list[RetrievedChunk]) -> str:
    return "\\n\\n".join(
        "\\n".join([
            # @@rank@@
            f"[Source rank={chunk.rank}]",
            f"Fichier: {chunk.file_name}",
            f"Score: {chunk.score:.4f}",
            "Extrait:",
            # @@text@@
            chunk.chunk_text,
        ])
        for chunk in chunks
    )
# @@rules@@`,
  },
  generation: {
    source: "src/raglab/generation/service.py",
    language: "python",
    code: `# @@what@@
response = requests.post(
    f"{self.settings.ollama_base_url}/api/chat",
    # @@stream@@
    json={"model": model, "messages": messages, "stream": True,
          # @@temperature@@
          "options": {"temperature": self.settings.generation_temperature}},
    stream=True,
)
for line in response.iter_lines():
    piece = json.loads(line).get("message", {}).get("content", "")
    if piece:
        # @@token@@
        yield piece`,
  },
  answer: {
    source: "frontend/src/components/AnswerText.tsx",
    language: "ts",
    code: `// @@what@@
const CITATION_REGEX = /\\[(?:Rank|rank|Source\\s+rank\\s*=)\\s*(\\d+)\\]/g;
// @@click@@`,
  },
};
