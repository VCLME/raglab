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
| `baseline-v1` | + pgvector cherche jusqu'à remplir le top-k malgré le filtre sur l'index run | le gain de recall du correctif ; c'est la **baseline officielle** |

Les deux défauts corrigés ont été trouvés en préparant la baseline :

- **Modèle d'embedding rechargé à chaque requête.** `build_embedding_provider` créait un nouveau provider à chaque question : les poids d'e5-small étaient relus depuis le disque, avec des appels réseau à Hugging Face pour vérifier les fichiers. Une requête RAG dépendait donc d'internet.
- **Top-k incomplet avec plusieurs index runs.** L'index HNSW est partagé par tous les runs de même dimension, et pgvector applique le filtre `index_run_id` *après* avoir lu 40 candidats (`hnsw.ef_search`). Avec plusieurs corpus dans la base, une question pouvait récupérer moins de 5 chunks, voire aucun. Correctif : recherche itérative de pgvector 0.8 (`hnsw.iterative_scan = strict_order`).

## Résultats

*(rempli par `raglab bench report` à la fin des mesures)*
