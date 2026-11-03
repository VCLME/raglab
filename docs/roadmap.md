# Roadmap

La roadmap ci-dessous reflète l'ordre réel de livraison. Les phases 0 à 6 sont livrées, les phases 7 et 8 sont en cours, la phase 9 (production) a démarré.

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
- **Phase 7.2 — RAGAS LLM-as-judge ✅ (livré)** : faithfulness (réponse ancrée dans les chunks ?) et answer_correctness (matche le ground truth ?) via Ollama avec prompts JSON-stricts. `compute_ragas: bool` sur `/api/experiments/recall`. Par-cas scores dans `ExperimentResult.metrics_json`, aggregates sur `experiment_run.config_json.summary.{faithfulness,answer_correctness}_mean`. Checkbox UI et colonnes/barres de chart.
- loaders additionnels envisagés : MIRACL (multilingue), PIAF, mMARCO-fr, SciFact

## Phase 8 — Extension graphe 🚧 (en cours)

**Sous-phase 8.0 — Plomberie Neo4j (livré)**

- service `neo4j` dans `docker-compose.yml` (image `neo4j:5.20-community`)
- driver Python `neo4j>=5.20` ajouté
- protocol `GraphStore` étendu pour matcher la forme de `VectorStore` (ingest + search + expand)
- placeholder `Neo4jGraphStore` avec `ping()` réel et stubs `NotImplementedError`
- endpoints API `/api/graph/{index,query,runs}` répondent 501 jusqu'au PR suivant
- statut Neo4j exposé dans `/api/health` et le Dashboard
- nav Expert réorganisée en 3 familles repliables : Vecteur / Graphe / LLM (Corpus, Dashboard, Benchmarks restent au top-level)
- pages placeholder « Indexation graphe » et « Retrieval graphe »

**Sous-phase 8.1 — Vector-in-graph ✅ (livré)**

- chaque chunk = nœud `(:Chunk)` avec propriété `embedding_d{N}` + relation `[:BELONGS_TO]` vers son document et `[:FROM_RUN]` vers l'index run
- helper `ensure_vector_index(driver, dim)` — un vector index Neo4j 5 par dimension (`cosine` par défaut)
- `GraphIndexingService` : chunks dans pg (métadonnées/audit), embeddings dans Neo4j
- `GraphQueryService` : KNN via `db.index.vector.queryNodes` avec filtres corpus / file_name / source_path / tags
- `IndexRun.config_json.backend` tagge chaque run (`pgvector` | `neo4j`) ; `/api/index-runs?backend=...` filtre côté API
- endpoints `/api/graph/{index,query,runs}` implémentés ; pages UI Indexation graphe + Retrieval graphe avec les mêmes formulaires que pgvector
- restera à faire en phase 8.2 : filtres `metadata_equals` côté graphe (modéliser les metadata en nœuds)

**Sous-phase 8.1.1 — Bench recall cross-backend ✅ (livré)**

- `/api/experiments/recall` accepte `backend: "pgvector" | "neo4j"`. `RecallBenchmarkService` dispatch vers `QueryService` ou `GraphQueryService` selon le choix.
- `IndexRun.config_json.backend` filtre la résolution d'index : un run pgvector ne peut plus être interrogé par `GraphQueryService` et vice-versa.
- UI Benchmarks Launch : dropdown Backend (`pgvector` | `neo4j` | les deux). Le choix « les deux » lance la même recall séquentiellement sur les deux stores.
- UI History : colonne Backend avec tag coloré (vert pgvector, bleu neo4j) ; le chart comparatif inclut le backend dans le label.
- Smoke test piaf_fr : pgvector 0.87 R@1 / 0.93 MRR ≈ neo4j 0.87 R@1 / 0.93 MRR (identique, mêmes chunks et embeddings).

**Sous-phase 8.2 — Knowledge graph 🚧 (en cours)**

**8.2.1 — Extraction d'entités ✅ (livré)**

- module `src/raglab/graph/entities/` : `EntityExtractor` Protocol + deux implémentations
  - `LLMEntityExtractor` : Ollama (qwen2.5:7b) avec prompt JSON-schema et 7 types canoniques (PERSON, ORGANIZATION, LOCATION, DATE, LAW, EVENT, PRODUCT, + MISC)
  - `SpacyEntityExtractor` : spaCy (optionnel, `pip install raglab[graph]`), remappe OntoNotes vers les 7 types canoniques
- `Neo4jGraphStore.upsert_chunks` accepte `entities_per_chunk` et MERGE `(:Entity {name, type})` + `[:MENTIONS]` depuis chaque Chunk
- `GraphIndexingService.index_corpus` accepte `extract_entities` + `extraction_engine` ; tags `config_json.entity_extraction{,_engine}` + retourne `entities_extracted`
- `/api/graph/index` accepte `extract_entities` + `extraction_engine` dans le body
- UI Indexation graphe : checkbox « Extraire les entités » + dropdown moteur (LLM / spaCy)
- smoke test sur piaf_fr : 56 entités typées extraites sur 6 chunks avec le LLM (19 LOCATION, 9 ORGANIZATION, 8 PRODUCT, 8 PERSON, 5 EVENT, 4 MISC, 1 DATE)

**8.2.2 — Retrieval hybride ✅ (livré)**

