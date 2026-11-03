# Retrieval hybride : BM25 + RRF (phase 9.2)

Le retrieval dense (embeddings + KNN cosinus) comprend bien les paraphrases. Il se trompe en revanche sur des chaînes exactes : un acronyme (`CNPJ`, `INSS`), un numéro d'article ou de loi (`art. 5º`, `Lei 8.666/1993`), un nom propre rare. Un embedding de 384 ou 1024 dimensions résume le sens du passage. Il ne garantit pas que le chunk qui contient littéralement « 8.666 » sorte devant un chunk voisin qui parle d'une autre loi.

La phase 9.2 ajoute un second retriever, lexical (BM25), et la fusion des deux listes par Reciprocal Rank Fusion. Le choix se fait par un paramètre `retrieval_mode`, distinct du `mode` du store graphe :

| `retrieval_mode` | Ce qui tourne | Score renvoyé |
|---|---|---|
| `dense` (défaut) | embedding de la question + KNN pgvector, comme avant | similarité cosinus |
| `lexical` | BM25 calculé dans PostgreSQL, sans embedder | score BM25 |
| `hybrid` | les deux, puis RRF | score RRF |

Chaque chunk renvoyé porte aussi ses scores intermédiaires : `dense_score` / `dense_rank`, `lexical_score` / `lexical_rank`, `fused_score`. Un champ vaut `null` quand ce retriever n'a pas tourné, ou n'a pas trouvé le chunk dans ses candidats. La réponse contient aussi `query_lexemes`, les lexèmes auxquels la question a été réduite pour BM25.

## 1. Index lexical

### tsvector par chunk

`chunks.lexical_tsv` contient le `tsvector` du texte du chunk, avec un index GIN (`ix_chunks_lexical_tsv`). `chunks.lexical_length` contient le nombre de tokens du chunk, c'est-à-dire la somme des positions : c'est le |d| de BM25, différent du nombre de lexèmes distincts.

La configuration de recherche plein texte dépend de la langue du document. On prend la première valeur définie parmi :

1. `documents.metadata_json.language` (les sidecars LexML déclarent `pt`) ;
2. `corpora.language`, renseignée par `raglab ingest --language`, sinon lue dans le `metadata.json` écrit par les loaders de benchmark (PIAF : `fr`) ;
3. le réglage `RAGLAB_DEFAULT_LANGUAGE` (défaut `fr`).

| Langue | Configuration | Chaîne appliquée aux mots |
|---|---|---|
| `fr` | `raglab_french` | mots vides français → `unaccent` → `french_stem` |
| `pt` | `raglab_portuguese` | mots vides portugais → `unaccent` → `portuguese_stem` |
| autre | `raglab_simple` | `unaccent` → `simple` (ni racinisation ni mots vides) |

Les mots vides sont retirés **avant** `unaccent`. Les listes de PostgreSQL sont accentuées : une fois « à » ou « été » désaccentués, la liste du stemmer ne les reconnaît plus. Les nombres et les tokens comme `8.666`, `5º` ou `/1993` ne passent pas par ces dictionnaires et restent tels quels.

La résolution de la langue est écrite en Python (`raglab.db.lexical`) et traduite en un `CASE` SQL équivalent. Ainsi, recalculer un run se fait en quelques requêtes ensemblistes.

### Statistiques par run

BM25 a besoin de statistiques sur la collection. On les stocke par `index_run`, si bien que l'IDF d'un terme ne dépend que du run interrogé :

- `lexical_index_stats` : `doc_count` (N), `avg_length` (avgdl), `ts_configs` (les configurations présentes dans le run) ;
- `lexical_term_stats` : `doc_freq` de chaque lexème du run.

Ces statistiques sont recalculées à la fin de chaque indexation. La migration `0002_hybrid_lexical` les calcule pour les runs existants : un run indexé avant la 9.2 est donc interrogeable en lexical sans ré-indexation.

Si la langue d'un corpus change, `raglab db refresh-lexical --corpus <nom>` recalcule les tsvectors et les statistiques sans recalculer les embeddings.

## 2. Score BM25

`ts_rank` n'a pas d'IDF : ce n'est pas BM25. Le score est donc calculé explicitement en SQL (Okapi BM25, IDF de Lucene, toujours positive) :

```
idf(t)      = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(d, q) = Σ  idf(t) · tf(t,d) · (k1 + 1) / (tf(t,d) + k1 · (1 - b + b · |d| / avgdl))
            t ∈ q ∩ d
```

`k1 = 1.2` et `b = 0.75` par défaut (`RAGLAB_BM25_K1`, `RAGLAB_BM25_B`).

Déroulé d'une requête :

