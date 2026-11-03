import type { NodeId } from "./pipeline";

export interface Snippet {
  /** Repository path the excerpt comes from. */
  source: string;
  language: "python" | "sql" | "text";
  code: string;
}

/**
 * Short excerpts of the code that runs each stage, trimmed from the repository
 * (comments shortened). Keep them in sync when the source changes: they are
 * shown as "how it is done" in the learning mode.
 */
export const SNIPPETS: Partial<Record<NodeId, Snippet>> = {
  question: {
    source: "src/raglab/retrieval/citations.py",
    language: "python",
    code: `# "Lei nº 8.078", "Lei 13.445, de 24 de maio de 2017", "art. 49"
_LAW_RE = re.compile(
    r"\\blei(?:\\s+complementar)?\\s*(?:n(?:[º°o.]|úmero)?\\s*)?"
    r"(\\d{1,2}\\.?\\d{3}|\\d{2,3})\\b(?:\\s*/\\s*(\\d{2,4}))?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(
    r"\\bart(?:igo|\\.)?\\s*(\\d{1,4})\\s*(?:[º°o]\\b|[º°])?(?:\\s*-\\s*([A-Z])\\b)?",
    re.IGNORECASE,
)`,
  },
  embed: {
    source: "src/raglab/embeddings/transformers_provider.py",
    language: "python",
    code: `# e5 models are trained with prefixes: "query: " for questions,
# "passage: " for indexed chunks (RAGLAB_QUERY_PREFIX / _PASSAGE_PREFIX).
def embed_query(self, text: str) -> list[float]:
    return self._encode_batch([f"{self.settings.query_prefix}{text}"])[0]`,
  },
  retrieval: {
    source: "src/raglab/stores/vector/postgres.py",
    language: "sql",
    code: `-- exact mode (default): true nearest neighbours of the index run
SELECT chunk.id, chunk.text, document.file_name,
       embedding <=> :query_vec AS distance      -- pgvector cosine distance
FROM chunks chunk
JOIN documents document ON document.id = chunk.document_id
JOIN chunk_embeddings ON chunk_embeddings.chunk_id = chunk.id
WHERE chunk.index_run_id = :index_run_id
ORDER BY distance
LIMIT :top_k;
-- score shown in the UI = 1 - distance (cosine similarity)`,
  },
  lexical: {
    source: "src/raglab/stores/lexical/postgres.py",
    language: "python",
    code: `# Okapi BM25 in PostgreSQL (ts_rank has no IDF):
#   idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
def bm25_idf(doc_count: int, doc_freq: int) -> float:
    return math.log(1.0 + (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))

# candidates: chunk.lexical_tsv @@ to_tsquery('mandat | president')
tf = cast(func.coalesce(func.array_length(terms.c.positions, 1), 1), Float)
norm = k1 * (1.0 - b + b * doc_length / avgdl)
score = func.sum(query_terms.c.idf * tf * (k1 + 1.0) / (tf + norm))`,
  },
  fusion: {
    source: "src/raglab/retrieval/fusion.py",
    language: "python",
    code: `#   fused(d) = (1 - w) / (k + rank_dense(d)) + w / (k + rank_lexical(d))
def fused_score(chunk: RetrievedChunk) -> float:
    score = 0.0
    if chunk.dense_rank is not None:
        score += (1.0 - lexical_weight) / (k + chunk.dense_rank)
    if chunk.lexical_rank is not None:
        score += lexical_weight / (k + chunk.lexical_rank)
    return score`,
  },
  rerank: {
    source: "src/raglab/retrieval/rerank.py",
    language: "python",
    code: `# bge-reranker-v2-m3 reads (question, passage) together
encoded = self._tokenizer(
    [query] * len(batch), batch,
    padding=True, truncation=True,
    max_length=self.max_length, return_tensors="pt",
)
logits = self._model(**encoded).logits.view(-1)

order = sorted(range(len(chunks)),
               key=lambda i: (-scores[i], chunks[i].rank))
reranked = [chunks[i] for i in order][:top_k]`,
  },
  prompt: {
    source: "src/raglab/generation/prompts.py",
    language: "python",
    code: `def build_context(chunks: list[RetrievedChunk]) -> str:
    return "\\n\\n".join(
        "\\n".join([
            f"[Source rank={chunk.rank}]",
            f"Fichier: {chunk.file_name}",
            f"Score: {chunk.score:.4f}",
            "Extrait:",
            chunk.chunk_text,
        ])
        for chunk in chunks
    )`,
  },
  generation: {
    source: "src/raglab/generation/service.py",
    language: "python",
    code: `response = requests.post(
    f"{self.settings.ollama_base_url}/api/chat",
    json={"model": model, "messages": messages, "stream": True,
          "options": {"temperature": self.settings.generation_temperature}},
    stream=True,
)
for line in response.iter_lines():
    piece = json.loads(line).get("message", {}).get("content", "")
    if piece:
        yield piece   # one SSE "token" event per fragment`,
  },
  answer: {
    source: "frontend/src/pages/Chat.tsx",
    language: "text",
    code: `// [Rank N] markers become citation buttons linked to their source
const CITATION_REGEX = /\\[(?:Rank|rank|Source\\s+rank\\s*=)\\s*(\\d+)\\]/g;`,
  },
};
