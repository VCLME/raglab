export const EMBEDDING_PROVIDERS = [
  { label: "transformers (HuggingFace local)", value: "transformers" },
  { label: "ollama", value: "ollama" },
];

export const EMBEDDING_MODELS = [
  { label: "intfloat/multilingual-e5-small (defaut, 384)", value: "intfloat/multilingual-e5-small" },
  { label: "intfloat/multilingual-e5-base (768)", value: "intfloat/multilingual-e5-base" },
  { label: "intfloat/multilingual-e5-large (1024)", value: "intfloat/multilingual-e5-large" },
  { label: "sentence-transformers/all-MiniLM-L6-v2 (384)", value: "sentence-transformers/all-MiniLM-L6-v2" },
  { label: "BAAI/bge-m3 (1024)", value: "BAAI/bge-m3" },
  { label: "nomic-embed-text (Ollama, 768)", value: "nomic-embed-text" },
  { label: "mxbai-embed-large (Ollama, 1024)", value: "mxbai-embed-large" },
];