1. la question est réduite en lexèmes avec **chaque** configuration du run, souvent une seule ;
2. les lexèmes sont combinés en OU (`'lei' | '8.666' | …`) : un chunk devient candidat s'il en contient un seul. L'index GIN trouve les candidats, croisé avec l'index sur `index_run_id` ;
3. le score se calcule sur les candidats, en dépliant leur `tsvector` (`unnest`) et en le joignant aux IDF des lexèmes de la question. Les filtres (documents, tags, métadonnées) s'appliquent aux candidats comme pour le dense.

Deux détails comptent pour la latence :

- **filtrer avant de déplier.** `setweight(tsv, 'A', lexèmes)` puis `ts_filter(…, '{a}')` ne gardent que les lexèmes de la question dans le `tsvector` de chaque candidat. Le `unnest` lit alors un ou deux termes par chunk au lieu de tout le vecteur, soit environ 5 fois moins de travail sur LexML ;
- **termes fréquents.** « lei », « art » ou « nº » apparaissent dans la plupart des chunks LexML : en OU, presque tout le run devient candidat. On sélectionne donc d'abord les candidats avec les seuls termes rares (df ≤ 20 % de N), en les notant quand même sur tous les termes. Un chunk sans terme rare a un score strictement inférieur à Σ idf(t)·(k1+1) sur les termes fréquents. Si le k-ième score de cette première passe atteint cette borne, le top-k est exact ; sinon on relance la requête OU complète. C'est l'idée de MaxScore : le résultat est identique, vérifié sur les 300 questions LexML et les 500 PIAF (k = 10 et 50), seul le travail change.

Contrôle de cohérence sur `raglab_hybrid` (CPU, PostgreSQL 16 en Docker), qui n'est pas la mesure de la phase : sur LexML (6 075 chunks), BM25 répond en 19 ms au p50 et 33 ms au p95 pour k = 10, contre 32 et 45 ms sans la première passe ; sur PIAF (833 chunks), 7 et 10 ms.

Le test `tests/test_bm25_postgres.py` compare le score SQL à un calcul fait à la main sur un corpus de trois chunks, et vérifie que la première passe rend le même top-k que la requête complète.

## 3. Fusion RRF

```
fused(d) = (1 - w) / (k + rang_dense(d)) + w / (k + rang_bm25(d))
```

- `k = 60` par défaut (`rrf_k`, `RAGLAB_RRF_K`) : plus k est petit, plus les premiers rangs pèsent ;
- `w` = `lexical_weight` (défaut `0.5`, `RAGLAB_HYBRID_LEXICAL_WEIGHT`) : `0` garde l'ordre dense, `1` l'ordre BM25, `0.5` donne la RRF classique ;
- un chunk absent d'une liste ne reçoit rien de cette liste ;
- en cas d'égalité, on départage par le meilleur rang individuel, puis par l'identifiant du chunk.

La RRF n'utilise que les rangs. On n'a donc jamais à calibrer une similarité cosinus contre un score BM25 dont l'échelle dépend de la requête.

Chaque retriever renvoie `max(top_k, RAGLAB_HYBRID_CANDIDATES)` candidats (défaut 50) avant la fusion : un chunk classé 30ᵉ en dense et 2ᵉ en BM25 doit rester visible pour la RRF.

## 4. Où le régler

| Surface | Paramètres |
|---|---|
| API `POST /api/query` | `retrieval_mode`, `lexical_weight`, `rrf_k` |
| CLI `raglab query` | `--retrieval-mode`, `--lexical-weight`, `--rrf-k` |
| Benchmark `raglab experiment recall`, `POST /api/experiments/recall` | mêmes paramètres, enregistrés dans `experiment_runs.config_json` et dans le rapport |
| UI Retrieval (mode expert) | sélecteur de mode ; poids et k en mode hybrid ; scores dense / BM25 / RRF par chunk ; lexèmes ; temps par étape |
| UI Benchmarks | sélecteur de mode au lancement (backend pgvector) ; mode affiché dans l'historique |

La CLI et l'API passent les mêmes arguments à `QueryService` et renvoient le même JSON (`tests/api/test_api_hybrid_parity.py`).

Les temps par étape (`timings_ms`) gardent `embed` et `retrieval` : le benchmark les additionne pour sa latence de requête. S'y ajoutent `dense`, `lexical` et `fusion`. En mode `lexical`, `embed` vaut 0 : aucun modèle n'est chargé.

## 5. Résultats mesurés (`hybrid-v1`, `lexical-v1`)

Mesures du 3 novembre 2026, faites selon [le protocole](benchmarks/protocole.md) sur les jeux figés (PIAF : 500 questions, LexML : 277 questions typées), avec les mêmes index_runs que `baseline-v1` (chunking `traditional`, multilingual-e5-small, recherche dense exacte). `lexical_weight = 0.5`, `rrf_k = 60`, 50 candidats par retriever. Les juges RAGAS (Gemma 4 26B-A4B via llama.cpp) portent sur les 100 premières questions de chaque jeu, générées depuis le top-5. `lexical-v1` ne mesure que le retrieval. Fichiers : `benchmarks/results/{baseline-v1,hybrid-v1,lexical-v1}.json`.

