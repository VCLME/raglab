# Idée de base

## Pourquoi raglab existe

raglab est un **laboratoire local** pour comparer, mesurer et comprendre les briques d'un pipeline RAG (Retrieval-Augmented Generation) sur ses propres documents.

Le problème de départ : quand on veut monter un RAG sérieux, chaque paramètre impacte la qualité — stratégie de chunking, modèle d'embedding, dimension, modèle de génération, prompt, top-k, métrique de distance, filtres de retrieval — et il est trop facile de bricoler sans jamais **mesurer** si les choix faits sont meilleurs que le défaut.

raglab n'est pas un framework pour mettre un RAG en production. C'est une **plateforme d'expérimentation** qui trace tout ce qu'elle fait et permet de poser la question « est-ce que X est mieux que Y sur mon corpus ? » avec des chiffres en sortie.

## Axes de comparaison visés

| Axe | Exemples | Statut |
| --- | --- | --- |
| Stratégie de chunking | `traditional`, `slide`, `late` | ✅ implémenté, comparable via `raglab experiment run` |
| Modèle d'embedding | `intfloat/multilingual-e5-small`, `e5-base`, `bge-m3`, … | ✅ pluggable via `embedding_space` |
| Dimension d'embedding | 384, 768, 1024, … | ✅ coexistence dans la même DB via `vector` variable + HNSW partiels par dim |
| Provider d'embedding | `transformers` (local), `ollama` | ✅ factory |
| Modèle de génération | tout modèle Ollama (`qwen2.5:7b`, `llama3.2:3b`, …) | ✅ sélectionnable côté chat et API |
| Top-k et filtres de retrieval | `top_k`, filtres par document/file_name/tags/metadata | ✅ exposés en CLI et API |
| Qualité du retrieval | Recall@K, Precision@K, MRR, mean_first_relevant_rank | ✅ partiel (pipeline existant, dataset à muscler) |
| Qualité de la génération | fidélité, hallucination, correctness | 🚧 prochaine itération |

## Ce que raglab **n'est pas**

- **Pas** un concurrent de LangChain/LlamaIndex. Pas d'orchestration complexe, pas de prod-ready.
- **Pas** une API SaaS. Tout tourne en local, sur la machine de l'utilisateur.
- **Pas** un moteur de recherche généraliste. La base vectorielle (PostgreSQL + pgvector) est dimensionnée pour des corpus d'expérimentation (quelques dizaines à quelques milliers de documents).
- **Pas** une démo LLM. Le modèle de génération compte, mais la vraie star ici c'est le banc de comparaison.

## Principes d'ingénierie

1. **Modularité stricte** : chaque étape est une couche (`ingestion`, `chunking`, `embeddings`, `indexing`, `retrieval`, `generation`) avec son interface et ses tests. Changer une couche ne casse pas les autres.
2. **Traçabilité complète** : chaque run d'indexation est un `index_run` daté, lié à une stratégie, un modèle, une dimension. Chaque requête est logguée avec les chunks récupérés, le temps d'exécution, l'index_run utilisé.
3. **Réexploitation** : la CLI et l'API web s'appuient sur **les mêmes services** — ce qu'on teste dans `pytest` est exactement ce que l'UI consomme.
4. **Local d'abord** : PostgreSQL + Ollama, pas d'appel cloud, pas de clé API.
5. **Observabilité** : logs structurés, métriques sur le pipeline. Pas de boîte noire.

## Flux type d'une expérimentation

```
1. raglab bench download fquad            # récupère un dataset Q/R ground-truthé
2. raglab ingest data/benchmarks/fquad/corpus --corpus fquad_fr
3. raglab index --corpus fquad_fr --strategy traditional
   raglab index --corpus fquad_fr --strategy slide
   raglab index --corpus fquad_fr --strategy late
4. raglab experiment recall --corpus fquad_fr --strategy <each>
5. raglab experiment run --corpus fquad_fr --strategy traditional --strategy slide --strategy late
6. Ouverture de la page « Benchmarks » du front (à venir)
   pour visualiser recall@K, MRR, latence, faithfulness côte à côte
```

## Critères pour ajouter un nouveau dataset de benchmark

Un dataset doit apporter au moins une des trois propriétés suivantes :

- **Vérité terrain humaine** : les paires Q/R ont été validées par des humains (pas du template)
- **Plusieurs documents pertinents par question** : permet de mesurer vraiment la recall
- **Ground truth de réponse** : permet la mesure de fidélité et de correctness

Les datasets auto-générés à partir de métadonnées (comme `lexml_recall_cases.jsonl` produit depuis LexML) restent utiles comme **smoke tests**, pas comme benchmarks rigoureux.

## Ressources clés

- [Architecture](architecture.md) : vue détaillée des couches
- [Modèle de données](data-model.md) : schéma Postgres + logique multi-dimensions
- [Plan d'expérimentation](experimentation-plan.md) : méthodologie de comparaison
- [Lancer et tester](run-and-test.md) : recettes concrètes
- [Interface web](frontend-ui.md) : modes Chat et Expert, i18n, Manage
- [Roadmap](roadmap.md) : où on en est, où on va