- `Neo4jGraphStore.hybrid_search` : KNN sur-fetch (top_k × 3 candidats), collecte les entités mentionnées par chaque candidat, re-rank avec `final_score = (1 - entity_weight) * vector_score + entity_weight * bridge_score` où `bridge_score` = proportion d'entités partagées avec les top-N seeds.
- `GraphQueryService.query(mode="vector"|"hybrid", seed_top_n, entity_weight)` dispatche. Le mode hybride refuse un run non-indexé avec entités (erreur claire).
- `QueryRequest` accepte `mode` + `seed_top_n` + `entity_weight`. L'endpoint `/api/query` (pgvector) ignore ces champs.
- UI Retrieval graphe : dropdown mode, slider `entity_weight` (0-1), input `seed_top_n`. Paramètres hybrides apparaissent seulement quand mode = hybride.
- Le vector index Neo4j est global aux runs de même dimension : on sur-fetch (×5 sans filtre, ×15 avec filtre) avant de filtrer par `index_run_id` pour ne pas perdre trop de candidats côté client.
- Restera : filtre par type d'entité (ex. uniquement mentions PERSON).

**8.2.2b — Visualisation du sous-graphe ✅ (livré)**

- `Neo4jGraphStore.subgraph_for_chunks(chunk_ids)` retourne en une requête Cypher un payload plat `{chunks, documents, entities, mentions}`, dédupliqué par clé `name|type` côté Python.
- Endpoint `GET /api/graph/subgraph?chunk_ids=c1,c2,...` côté API, réponse typée (`SubgraphResponse`).
- Composant React `SubgraphView` basé sur Cytoscape.js — layout force-directed `cose`, nœuds Chunk (bleu arrondi) vs Entity (colorés par type : PERSON rouge, LOCATION jaune, ORGANIZATION violet, etc.), clic pour voir le preview du chunk / le type de l'entité.
- Section repliable « Sous-graphe » sur la page Retrieval graphe, lazy-load après la requête. Légende en couleurs sous le canvas.

**8.2.3 — Filtres metadata (à venir)**

- modéliser les metadata comme nœuds de premier rang pour que `metadata_equals` fonctionne côté graphe

## Phase 9 — Production 🚧 (en cours)

Objectif : passer du laboratoire à un pipeline RAG prêt pour la production, chaque brique justifiée par un gain mesuré (Recall@5/10, MRR, latence p50/p95, juges RAGAS) sur PIAF et LexML. Une PR par sous-phase, avec le tableau avant / après. Une brique qui n'améliore rien reste derrière un drapeau.

**9.1 — Baseline reproductible 🚧**

- **9.1a — Protocole ✅** : voir [benchmarks/protocole.md](benchmarks/protocole.md) et les jeux figés dans [`benchmarks/`](../benchmarks/)
  - PIAF : corpus complet (761 paragraphes) et 500 questions tirées avec une graine, au lieu d'un corpus réduit aux paragraphes des questions
  - pertinence au niveau du passage (`expected_spans`), indépendante de la stratégie de chunking ; métriques par type de question
  - LexML texte intégral : 252 lois fédérales (API du Sénat + planalto.gov.br, `raglab lexml fulltext`), manifeste SHA-256
  - 277 questions LexML typées (`paraphrase`, `reference`, `entity`) écrites par Qwen3.6-35B-A3B via llama.cpp, réponse citée et retrouvée dans le texte, filtrées puis relues sur échantillon
  - client compatible OpenAI et `LocalLLMServer` : raglab décharge Ollama, démarre et arrête llama-server tout seul
- **9.1b — Mesure (à venir)** : timing par étape, cache de l'embedder, `raglab bench all`, `docs/benchmarks/baseline.md`, juge answer_relevancy, juge RAGAS Gemma 4 via llama.cpp (calibré contre qwen2.5), CI GitHub Actions

**9.5 — Durcissement API 🚧 (PR ouverte, empilée sur 9.1b)** : voir [api-production.md](api-production.md)

- `POST /api/query/stream` en SSE : événement `retrieval` (chunks, scores, timings) avant la génération, puis `token` au fil d'Ollama (`stream: true`), puis `done` (QueryResponse complète + `first_token_ms`) ou `error` ; `/api/query` inchangé ; page Chat en streaming avec repli automatique sur `/api/query` ; `raglab query --stream`
- budgets par étape (`RAGLAB_EMBED_TIMEOUT_SECONDS`, `RAGLAB_RETRIEVAL_TIMEOUT_SECONDS` via `statement_timeout` Postgres, `RAGLAB_GENERATION_TIMEOUT_SECONDS` total en streaming), 504 qui nomme l'étape
- `X-Request-ID` accepté ou généré, renvoyé, présent dans chaque ligne de log de la requête (ContextVar) ; ligne d'accès `http.request`
- clé d'API optionnelle (`RAGLAB_API_KEY`, en-tête `X-API-Key` ou Bearer, bouton dans l'interface) ; rate limit en mémoire par clé ou IP, 429 + `Retry-After`
- `/health` (liveness, sans dépendance) et `/ready` (Postgres, Ollama, modèle par défaut installé) ; `/api/health` conservé pour le Dashboard
- erreurs Ollama typées : modèle absent 424 (message actionnable), mémoire saturée 503 + `Retry-After`, injoignable 502, timeout 504
- mesuré sans GPU (`scripts/bench_api_hardening.py`) : sources affichées après ~65 ms au lieu de ~3,4 s, premier token à 366 ms (préremplissage simulé 300 ms) ; middlewares +0,16 ms par requête ; TTFT réel sur GPU à mesurer
- migrations Alembic : introduites avec 9.2 (`feature/hybrid-retrieval`), aucune migration dans cette PR

**À venir** : 9.2 retrieval hybride BM25 + RRF · 9.3 re-ranking cross-encoder · 9.4 compréhension de la requête et abstention · 9.6 observabilité (Prometheus, Grafana, dérive) · 9.7 portes de qualité · 9.8 vitrine
