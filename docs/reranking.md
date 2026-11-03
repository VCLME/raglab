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

Ordres de grandeur attendus pour 40 candidats d'environ 900 caractères (~250 tokens avec la question), à confirmer par la mesure :

| Configuration | Estimation | Commentaire |
|---|---|---|
| GPU 8 Go, fp16, cache froid | ~100 à 200 ms | ~10 000 tokens en 3 lots de 16 |
| GPU, cache chaud | < 5 ms | lecture du LRU |
| CPU, fp32 | plusieurs secondes | inutilisable en interactif ; utile pour les tests seulement |
| premier appel du processus | + quelques secondes | chargement des poids (~2,2 Go sur disque) |

Le budget visé : le re-ranking ne doit pas ajouter plus de 200 ms au p50 de la requête sur GPU. C'est peu à côté de la génération (plusieurs secondes), mais c'est plus que la recherche elle-même (quelques dizaines de ms). La brique ne sera activée par défaut que si le gain de Recall@5 et de MRR sur PIAF et LexML justifie ce surcoût. Les réglages qui pèsent sur la latence : `RAGLAB_RERANK_CANDIDATES` (linéaire), `RAGLAB_RERANK_MAX_LENGTH` (au plus linéaire) et `RAGLAB_RERANK_BATCH_SIZE` (moins de lots, plus de VRAM).

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

À faire après la baseline 9.1b, sur les jeux figés (voir [benchmarks/protocole.md](benchmarks/protocole.md)) : Recall@5/10 et MRR avec et sans re-ranking, pour les modes dense et hybride, par type de question ; latence ajoutée p50/p95 ; pic de VRAM à côté de qwen2.5.
