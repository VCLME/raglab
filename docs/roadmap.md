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
- initialisation de la base (`raglab db init`), qui applique aussi les ajustements de schéma connus
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

**Fil rouge (validé le 3 novembre 2026, voir [audit-2026-11.md](audit-2026-11.md))** : le RAG classique échoue sur les documents structurés, référencés et versionnés. raglab montre où, le mesure et le corrige, entièrement en local. Quatre modes d'échec, chacun avec son jeu de questions figé, sa mesure avant / après et sa brique :

| Mode d'échec | Brique | État |
|---|---|---|
| Identifiants (« art. 49 da Lei 8.078 ») | résolveur de citations (9.3b) | ✅ 9 % → 72 % (LexML) ; questions à numéro d'article du Code de la consommation 0,46 → 1,00 |
| Renvois (la réponse est dans l'article cité) | graphe des citations dans Neo4j (9.9) | mesuré, pas de gain significatif : +6,5 pts sur 46 questions de renvois (n.s.), −2,3 pts sur les textes de l'UE (n.s.) ; reste désactivé |
| Versions (article abrogé ou réécrit cité comme en vigueur) | option `versions` : filtre par date, statut de version par chunk (9.10) | ✅ mesuré : version périmée en tête 57 % → 0 %, Recall@5 0,66 → 0,82 (Code de la consommation) ; option, passage par défaut en cours |
| Hors périmètre | routeur et abstention (9.4) | re-mesuré sur le pipeline actuel : précision 0,958 / rappel 0,850 à 3,8 % de fausses abstentions (score dense, `benchmarks/routing/router-dense-v1.json`) ; décision en attente |

Chiffres et précautions : [benchmarks/resultats-2026-11.md](benchmarks/resultats-2026-11.md).

Toute nouvelle brique doit servir l'un de ces modes d'échec ou l'expérience de démonstration (mode Démo : comparer RAG classique et raglab sur des questions pièges).

**9.1 — Baseline reproductible 🚧**

- **9.1a — Protocole ✅** : voir [benchmarks/protocole.md](benchmarks/protocole.md) et les jeux figés dans [`benchmarks/`](../benchmarks/)
  - PIAF : corpus complet (761 paragraphes) et 500 questions tirées avec une graine, au lieu d'un corpus réduit aux paragraphes des questions
  - pertinence au niveau du passage (`expected_spans`), indépendante de la stratégie de chunking ; métriques par type de question
  - LexML texte intégral : 252 lois fédérales (API du Sénat + planalto.gov.br, `raglab lexml fulltext`), manifeste SHA-256
  - 277 questions LexML typées (`paraphrase`, `reference`, `entity`) écrites par Qwen3.6-35B-A3B via llama.cpp, réponse citée et retrouvée dans le texte, filtrées puis relues sur échantillon
  - client compatible OpenAI et `LocalLLMServer` : raglab décharge Ollama, démarre et arrête llama-server tout seul
- **9.1b — Mesure 🚧 (code livré, mesures en cours)** : timing par étape, cache de l'embedder, `raglab bench all`, `docs/benchmarks/baseline.md`, juge answer_relevancy, juge RAGAS Gemma 4 via llama.cpp (calibré contre qwen2.5), CI GitHub Actions
  - CI GitHub Actions : ruff (lint + format), mypy (mode par défaut, `src/`), pytest, `tsc` + `vite build`, build des deux images Docker

**9.2 — Retrieval hybride BM25 + RRF ✅ (PR #31)** : voir [retrieval-hybrid.md](retrieval-hybrid.md)

- Alembic : révision de base identique au schéma `create_all` d'avant, puis `0002_hybrid_lexical` ; `raglab db init` exécute les migrations et adopte les bases existantes (estampille + mise à niveau)
- `tsvector` par chunk + index GIN, configuration choisie selon la langue du document ou du corpus (`raglab_french`, `raglab_portuguese`, avec `unaccent`)
- vrai BM25 calculé dans PostgreSQL (`ts_rank` n'a pas d'IDF), statistiques N / avgdl / df stockées par `index_run`, recalculées pour les runs existants par la migration ; première passe sur les termes rares qui garde le top-k exact
- fusion RRF (k = 60) avec un poids lexical réglable ; `retrieval_mode = dense | lexical | hybrid` sur l'API (y compris `/api/query/stream` et ses événements `stage` lexical / fusion), la CLI, le benchmark de recall (`raglab experiment recall`, `raglab bench all --retrieval-mode`) et l'UI, avec les scores dense / BM25 / RRF de chaque chunk
- mesuré (`hybrid-v1`, `lexical-v1` contre `baseline-v1`) : Recall@10 +0.042 sur PIAF et +0.061 sur LexML (significatifs, McNemar), +0.126 sur les questions `entity` ; Recall@5 +0.022 / +0.033 (non significatifs) ; questions `reference` inchangées (0.093) : la bonne loi est trouvée (91/97 dans le top-5), pas le bon article, à traiter en 9.4 ; BM25 seul perd sur PIAF (−0.040) ; latence de recherche doublée (p50 23 → 43 ms sur PIAF, 41 → 88 ms sur LexML : BM25 plus 50 candidats denses au lieu de 10). Mode `dense` conservé par défaut, `hybrid` recommandé comme générateur de candidats pour 9.3

**9.3 — Re-ranking cross-encoder ✅ (PR #32, garde-fou GPU #41)** : voir [reranking.md](reranking.md)

- `BAAI/bge-reranker-v2-m3` (Apache-2.0, 568 M de paramètres) via `transformers`, fp16 sur CUDA (~1,1 Go de VRAM), chargé une fois et partagé, scoring par lots
- le premier niveau (dense, lexical ou hybride) renvoie 40 candidats, le cross-encoder garde le top-k ; `rerank` activable à chaque requête sur l'API (y compris `/api/query/stream`), la CLI, le benchmark de recall, `raglab bench all --rerank` et l'UI
- chaque chunk porte ses scores et rangs dense, BM25, RRF et rerank ; étape `rerank` dans `timings_ms` et dans la latence de requête du benchmark
- cache LRU des scores par (modèle, question, chunk), taux de hit dans `rerank_stats`
- VRAM du cross-encoder libérée (`release()`) avant la passe du juge llama.cpp
- mesuré (`rerank-v1` = hybride + rerank, `rerank-dense-v1` = dense + rerank) : contre `hybrid-v1`, MRR +0.122 sur PIAF et +0.137 sur LexML, Recall@5 +0.066 / +0.098, tous significatifs, 0 et 2 questions perdues ; paraphrases LexML Recall@5 0.602 → 0.796 ; questions `reference` toujours à 0.093 (9.4) ; l'hybride reste le meilleur générateur de candidats ; correctness RAGAS +0.05 / +0.10, faithfulness LexML −0.035 ; latence ajoutée p50 423 / 612 ms (p95 544 / 844 ms), au-delà du budget de 200 ms ; pic de VRAM 7,6 Go sur 8 avec qwen2.5:7b ; cache à ~0 % de hit sur un premier passage. activé par défaut à la demande du propriétaire (`RAGLAB_DEFAULT_RERANK=true`, mode `hybrid` par défaut) ; sans GPU utilisable, le re-ranking par défaut est sauté et la réponse l'indique (`rerank_notice`, `RAGLAB_RERANK_WITHOUT_GPU=skip|cpu`) ; une demande explicite tourne sur CPU

**9.3b — Résolveur de citations juridiques ✅ (PR #39)** : voir [citations.md](citations.md)

- lecture de « art. N da Lei nº X » dans la question, recherche restreinte à cette loi (métadonnée `number` du document), article cité épinglé en tête, y compris après le re-ranking ; activé par défaut (`RAGLAB_CITATION_RESOLVER=true`), option `citations` sur l'API, la CLI, le benchmark et l'UI (badge « article cité »)
- mesuré : questions `reference` Recall@5 0.093 → 0.753 (`citations-v1`, dense) et 0.722 (`full-v1`, hybride + rerank + citations), +61 / −0, p < 0,001 ; 0.083 → 0.722 sur les 72 questions jamais regardées pendant la mise au point
- configuration complète `full-v1` contre `baseline-v1` : LexML Recall@5 0.466 → 0.816, MRR 0.379 → 0.694 ; PIAF Recall@5 0.878 → 0.966 ; correctness LexML 0.451 → 0.598, faithfulness 0.903 → 0.895 ; latence de recherche p50 635 / 728 ms (re-ranking ~600 ms)

**9.5 — Durcissement API ✅ (fusionnée dans la branche 9.1b, PR #28 et #29)** : voir [api-production.md](api-production.md)

- `POST /api/query/stream` en SSE : événement `retrieval` (chunks, scores, timings) avant la génération, puis `token` au fil d'Ollama (`stream: true`), puis `done` (QueryResponse complète + `first_token_ms`) ou `error` ; `/api/query` inchangé ; page Chat en streaming avec repli automatique sur `/api/query` ; `raglab query --stream`
- budgets par étape (`RAGLAB_EMBED_TIMEOUT_SECONDS`, `RAGLAB_RETRIEVAL_TIMEOUT_SECONDS` via `statement_timeout` Postgres, `RAGLAB_GENERATION_TIMEOUT_SECONDS` total en streaming), 504 qui nomme l'étape
- `X-Request-ID` accepté ou généré, renvoyé, présent dans chaque ligne de log de la requête (ContextVar) ; ligne d'accès `http.request`
- clé d'API optionnelle (`RAGLAB_API_KEY`, en-tête `X-API-Key` ou Bearer, bouton dans l'interface) ; rate limit en mémoire par clé ou IP, 429 + `Retry-After`
- `/health` (liveness, sans dépendance) et `/ready` (Postgres, Ollama, modèle par défaut installé) ; `/api/health` conservé pour le Dashboard
- erreurs Ollama typées : modèle absent 424 (message actionnable), mémoire saturée 503 + `Retry-After`, injoignable 502, timeout 504
- mesuré sans GPU (`scripts/bench_api_hardening.py`) : sources affichées après ~65 ms au lieu de ~3,4 s, premier token à 366 ms (préremplissage simulé 300 ms) ; middlewares +0,16 ms par requête ; TTFT réel sur GPU à mesurer
- migrations Alembic : introduites avec 9.2 (`feature/hybrid-retrieval`), aucune migration dans cette PR

- **Mode pédagogique (vitrine, en revue)** : bouton « Mode pédagogique » dans la barre du haut ; schéma SVG du pipeline à côté du Chat qui s'allume étape par étape via les événements SSE `pipeline` / `stage` (durée, compteurs, vecteur de la question, meilleurs passages et scores, aperçu du prompt, tokens/s) avec explication de chaque brique ; les étapes 9.2 / 9.3 / 9.4 apparaissent d'elles-mêmes une fois fusionnées. Voir [frontend-ui.md](frontend-ui.md#mode-pédagogique-schéma-du-pipeline-en-direct)

- **9.7 — Portes de qualité (outillage en place)** : `raglab gate` et seuils versionnés dans `benchmarks/thresholds.json` (à fixer depuis `baseline-v1`), workflow hebdomadaire de retrieval sur CPU, voir [portes-qualite.md](portes-qualite.md)

**9.6 — Observabilité ✅ (PR #34)** : voir [observabilite.md](observabilite.md)

**9.9 — Graphe des citations 🚧 (9.9a en revue)** : mode d'échec « renvois », voir [graphe.md](graphe.md)

- 9.9a 🚧 (en revue) : graphe structuré dans Neo4j, construit à l'indexation à partir des chunks PostgreSQL (et par `raglab graph build`, `POST /api/graph/build`, la page Expert « Graphe des renvois »). Socle commun `Document → Section → Chunk` (`PART_OF`, `NEXT`) et profil « lois » : `Law`, `Article`, `CITES`, `AMENDS`, `REVOKES`, extraits par règles, sans LLM. Mesuré sur LexML : 3 984 articles, 1 078 renvois article → article (98 entre lois du corpus), 1 054 `AMENDS`, 274 `REVOKES`, build en 6 s ; précision vérifiée à la main sur un tirage jamais regardé (graine 43) : 0,983 sur `CITES`, 0,900 sur `AMENDS` / `REVOKES` ; 97 des 100 questions LexML qui citent un article tombent sur un nœud `Article` (90 avec la réponse dans l'article). Le store Neo4j à entités extraites par LLM (phase 8) passe derrière `RAGLAB_ENTITY_GRAPH_ENABLED`.
- 9.9b 🚧 (code en revue, mesure à faire) : troisième branche de recherche en parallèle de la recherche dense et de BM25 (départs : l'article cité par la question et ceux des meilleurs passages ; `CITES` un saut), fusion RRF à trois sources, puis re-ranking ; un passage trouvé par renvoi reste groupé avec celui qui le cite. Sans Neo4j, la branche est sautée et la réponse le dit (`graph_notice`). Option `graph` sur la CLI, l'API et l'UI, désactivée par défaut tant qu'elle n'est pas mesurée. Générateur du jeu figé d'environ 100 questions « à renvoi » (`raglab lexml reference-questions`, partage `dev` / `heldout`) ; génération et comparaison appariée sur PIAF, LexML et le jeu « renvois » à lancer sur GPU.
- 9.9c (plus tard) : profils markdown / documentation et articles de recherche (`Section`, `Topic`, `Source`, `Author`, `Reference`), avec un corpus de test dédié.

**9.10 — Versions des textes 🚧 (code en revue, mesure à faire)** : mode d'échec « versions », voir [versions.md](versions.md)

- corpus : Code de la consommation avec tout son historique (1 352 articles réécrits, 1 586 versions abrogées, 321 numéros réutilisés en 2016) ; LexML : 70 lois sur 252 ont des articles réécrits (863 « Redação dada pela »), 79 ont des articles abrogés (1 084 « (Revogado) »), 1 239 articles insérés
- option `versions` sur la CLI, l'API et l'UI, défaut livré `all` (toutes les versions, comme avant) tant que la mesure n'est pas faite : `in_force` (versions en vigueur aujourd'hui, ou à la date que demande la question, « avant 2016 », lue en français, portugais et anglais), `as_of=AAAA-MM-JJ`, `all` (comme un RAG classique) ; filtre SQL avant le classement sur les métadonnées de Légifrance, version de la date pour l'article cité, passages entièrement « (Revogado) » en fin de liste et dispositions abrogées masquées au modèle sur LexML ; état de chaque passage dans la réponse, le prompt, l'interface et une étape « Versions » du mode pédagogique
- générateur du jeu figé d'environ 100 questions pièges (`raglab legifrance version-questions`, suite `legi_versions` : réécrit, numéro réutilisé, article déplacé, question sur le passé ; `trap` et partie `dev` / `heldout`) ; métriques `outdated_hit@k` et `outdated_answer_rate`, comparées question par question par `raglab bench compare` ; génération et mesures à lancer sur GPU

**Corpus français 🚧 (bloc C1 de l'audit)** : voir [corpus-legi.md](corpus-legi.md)

- `raglab legifrance fetch --code consommation` : Code de la consommation avec tout son historique (données LEGI de la DILA via le dépôt git tricoteuses du code, figé sur un commit), un document par version d'article, état, dates, textes modificatifs et renvois dans les métadonnées ; 5 998 versions de 3 391 articles (2 106 en vigueur), 3 593 renvois internes, 1 352 articles réécrits, 321 numéros réutilisés par la recodification de 2016
- résolveur de citations, profil français (« article L. 221-18 du code de la consommation », « l'article 1240 du code civil »), suite `legi_consommation` (sur demande), générateur de questions avec partie `dev` / `heldout` ; questions et mesures à lancer

**Corpus de conformité UE 🚧** : voir [corpus-eurlex.md](corpus-eurlex.md)

- `raglab eurlex fetch` : 15 actes de l'UE (RGPD, AI Act, DORA, NIS 2, actes délégués et d'exécution, omnibus numérique sur l'IA) en français, anglais et portugais, depuis CELLAR (sans compte), versions consolidées figées ; un document par considérant, article ou annexe, par langue et par version : 4 236 documents, 9 632 renvois en vigueur dont 1 395 d'un acte à l'autre, 38 articles de l'AI Act réécrits par l'omnibus de 2026
- résolveur de citations, profil UE (« article 32 du RGPD », « Article 6(1)(a) GDPR », « considérant 39 ») ; graphe, profil `eu_acts` (`CITES`, `EXPLAINS`, `SUPPLEMENTS`, `AMENDS`, `SAME_AS`), précision relue 39/39 ; suite `eurlex_compliance` (sur demande) et générateur de questions (`scenario` majoritaire, `cross_reference`, `cross_language`) ; questions et mesures à lancer

**Mode Démo 📋 (planifié)** : questions pièges pré-remplies (une par mode d'échec), bouton « Comparer : RAG classique / raglab » qui affiche les deux réponses et leurs passages côte à côte, description de chaque corpus dans le sélecteur, pages Expert secondaires rangées dans une section « Outils ».

- `GET /metrics` (Prometheus) : latence par étape (embed, retrieval, citation, dense, lexical, fusion, rerank, generation : chaque clé de `timings_ms`), tokens/s, score top-1, requêtes par route et statut, compteurs de cache (`embedder`, `reranker` depuis `rerank_stats`), re-ranking sans GPU (`raglab_rerank_notices_total`) et abstention (9.4) ; labels à faible cardinalité (gabarits de route)
- profil Compose `obs` : Prometheus v3.5.0 et Grafana 12.1.1, ports sur 127.0.0.1, source de données et tableau de bord versionnés, lecture anonyme
- `raglab experiment drift` et `POST /api/experiments/drift` : test KS sur les distributions de scores et de rangs, écarts des moyennes RAGAS / MRR / recall entre deux index runs, experiment runs ou fenêtres de dates ; Markdown ou JSON, `--fail-on-drift` ; scores désormais stockés dans `metrics_json.retrieved_scores`
- coût mesuré sans GPU (`scripts/bench_observability.py`) : +105 µs sur une requête simulée de 60 ms (+0,17 %, objectif < 1 %) ; capture Grafana sur trafic réel dans [observabilite.md](observabilite.md#profil-compose-obs)

**À venir** : 9.4 compréhension de la requête et abstention · 9.7 portes de qualité · 9.8 vitrine