### Vue d'ensemble

| Métrique | baseline-v1 (dense) | lexical-v1 (BM25) | hybrid-v1 (RRF) |
|---|---|---|---|
| PIAF Recall@1 | 0.672 | 0.654 | 0.688 |
| PIAF Recall@5 | 0.878 | 0.838 | 0.900 |
| PIAF Recall@10 | 0.898 | 0.874 | 0.940 |
| PIAF MRR | 0.758 | 0.730 | 0.778 |
| LexML Recall@1 | 0.325 | 0.332 | 0.329 |
| LexML Recall@5 | 0.466 | 0.477 | 0.498 |
| LexML Recall@10 | 0.502 | 0.513 | 0.563 |
| LexML MRR | 0.379 | 0.395 | 0.402 |
| PIAF faithfulness / relevancy / correctness | 0.930 / 0.900 / 0.658 | non jugé | 0.915 / 0.870 / 0.643 |
| LexML faithfulness / relevancy / correctness | 0.903 / 0.725 / 0.451 | non jugé | 0.888 / 0.735 / 0.435 |

### Comparaison appariée (`raglab bench compare`)

Recall@5 : test de McNemar question par question ; MRR : bootstrap apparié (IC 95 %). ✱ = significatif.

| Jeu | Questions | baseline-v1 → hybrid-v1, Recall@5 | gagnées / perdues | p | MRR (IC 95 % de l'écart) |
|---|---|---|---|---|---|
| PIAF | 500 | 0.878 → 0.900 (+0.022) | +25 / −14 | 0.108 | 0.758 → 0.778 [−0.002 ; +0.041] |
| LexML | 277 | 0.466 → 0.498 (+0.033) | +21 / −12 | 0.163 | 0.379 → 0.402 [−0.008 ; +0.051] |
| LexML · entity | 87 | 0.793 → 0.839 (+0.046) | +6 / −2 | 0.289 | 0.679 → 0.723 [−0.010 ; +0.097] |
| LexML · paraphrase | 93 | 0.548 → 0.602 (+0.054) | +12 / −7 | 0.359 | 0.432 → 0.445 [−0.045 ; +0.070] |
| LexML · reference | 97 | 0.093 → 0.093 (+0.000) | +3 / −3 | 1.000 | 0.059 → 0.072 [−0.025 ; +0.056] |

| Jeu | baseline-v1 → hybrid-v1, Recall@10 | gagnées / perdues | p |
|---|---|---|---|
| PIAF | 0.898 → 0.940 (+0.042) ✱ | +28 / −7 | 0.001 |
| LexML | 0.502 → 0.563 (+0.061) ✱ | +21 / −4 | 0.001 |
| LexML · entity | 0.793 → 0.919 (+0.126) ✱ | +11 / −0 | 0.001 |
| LexML · paraphrase | 0.624 → 0.677 (+0.054) | +7 / −2 | 0.180 |
| LexML · reference | 0.124 → 0.134 (+0.010) | +3 / −2 | 1.000 |

| Jeu | baseline-v1 → lexical-v1, Recall@5 | gagnées / perdues | p |
|---|---|---|---|
| PIAF | 0.878 → 0.838 (−0.040) ✱ | +28 / −48 | 0.029 |
| LexML | 0.466 → 0.476 (+0.011) | +24 / −21 | 0.766 |
| LexML · entity | 0.793 → 0.874 (+0.081) | +11 / −4 | 0.118 |
| LexML · paraphrase | 0.548 → 0.538 (−0.011) | +11 / −12 | 1.000 |
| LexML · reference | 0.093 → 0.062 (−0.031) | +2 / −5 | 0.453 |

### Latence (p50 / p95, embedding + recherche, génération exclue)

| | baseline-v1 | lexical-v1 | hybrid-v1 |
|---|---|---|---|
| PIAF (833 chunks) | 23 / 28 ms | 6.6 / 10.7 ms | 43 / 61 ms |
| LexML (6 075 chunks) | 41 / 68 ms | 19 / 34 ms | 88 / 126 ms |

| Décomposition du p50 | embedding | recherche dense | BM25 | fusion |
|---|---|---|---|---|
| PIAF, baseline-v1 (10 candidats) | 12.6 ms | 10.9 ms | — | — |
| PIAF, hybrid-v1 (50 candidats) | 15.2 ms | 15.9 ms | 10.9 ms | 0.6 ms |
| LexML, baseline-v1 (10 candidats) | 15.8 ms | 24.7 ms | — | — |
| LexML, hybrid-v1 (50 candidats) | 18.0 ms | 41.7 ms | 25.0 ms | 0.5 ms |

**L'hybride double la latence de recherche** (+20 ms au p50 sur PIAF, +47 ms sur LexML). Deux causes, à peu près à parts égales sur LexML :

- BM25 lui-même : 11 ms (PIAF) et 25 ms (LexML) au p50 ;
- la profondeur des candidats : la recherche dense rend 50 chunks au lieu de 10. Le calcul des distances ne change pas, mais `PostgresVectorStore.search` charge chaque document entier, y compris `documents.content` (le texte complet de la loi pour LexML), pour chaque candidat. À code égal, passer de 10 à 50 candidats coûte environ 13 ms sur LexML (22 → 35 ms au p50, mesuré à part).

Le second point se corrige sans toucher aux résultats : ne charger que les colonnes utiles du document dans la recherche dense, comme le fait déjà BM25. On peut aussi réduire `RAGLAB_HYBRID_CANDIDATES`. Seul, BM25 répond en 7 ms (PIAF) et 19 ms (LexML), sans charger d'embedder.

### Ce que disent les chiffres

1. **L'hybride gagne surtout en profondeur.** Le Recall@10 progresse significativement sur les deux jeux (+0.042 sur PIAF, +0.061 sur LexML, +0.126 sur les questions `entity`). Au Recall@5 et au MRR, les écarts vont dans le bon sens partout sauf `reference`, mais aucun n'est significatif à 500 / 277 questions. Le gain est donc réel pour un étage qui reclasse un top-10 ou plus (re-ranking 9.3), plus mince pour un top-5 envoyé directement au LLM.
2. **L'hypothèse principale est réfutée : les questions `reference` ne bougent pas** (Recall@5 0.093 → 0.093). L'analyse des 97 questions montre pourquoi. Elles ont la forme « Que dispõe o art. 2 da Lei nº 7.689 ? ». Le numéro de loi n'apparaît que dans le premier chunk du document (son titre), et les chunks des articles ne disent que « Art. 2º », comme toutes les autres lois. BM25 retrouve bien la loi : la bonne loi est dans le top-5 pour 91 questions sur 97, dans le top-10 pour 95. Mais il ne retrouve pas l'article, parce que `art` et `2` sont des termes présents partout. Le problème n'est pas le score lexical, c'est que le passage visé ne contient aucun terme qui le distingue sans le contexte du document. Pistes, hors 9.2 :
   - comprendre la requête (9.4) : extraire « loi X, article N », filtrer sur le document de la loi X puis chercher l'article N dans ses chunks ;
   - indexer avec chaque chunk le titre de son document, dans le `tsvector` seulement, sans toucher au texte ni aux chunkers.
3. **Entités : le lexical fait mieux que le dense, l'hybride encore mieux.** Sur `entity`, BM25 seul passe de 0.793 à 0.874 au Recall@5 et l'hybride atteint 0.919 au Recall@10 sans perdre une seule question (+11 / −0) : les noms propres rares sont bien servis par l'IDF.
4. **BM25 seul perd en français.** Sur PIAF, le lexical seul perd significativement (Recall@5 −0.040, 48 questions perdues contre 28 gagnées) : les questions PIAF reformulent le paragraphe, ce que le dense capte mieux. L'hybride ne perd pas cet avantage (+0.022).
5. **Juges RAGAS légèrement en baisse.** Faithfulness −0.015 sur les deux jeux, answer relevancy −0.030 (PIAF) et +0.010 (LexML), correctness −0.015 (PIAF) et −0.016 (LexML). Ces écarts portent sur 100 réponses par jeu et n'ont pas d'intervalle de confiance ; ils restent à surveiller, mais ne permettent pas de conclure à une dégradation.
6. **Hypothèses non testées.** Pas de type de question « acronyme » dans les jeux, et pas de balayage de `lexical_weight` / `rrf_k` : les deux runs utilisent les valeurs par défaut, qui n'ont donc pas été réglées sur le jeu de test.

**Recommandation.** Garder `RAGLAB_DEFAULT_RETRIEVAL_MODE=dense` par défaut tant que le gain au top-5 n'est pas significatif et que la latence double, et utiliser `hybrid` comme générateur de candidats pour le re-ranking (9.3), là où le gain au top-10 compte. Le mode `lexical` seul n'est pas recommandé. La décision revient au propriétaire.

### Limites connues

- la racinisation Snowball est approximative : en portugais, « são » est un mot vide, donc « São Paulo » devient `paul` ;
- un mot rare mal orthographié dans la question n'a aucun candidat, et BM25 ne trouve alors rien ;
- les statistiques sont figées par run : ré-indexer (ou `raglab db refresh-lexical`) après une ingestion importante.
