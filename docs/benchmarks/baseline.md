# Baseline (phase 9.1)

La configuration de référence de raglab, mesurée sur les jeux figés de [`benchmarks/`](../../benchmarks/). Toutes les briques suivantes (hybride, re-ranking, routeur…) se comparent à ces chiffres.

## Configuration mesurée

| Élément | Valeur |
|---|---|
| Chunking | `traditional`, 900 caractères, chevauchement 150 |
| Embedding | `intfloat/multilingual-e5-small` (384 dimensions), transformers sur CPU, préfixes `query: ` / `passage: ` |
| Recherche | pgvector, distance cosinus, index HNSW (m = 16, ef_construction = 64), top-k 5 (le benchmark récupère 10 pour Recall@10) |
| Génération | `qwen2.5:7b` (Q4) via Ollama sur GPU, température 0,1, prompt de grounding avec citations `[Rank N]` |
| Juges RAGAS | Gemma 4 26B-A4B via llama.cpp, notation en seconde passe (voir [juges.md](juges.md)) |
| Questions | PIAF : 500 (fr) ; LexML texte intégral : 277 (pt), voir [protocole.md](protocole.md) |
| RAGAS | les 100 premières questions de chaque jeu (par identifiant) |

## Commande

```bash
raglab bench all --label baseline-v1
raglab bench report baseline-v0 baseline-v0-cache baseline-v1
```

`raglab bench all` vérifie le corpus LexML contre son manifeste, ingère et indexe chaque corpus dans un corpus dédié (`bench_piaf_fr`, `bench_lexml_pt`), lance le benchmark, puis écrit `benchmarks/results/<label>.json` : chiffres, machine, versions, empreintes des modèles et commande exacte.

## Trois mesures, trois causes

| Run | Ce qui change | Ce qu'il isole |
|---|---|---|
| `baseline-v0` | rien : le code tel qu'avant la phase 9 (`RAGLAB_EMBEDDING_CACHE=false`, `RAGLAB_HNSW_ITERATIVE_SCAN=false`) | le point de départ |
| `baseline-v0-cache` | + le modèle d'embedding n'est chargé qu'une fois (retrieval seul) | le gain de latence du cache, à retrieval identique |
| `baseline-v1` | + recherche vectorielle exacte sur l'index run, réponses générées depuis le top 5, juge lisant les passages entiers | la **baseline officielle** |

Trois défauts ont été trouvés et corrigés en préparant la baseline :

- **Modèle d'embedding rechargé à chaque requête.** `build_embedding_provider` créait un nouveau provider à chaque question : les poids d'e5-small étaient relus depuis le disque, avec des appels réseau à Hugging Face pour vérifier les fichiers. Une requête RAG dépendait donc d'internet.
- **Recall dépendant du reste de la base.** L'index HNSW est partagé par tous les index runs de même dimension, et pgvector applique le filtre `index_run_id` *après* la recherche approximative. Premier symptôme : un top-k incomplet (40 candidats lus, puis filtrés) ; la recherche itérative de pgvector 0.8 l'a corrigé. Mais une fois un corpus indexé plusieurs fois, l'index contient des copies identiques des mêmes vecteurs et le graphe HNSW se dégrade : sur 150 questions PIAF, Recall@5 de **0,093** et **0,627** pour deux runs du même corpus, contre **0,913** pour les deux en recherche exacte. Correctif : recherche exacte sur les vecteurs de l'index run (`vector_search_mode = exact`, 11 à 25 ms au p50 à cette échelle), HNSW gardé en option pour les gros volumes ; et `raglab bench all` réutilise l'index run quand rien n'a changé, au lieu de dupliquer les vecteurs.
- **Protocole RAGAS faussé.** Le benchmark récupère 10 chunks pour Recall@10 et les passait tous au LLM, alors que la configuration de référence en envoie 5 ; et le juge de fidélité ne lisait que les 600 premiers caractères de chaque chunk. Corrigé avant la v1 : génération depuis le top 5, juge sur le même contexte, passages entiers. Les scores RAGAS de la v0 ne sont donc pas comparables à ceux de la v1.

## Résultats

Run officiel : `baseline-v1` ([`benchmarks/results/baseline-v1.json`](../../benchmarks/results/baseline-v1.json)). Intervalles à 95 % par bootstrap.

| Environnement | |
|---|---|
| Machine | Intel64 Family 6 Model 154 Stepping 3, GenuineIntel (20 threads), 32 GiB, NVIDIA GeForce RTX 3070 Ti Laptop GPU, 8192 MiB, 595.79 |

| Système | Windows-11-10.0.26300-SP0 |

| Versions | Python 3.12.10, torch 2.11.0, transformers 5.5.4, PostgreSQL 16.13 (Debian 16.13-1.pgdg12+1), pgvector 0.8.2 |

| Modèles | transformers:intfloat/multilingual-e5-small (cpu) ; ollama:qwen2.5:7b (845dbda0ea48) ; juge llamacpp:gemma4-26b-a4b |

| Commit | 3a0781d (2026-11-03T05:42:27+00:00) |

| Commande | `raglab bench all --label baseline-v1` |

### piaf (fr, 500 questions)



| Métrique | baseline-v0 | baseline-v0-cache | baseline-v1 |

|---|---|---|---|

| Recall@1 | 0.672 | 0.672 | 0.672 [0.63–0.71] |

| Recall@5 | 0.878 | 0.878 | 0.878 [0.85–0.91] |

| Recall@10 | 0.898 | 0.898 | 0.898 [0.87–0.92] |

| MRR | 0.758 | 0.758 | 0.758 [0.73–0.79] |

