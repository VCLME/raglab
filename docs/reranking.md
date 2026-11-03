# Re-ranking cross-encoder (phase 9.3)

Le retrieval de premier niveau (dense, lexical ou hybride) note chaque chunk sans jamais lire la question et le chunk ensemble : l'embedding de la question est comparé à des embeddings calculés à l'indexation, ou ses lexèmes sont comptés dans le chunk. Un cross-encoder lit au contraire la paire (question, chunk) d'un seul tenant, avec l'attention croisée entre les deux textes. Il est bien plus précis, mais trop lent pour parcourir tout l'index. On l'applique donc à une liste courte.

```
question ──► retrieval (dense | lexical | hybrid) ──► rerank_candidates chunks
                                                         │
                                         cross-encoder (question, chunk) × N
                                                         │
                                                         ▼
                                                  top_k chunks réordonnés
```

## Modèle

`BAAI/bge-reranker-v2-m3` (Apache-2.0, 568 M de paramètres, base XLM-RoBERTa large, multilingue : français et portugais). Il est chargé avec `transformers` (`AutoModelForSequenceClassification`) :

- fp16 sur CUDA quand un GPU est disponible, fp32 sur CPU sinon ;
- chargé une seule fois par configuration (modèle, device, batch, longueur max, taille du cache) et partagé entre les requêtes, comme l'embedder ; un verrou sérialise les passes avant sur le GPU ;
- scoring par lots de `RAGLAB_RERANK_BATCH_SIZE` paires, tronquées à `RAGLAB_RERANK_MAX_LENGTH` tokens (c'est le chunk qui est coupé, pas la question) ;
- le score renvoyé est le logit brut du modèle : seul l'ordre compte, il n'est pas comparable à une similarité cosinus.

## Utilisation

Le re-ranking est un booléen `rerank`, modifiable à chaque requête. Absent, il prend la valeur de `RAGLAB_DEFAULT_RERANK` (désactivé par défaut tant que le gain n'est pas mesuré).

| Surface | Paramètre |
|---|---|
| `QueryService.retrieve` / `query` | `rerank=True` |
| `POST /api/query`, `POST /api/query/stream` | `"rerank": true` |
| `raglab query` | `--rerank` / `--no-rerank` |
| `raglab experiment recall`, `POST /api/experiments/recall` | `--rerank` / `"rerank": true` |
| `raglab bench all` | `--rerank` (et `--retrieval-mode` pour re-classer les candidats hybrides) |
| UI, page Retrieval (mode Expert) | liste « Re-ranking cross-encoder » |
| UI, page Benchmarks | case « Re-ranking cross-encoder » au lancement |

Avec `rerank`, le premier niveau renvoie `max(top_k, RAGLAB_RERANK_CANDIDATES)` chunks (40 par défaut). En mode hybride, chaque retriever en cherche au moins `RAGLAB_HYBRID_CANDIDATES` avant la fusion, comme sans re-ranking. Le cross-encoder note ces candidats et garde les `top_k` meilleurs. En cas d'égalité, l'ordre du premier niveau est conservé.

Chaque chunk renvoyé garde la vue du premier niveau et y ajoute celle du cross-encoder :

| Champ | Contenu |
|---|---|
| `score`, `rank` | ceux du cross-encoder quand `rerank` est actif, sinon ceux du mode demandé |
| `dense_score`, `dense_rank` | similarité cosinus et rang dans la liste dense |
| `lexical_score`, `lexical_rank` | score BM25 et rang dans la liste lexicale |
| `fused_score`, `fused_rank` | score et rang RRF (mode hybride) |
| `rerank_score`, `rerank_rank` | logit et rang du cross-encoder |

La réponse contient `rerank: true` et `rerank_stats` (voir le cache ci-dessous). `timings_ms` gagne l'étape `rerank`. Le benchmark de recall l'ajoute à la latence de requête (`latency_query_*` = embed + recherche + re-ranking) et publie `latency_rerank_p50_ms` / `latency_rerank_p95_ms`. La page Retrieval affiche, pour chaque chunk, les rangs et scores dense, BM25, RRF et rerank côte à côte : on voit directement quel chunk le cross-encoder a fait monter.

## Cache des scores

Un chunk ne change pas de texte sous un même identifiant, et le benchmark comme l'UI reposent souvent les mêmes questions. Les scores sont donc mis en cache par clé `(modèle, texte de la question, chunk_id)`, dans un LRU borné à `RAGLAB_RERANK_CACHE_SIZE` entrées (20 000 par défaut, quelques Mo ; 0 désactive le cache). Seules les paires absentes passent dans le modèle.

`rerank_stats` dans chaque réponse :

| Clé | Sens |
|---|---|
| `candidates` | chunks soumis au cross-encoder |
| `scored` | paires réellement calculées par le modèle |
| `cache_hits` | paires lues dans le cache |
| `cache_hit_rate` | `cache_hits / candidates` pour cette requête |
| `cache_size` | entrées dans le cache |
| `cache_hit_rate_total` | taux de hit depuis le démarrage du processus |

Le benchmark agrège `rerank_cache_hit_rate` sur le run. Sur un premier passage il vaut 0 : la latence `rerank` mesurée est alors celle du modèle. Un second passage identique la ramène presque à zéro, ce qui ne doit pas être confondu avec un gain du modèle. Les mesures se font donc sur un processus neuf (`raglab bench all` en lance un à chaque fois).

## Mémoire GPU

Le GPU de référence a 8 Go.

| Étape | Résident sur le GPU |
|---|---|
| retrieval + génération | qwen2.5:7b Q4 via Ollama (~4,9 Go) + cross-encoder fp16 (~1,1 Go de poids, plus les activations d'un lot) |
| passe du juge RAGAS | Gemma via llama.cpp (~7 Go) seul |

Le cross-encoder tient à côté de qwen2.5 pendant la génération. Il ne tient pas à côté du juge : avant la seconde passe du benchmark, `RecallBenchmarkService` appelle `release()`, qui supprime le modèle, lance le ramasse-miettes et vide le cache CUDA (`torch.cuda.empty_cache()`). Ensuite seulement, `LocalLLMServer` décharge Ollama et démarre llama-server. Le cache de scores, en RAM, est conservé ; la prochaine requête avec `rerank` recharge le modèle.

## Budget de latence

L'étape a son propre budget, `RAGLAB_RERANK_TIMEOUT_SECONDS` (60 s par défaut, 0 = sans limite). Un dépassement renvoie un 504 qui nomme l'étape `rerank`, comme pour `embed` et `retrieval`. Le délai est large parce que le premier appel charge le modèle depuis le disque.

Pour 40 candidats d'environ 900 caractères (~250 tokens avec la question) :

| Configuration | Estimation avant mesure | Mesuré (RTX 3070 Ti Laptop, p50 / p95) |
|---|---|---|
| GPU 8 Go, fp16, cache froid | ~100 à 200 ms | 423 / 544 ms (PIAF), 612 / 844 ms (LexML) |
| GPU, cache chaud | < 5 ms | non mesuré (taux de hit ~0 sur un premier passage) |
| CPU, fp32 | plusieurs secondes | non mesuré ; utile pour les tests seulement |
| premier appel du processus | + quelques secondes | ~8 s, chargement des poids (~2,2 Go sur disque) compris |

Le budget visé était de 200 ms ajoutées au p50 sur GPU : **il est dépassé d'un facteur 2 à 3** (voir [Mesures](#mesures)). L'estimation sous-évaluait le coût d'XLM-R large sur un GPU portable. Le surcoût reste modeste à côté de la génération (2,2 s au p50 sur PIAF, 4,3 s sur LexML), mais il est dix fois la recherche elle-même. Les réglages qui pèsent sur la latence : `RAGLAB_RERANK_CANDIDATES` (linéaire), `RAGLAB_RERANK_MAX_LENGTH` (au plus linéaire) et `RAGLAB_RERANK_BATCH_SIZE` (moins de lots, plus de VRAM). Aucun n'a été balayé.

## Réglages

| Variable | Défaut | Rôle |
|---|---|---|
| `RAGLAB_DEFAULT_RERANK` | `false` | re-ranking quand la requête ne précise rien |
| `RAGLAB_RERANK_MODEL_NAME` | `BAAI/bge-reranker-v2-m3` | modèle Hugging Face |
| `RAGLAB_RERANK_DEVICE` | `cuda` | repli sur CPU si CUDA est absent |
| `RAGLAB_RERANK_CANDIDATES` | `40` | taille de la liste re-classée |
| `RAGLAB_RERANK_BATCH_SIZE` | `16` | paires par passe avant |
| `RAGLAB_RERANK_MAX_LENGTH` | `512` | tokens par paire |
| `RAGLAB_RERANK_CACHE_SIZE` | `20000` | entrées du LRU de scores (0 = désactivé) |
| `RAGLAB_RERANK_TIMEOUT_SECONDS` | `60` | budget de l'étape |

## Tests

`tests/test_rerank.py` et `tests/api/test_api_rerank_parity.py` remplacent le modèle par un scorer factice : aucun téléchargement en CI. Ils couvrent l'ordre, la troncature au top_k, les égalités, le cache (hits, clé, éviction LRU), le partage du modèle par configuration, `release()`, le découpage en lots du cross-encoder, la libération avant la passe du juge et la parité API / CLI / benchmark.

## Mesures

Mesures du 3 novembre 2026, faites selon [le protocole](benchmarks/protocole.md) sur les jeux figés (PIAF : 500 questions, LexML : 277 questions typées), avec les mêmes index_runs que `baseline-v1` et `hybrid-v1` (chunking `traditional`, multilingual-e5-small, recherche dense exacte), sur une RTX 3070 Ti Laptop (8 Go). Le premier niveau renvoie 40 candidats, le cross-encoder garde le top-5 (top-10 pour le Recall@10).

- `rerank-v1` : hybride (`lexical_weight = 0.5`, `rrf_k = 60`) + re-ranking, juges RAGAS (Gemma 4 26B-A4B via llama.cpp) sur les 100 premières questions de chaque jeu ;
- `rerank-dense-v1` : dense + re-ranking, retrieval seul.

Fichiers : `benchmarks/results/{rerank-v1,rerank-dense-v1}.json`, à comparer à `baseline-v1.json` et `hybrid-v1.json`.

### Vue d'ensemble

| Métrique | baseline-v1 (dense) | hybrid-v1 (RRF) | rerank-dense-v1 | rerank-v1 (RRF + rerank) |
|---|---|---|---|---|
| PIAF Recall@1 | 0.672 | 0.688 | 0.832 | 0.846 |
| PIAF Recall@5 | 0.878 | 0.900 | 0.952 | 0.966 |
| PIAF Recall@10 | 0.898 | 0.940 | 0.958 | 0.970 |
| PIAF MRR | 0.758 | 0.778 | 0.886 | 0.900 |
| LexML Recall@1 | 0.325 | 0.329 | 0.458 | 0.495 |
| LexML Recall@5 | 0.466 | 0.498 | 0.545 | 0.596 |
| LexML Recall@10 | 0.502 | 0.563 | 0.570 | 0.617 |
| LexML MRR | 0.379 | 0.402 | 0.498 | 0.539 |
| PIAF faithfulness / relevancy / correctness | 0.930 / 0.900 / 0.658 | 0.915 / 0.870 / 0.643 | non jugé | 0.905 / 0.920 / 0.693 |
| LexML faithfulness / relevancy / correctness | 0.903 / 0.725 / 0.451 | 0.888 / 0.735 / 0.435 | non jugé | 0.853 / 0.775 / 0.532 |

### Comparaison appariée (`raglab bench compare`)

Recall : test de McNemar question par question ; MRR : bootstrap apparié (IC 95 %). ✱ = significatif.

| Jeu | Questions | hybrid-v1 → rerank-v1, Recall@5 | gagnées / perdues | p | MRR (IC 95 % de l'écart) |
|---|---|---|---|---|---|
| PIAF | 500 | 0.900 → 0.966 (+0.066) ✱ | +33 / −0 | < 0.001 | 0.778 → 0.900 (+0.122) ✱ [+0.097 ; +0.146] |
| LexML | 277 | 0.498 → 0.596 (+0.098) ✱ | +29 / −2 | < 0.001 | 0.402 → 0.539 (+0.137) ✱ [+0.103 ; +0.175] |
| LexML · entity | 87 | 0.839 → 0.943 (+0.103) ✱ | +9 / −0 | 0.004 | 0.723 → 0.875 (+0.152) ✱ [+0.095 ; +0.210] |
| LexML · paraphrase | 93 | 0.602 → 0.796 (+0.194) ✱ | +19 / −1 | < 0.001 | 0.445 → 0.716 (+0.271) ✱ [+0.191 ; +0.357] |
| LexML · reference | 97 | 0.093 → 0.093 (+0.000) | +1 / −1 | 1.000 | 0.072 → 0.068 (−0.004) [−0.017 ; +0.008] |

| Jeu | baseline-v1 → rerank-v1, Recall@5 | gagnées / perdues | p | MRR (IC 95 % de l'écart) |
|---|---|---|---|---|
| PIAF | 0.878 → 0.966 (+0.088) ✱ | +45 / −1 | < 0.001 | 0.758 → 0.900 (+0.141) ✱ [+0.113 ; +0.168] |
| LexML | 0.466 → 0.596 (+0.130) ✱ | +41 / −5 | < 0.001 | 0.379 → 0.539 (+0.160) ✱ [+0.117 ; +0.205] |
| LexML · entity | 0.793 → 0.943 (+0.149) ✱ | +13 / −0 | < 0.001 | 0.679 → 0.875 (+0.196) ✱ [+0.127 ; +0.267] |
| LexML · paraphrase | 0.548 → 0.796 (+0.247) ✱ | +25 / −2 | < 0.001 | 0.432 → 0.716 (+0.283) ✱ [+0.189 ; +0.379] |
| LexML · reference | 0.093 → 0.093 (+0.000) | +3 / −3 | 1.000 | 0.059 → 0.068 (+0.009) [−0.025 ; +0.049] |

| Jeu | hybrid-v1 → rerank-v1, Recall@10 | gagnées / perdues | p |
|---|---|---|---|
| PIAF | 0.940 → 0.970 (+0.030) ✱ | +15 / −0 | < 0.001 |
| LexML | 0.563 → 0.617 (+0.054) ✱ | +17 / −2 | 0.001 |
| LexML · entity | 0.919 → 0.943 (+0.023) | +2 / −0 | 0.500 |
| LexML · paraphrase | 0.677 → 0.828 (+0.150) ✱ | +14 / −0 | < 0.001 |
| LexML · reference | 0.134 → 0.124 (−0.010) | +1 / −2 | 1.000 |

Quel premier niveau sous le re-ranking ? `rerank-dense-v1 → rerank-v1` :

| Jeu | Recall@5 | gagnées / perdues | p | MRR (IC 95 % de l'écart) |
|---|---|---|---|---|
| PIAF | 0.952 → 0.966 (+0.014) | +11 / −4 | 0.118 | 0.886 → 0.900 (+0.014) ✱ [+0.003 ; +0.027] |
| LexML | 0.545 → 0.596 (+0.051) ✱ | +17 / −3 | 0.003 | 0.498 → 0.539 (+0.040) ✱ [+0.015 ; +0.069] |
| LexML · paraphrase | 0.699 → 0.796 (+0.097) ✱ | +11 / −2 | 0.022 | 0.617 → 0.716 (+0.099) ✱ [+0.025 ; +0.176] |

### Latence (p50 / p95, génération exclue)

| | baseline-v1 | hybrid-v1 | rerank-dense-v1 | rerank-v1 |
|---|---|---|---|---|
| PIAF, requête complète | 23 / 28 ms | 43 / 61 ms | 409 / 454 ms | 461 / 588 ms |
| PIAF, dont re-ranking | — | — | 384 / 427 ms | 423 / 544 ms |
| LexML, requête complète | 41 / 68 ms | 88 / 126 ms | 619 / 841 ms | 695 / 948 ms |
| LexML, dont re-ranking | — | — | 584 / 805 ms | 612 / 844 ms |
| Génération p50, PIAF / LexML (rappel) | 1.8 s / 4.6 s | 1.9 s / 4.4 s | — | 2.2 s / 4.3 s |

La requête complète est embedding + recherche + re-ranking. Le re-ranking coûte plus cher sur LexML : les textes de loi en portugais donnent plus de tokens par chunk que PIAF, et plus de paires atteignent la troncature.

### Mémoire GPU et cache

| | Mesuré (nvidia-smi toutes les 500 ms, écran compris, ~0,8 Go au repos) |
|---|---|
| retrieval + génération, qwen2.5:7b + cross-encoder | pic 7 624 Mio sur 8 192 (LexML), 7 547 Mio (PIAF) |
| cross-encoder seul (`rerank-dense-v1`, pas de génération) | pic 2 614 Mio, soit ~1,8 Go pour le modèle, ses activations et le contexte CUDA |
| passe du juge (Gemma seul, après `release()`) | pic 7 679 Mio |
| fin des deux runs | 807 Mio : le modèle est bien libéré |

Le cross-encoder tient à côté de qwen2.5:7b, avec ~550 Mio de marge seulement. Taux de hit du cache des scores : 0.000 sur PIAF, 0.004 sur LexML (quelques questions en double). C'est attendu sur un premier passage, et c'est ce qui rend la latence mesurée honnête ; le cache ne sert qu'aux questions répétées (UI, démos, re-runs).

### Ce que disent les chiffres

1. **Le re-ranking est le plus gros gain de la phase 9 à ce jour, et il est significatif partout sauf sur `reference`.** Le MRR progresse de +0.12 (PIAF) et +0.14 (LexML) par rapport à l'hybride, avec des intervalles de confiance loin de 0, et le Recall@5 de +0.066 et +0.098. Quasiment aucune question perdue : 0 sur PIAF, 2 sur LexML. Le Recall@1 de PIAF passe de 0.688 à 0.846 : la bonne réponse est en tête bien plus souvent.
2. **Les paraphrases en profitent le plus** (LexML Recall@5 0.602 → 0.796, MRR +0.27). C'est le cas d'usage du cross-encoder : il lit la question et le passage ensemble, là où l'embedding et BM25 les comparent de loin.
3. **Les questions `reference` ne bougent toujours pas** (0.093). Le cross-encoder ne peut pas remonter un article qui n'est pas dans les 40 candidats, et le passage « Art. 2º » ne dit pas de quelle loi il fait partie. Le problème reste celui décrit pour 9.2 ; il relève de la compréhension de requête (9.4).
4. **L'hybride reste le meilleur générateur de candidats.** Sous le re-ranking, il bat le dense de façon significative sur LexML (Recall@5 +0.051, MRR +0.040) et au MRR sur PIAF (+0.014). Le gain au top-10 mesuré en 9.2 se transforme ici en gain au top-5.
5. **Juges RAGAS : correctness et relevancy en hausse, faithfulness en baisse sur LexML.** Correctness +0.050 (PIAF) et +0.097 (LexML) par rapport à l'hybride, relevancy +0.050 et +0.040. Faithfulness −0.010 (PIAF) et −0.035 (LexML), −0.050 contre la baseline sur LexML. Ces écarts portent sur 100 réponses sans intervalle de confiance. Une hypothèse, non vérifiée : avec de meilleurs passages, le modèle répond plus souvent et prend plus de risques. À surveiller.
6. **La latence dépasse le budget.** +420 ms (PIAF) et +610 ms (LexML) au p50, contre 200 ms visés. Rapporté à la réponse complète (génération 2 à 4 s au p50), c'est +15 à 20 %.

**Recommandation.** Le gain justifie la brique : la proposer comme configuration recommandée (`RAGLAB_DEFAULT_RETRIEVAL_MODE=hybrid`, `RAGLAB_DEFAULT_RERANK=true`) pour un usage où la qualité prime sur la latence de recherche. Cette PR laisse `RAGLAB_DEFAULT_RERANK=false` : basculer le défaut revient au propriétaire. Avant de le faire, deux réglages non mesurés pourraient ramener la latence près du budget : 20 candidats au lieu de 40 (le Recall@10 de l'hybride, 0.94 / 0.56, laisse penser que l'essentiel est dans le top-20) et `RAGLAB_RERANK_MAX_LENGTH=256`.
