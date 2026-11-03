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

## 5. Hypothèses à tester

Rien n'est encore mesuré : les chiffres viendront après la baseline 9.1b, sur les mêmes jeux figés (PIAF 500 questions, LexML 277 questions typées), avec Recall@5/10, MRR et latence p50/p95.

1. **Références (numéros de loi, d'article).** Sur les questions LexML `reference`, le mode hybrid améliore le Recall@5 par rapport au dense. Les tokens `8.666`, `5º` ou `9.610` survivent tels quels au parseur, et leur IDF est élevée.
2. **Entités et noms propres.** Sur les questions LexML `entity` et sur PIAF, BM25 seul est proche du dense, et l'hybride le dépasse. Les noms rares apparaissent dans peu de chunks, donc leur IDF est forte.
3. **Acronymes.** `CNPJ`, `INSS`, `ANVISA` : même effet attendu que pour les noms propres. Attention : les acronymes en minuscules sont racinisés, et un sigle court peut tomber sur un mot vide.
4. **Paraphrases.** Sur les questions `paraphrase`, le lexical seul est nettement en dessous du dense. L'hybride ne doit pas faire moins bien que le dense : si c'est le cas, baisser `lexical_weight`.
5. **Latence.** BM25 reste sous le temps du chemin dense (embedding de la question + KNN) sur environ 10 000 chunks, et le mode `lexical` évite le chargement de l'embedder. À vérifier contre un embedder mis en cache sur GPU (9.1b) : le KNN seul prend environ 8 ms, et BM25 environ 20 ms sur LexML.
6. **Réglages.** Balayer `lexical_weight` ∈ {0.25, 0.5, 0.75} et `rrf_k` ∈ {10, 60}. On s'attend à une zone plate autour des valeurs par défaut. Si ce n'est pas le cas, le gain vient d'un réglage fait sur le jeu de test : le signaler comme tel.

Limites connues :

- la racinisation Snowball est approximative : en portugais, « são » est un mot vide, donc « São Paulo » devient `paul` ;
- un mot rare mal orthographié dans la question n'a aucun candidat, et BM25 ne trouve alors rien ;
- les statistiques sont figées par run : ré-indexer après une ingestion importante.