| Latence requête p50 (embed + recherche) | 3 687 ms | 19.7 ms | 23.5 ms |

| Latence requête p95 | 5 352 ms | 26.6 ms | 28.2 ms |

| dont embedding p50 | 3 681 ms | 11.5 ms | 12.6 ms |

| dont recherche pgvector p50 | 5.0 ms | 8.4 ms | 10.9 ms |

| Génération p50 | 3 250 ms | — | 1 815 ms |

| Génération p95 | 5 991 ms | — | 4 963 ms |

| Débit de génération p50 (tokens/s) | 49.0 | — | 65.1 |

| Faithfulness | 0.845 | — | 0.930 |

| Answer relevancy | 0.870 | — | 0.900 |

| Answer correctness | 0.600 | — | 0.658 |



Juges RAGAS calculés sur les 100 premières questions.



### lexml_fulltext (pt, 277 questions)



| Métrique | baseline-v0 | baseline-v0-cache | baseline-v1 |

|---|---|---|---|

| Recall@1 | 0.303 | 0.318 | 0.325 [0.27–0.38] |

| Recall@5 | 0.426 | 0.451 | 0.466 [0.41–0.53] |

| Recall@10 | 0.458 | 0.484 | 0.502 [0.44–0.56] |

| MRR | 0.350 | 0.368 | 0.379 [0.33–0.43] |

| Latence requête p50 (embed + recherche) | 3 972 ms | 40.2 ms | 40.5 ms |

| Latence requête p95 | 5 711 ms | 57.3 ms | 67.5 ms |

| dont embedding p50 | 3 964 ms | 12.0 ms | 15.8 ms |

| dont recherche pgvector p50 | 10.5 ms | 29.6 ms | 24.7 ms |

| Génération p50 | 3 392 ms | — | 4 637 ms |

| Génération p95 | 16 584 ms | — | 20 100 ms |

| Débit de génération p50 (tokens/s) | 59.1 | — | 31.7 |

| Faithfulness | 0.723 | — | 0.903 |

| Answer relevancy | 0.620 | — | 0.725 |

| Answer correctness | 0.298 | — | 0.451 |



Juges RAGAS calculés sur les 100 premières questions.



| Recall@5 / MRR par type | baseline-v0 | baseline-v0-cache | baseline-v1 |

|---|---|---|---|

| entity | 0.747 / 0.645 (87) | 0.770 / 0.668 (87) | 0.793 / 0.679 (87) |

| paraphrase | 0.505 / 0.395 (93) | 0.538 / 0.421 (93) | 0.548 / 0.432 (93) |

| reference | 0.062 / 0.043 (97) | 0.082 / 0.048 (97) | 0.093 / 0.058 (97) |

### `baseline-v0` → `baseline-v1` (comparaison appariée)



| Jeu | Questions | Recall@5 | Gagnées / perdues | p (McNemar) | MRR | IC 95 % de l'écart MRR |

|---|---|---|---|---|---|---|

| piaf | 500 | 0.878 → 0.878 (+0.000) | +0 / −0 | 1.000 | 0.758 → 0.758 (+0.000) | [+0.000 ; +0.000] |

| lexml_fulltext | 277 | 0.426 → 0.466 (+0.040) ✱ | +11 / −0 | 0.001 | 0.350 → 0.379 (+0.029) ✱ | [+0.010 ; +0.051] |

| lexml_fulltext · entity | 87 | 0.747 → 0.793 (+0.046) | +4 / −0 | 0.125 | 0.645 → 0.679 (+0.034) | [-0.001 ; +0.081] |

| lexml_fulltext · paraphrase | 93 | 0.505 → 0.548 (+0.043) | +4 / −0 | 0.125 | 0.395 → 0.432 (+0.038) ✱ | [+0.006 ; +0.079] |

| lexml_fulltext · reference | 97 | 0.062 → 0.093 (+0.031) | +3 / −0 | 0.250 | 0.043 → 0.059 (+0.015) | [-0.000 ; +0.041] |



✱ = écart significatif (p < 0,05 pour le recall, IC 95 % excluant 0 pour le MRR).

### Ce qu'il faut retenir

- **PIAF (français) est un jeu facile pour la recherche dense** : la bonne réponse est dans le top 5 pour 88 % des questions. Les questions PIAF ont été écrites par des annotateurs qui lisaient le paragraphe : elles reprennent ses mots.
- **LexML (portugais juridique) est difficile** : 47 % en Recall@5, et **9 % seulement pour les questions qui citent un article de loi**. Les embeddings saisissent le sens, pas les identifiants (« art. 49 » ≈ « art. 94 »). C'est le cas que la recherche hybride (9.2) doit corriger.
- **La latence de recherche** passe de 3,7-4,0 s (modèle d'embedding rechargé à chaque question) à **23-40 ms** au p50, embedding compris.
- **La génération** (qwen2.5:7b sur GPU) prend 1,8 s au p50 sur PIAF et 4,6 s sur LexML, avec un p95 à 20 s sur LexML : les réponses juridiques sont longues et la sortie n'est pas plafonnée.
- **Fidélité 0,93 / 0,90** (juge Gemma 4, calibré à 0,978 de bons verdicts) : les réponses restent ancrées dans les passages fournis. **Answer correctness 0,66 / 0,45** : quand le bon passage n'est pas récupéré, la réponse ne peut pas être juste, même fidèle.
- Runs écartés, gardés pour la transparence : `baseline-v1-hnsw-broken` (index HNSW dégradé par les copies) et `baseline-v1-exact-unoptimized` (mêmes résultats, latence avant optimisation de la requête exacte).
