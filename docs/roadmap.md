# Roadmap

La roadmap ci-dessous reflète l'ordre réel de livraison. Les phases 0 à 5 sont livrées, la 6 est en cours, les phases 7+ sont à venir.

## Phase 0 — Cadrage ✅

- architecture documentée
- choix techniques explicités
- modèle de données défini
- plan d'expérimentation cadré
- document de mission : [base-idea.md](base-idea.md)

## Phase 1 — Socle exécutable ✅

- Docker Compose pour PostgreSQL + pgvector + Ollama (+ Adminer)
- configuration centralisée (Pydantic Settings, préfixe `RAGLAB_`)
- initialisation de la base (`raglab db init`) + migration automatique au démarrage
- CLI Typer opérationnelle
- ingestion `.txt`, `.pdf`, `.docx` avec sidecars JSON pour les metadata

## Phase 2 — Baseline RAG ✅

- chunking `traditional`
- indexation complète avec `index_run` traçable
- retrieval pgvector
- génération via Ollama (`qwen2.5:7b` par défaut)
- tests unitaires

## Phase 3 — Expérimentation chunking ✅

- ajout du `slide` chunking
- ajout du `late` chunking contextualisé
- runner d'expérimentation (`raglab experiment run`)
- rapport JSON comparatif

## Phase 4 — Qualité et observabilité ✅

- filtres de retrieval (`document_id`, `file_name`, `source_path`, `tags`, `metadata_eq`)
- prompts grounding + citations inline `[Rank N]`
- métriques de retrieval : Recall@K, Precision@K, MRR, `mean_first_relevant_rank`
- logs structurés JSON côté CLI et services
- réindexation incrémentale (reuse des chunks/embeddings compatibles)

## Phase 5 — Multi-providers embeddings + multi-dimensions ✅

- provider Ollama embeddings (en complément des `transformers` locaux)
- coexistence de plusieurs modèles d'embedding sur une même base
- **plusieurs dimensions simultanées** dans la colonne `chunk_embeddings.embedding` (pgvector ≥ 0.7, `vector` non dimensionné)
- index HNSW **partiels par dimension** créés à la volée à l'indexation (voir [data-model.md](data-model.md))
- réconciliation automatique au `db init` entre `embedding_space.dimension` et les vecteurs réellement stockés

## Phase 6 — Interface web + expérimentation assistée ✅ (en itération)

- API FastAPI sous `src/raglab/api/` réutilisant les services existants
- frontend React + TypeScript + Vite (voir [frontend-ui.md](frontend-ui.md))
- modes **Chat** (conversation épurée, 3 langues) et **Expert** (ingestion, indexation, Playground Ollama, LexML, Experiments, Manage)
- i18n français / anglais / portugais (BR) avec sélecteur drapeau
- Chat Index picker : une seule liste des `index_run` disponibles, fini le duo stratégie + embedding mensonger
- page Manage : suppression de corpus et de modèles Ollama directement depuis l'UI
- citations cliquables `[Rank N]` qui activent la pill de source correspondante
- support GPU Nvidia pour Ollama via override `docker-compose.gpu.yml`

## Phase 7 — Banc de benchmark multi-datasets 🚧 (en cours)

- module `src/raglab/benchmarks/` : loaders pluggables produisant corpus + ground truth
- premier loader : **FQuAD** (SQuAD français, Wikipedia, ~500 articles, ~25 000 paires Q/R)
- commande `raglab bench download <loader>` pour alimenter le banc
- prochaine sous-phase : page UI « Benchmarks » avec graphes recall@K, MRR, latence, comparaison inter-stratégie
- sous-phase suivante : métriques RAGAS (faithfulness, context relevance, answer correctness) + LLM-as-judge
- loaders additionnels envisagés : MIRACL (multilingue), PIAF, mMARCO-fr, SciFact

## Phase 8 — Extension graphe

- interface `GraphStore`
- extraction entités / relations
- branchement Neo4j
- requêtes hybrides vectorielles + graphe

## Phase 9 — Industrialisation

- migrations Alembic
- observabilité avancée (traces, tableaux de bord)
- packaging et documentation d'exploitation
- sécurité (auth optionnelle)
