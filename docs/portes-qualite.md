# Portes de qualité (phase 9.7)

Une porte de qualité est une commande qui **échoue** quand la qualité du RAG baisse sous un seuil fixé à l'avance. Elle protège contre les régressions silencieuses : un changement de prompt, de modèle, de chunking ou de dépendance qui dégrade les résultats sans casser aucun test unitaire.

## Ce qui est vérifié

`benchmarks/thresholds.json` (versionné) fixe, pour chaque jeu figé, le plancher de chaque métrique :

| Métrique | Pourquoi |
|---|---|
| `recall@5` | le bon passage est-il dans les 5 chunks envoyés au LLM ? |
| `mrr` | arrive-t-il en tête ? |
| `faithfulness_mean` | la réponse reste-t-elle ancrée dans les documents (juge Gemma 4) ? |

Les planchers sont ceux de la baseline officielle (`baseline-v1`), moins une tolérance qui absorbe le bruit de mesure. On les relève quand une brique améliore durablement les chiffres, jamais on ne les baisse pour faire passer une régression.

## Commandes

```bash
# vérifier un run déjà mesuré
raglab gate --results benchmarks/results/baseline-v1.json

# tout mesurer puis vérifier (Ollama + juge llama.cpp, ~1 h)
raglab gate --run

# retrieval seul, sans GPU (ce que fait la CI)
raglab gate --run --ragas-limit 0
```

Code de sortie 1 si une métrique mesurée passe sous son plancher. Une métrique non mesurée (faithfulness dans un run sans génération) est affichée « non mesurée », sans faire échouer la porte ; `--require-all` la rend obligatoire.

## Automatisation

Le workflow GitHub Actions `Quality gate` (`.github/workflows/quality-gate.yml`) tourne chaque lundi et à la demande. Les runners GitHub n'ont pas de GPU : il mesure le **retrieval** (Recall@5, MRR) sur CPU, avec une base pgvector de service, et publie le tableau dans le résumé du job, avec les résultats JSON en artefact. Les corpus sont gardés en cache entre deux runs (la collecte LexML prend environ une heure). Si Planalto a modifié un texte, la vérification du manifeste fait échouer le run avec un message explicite plutôt que de mesurer sur un corpus différent.

La **faithfulness** demande Ollama et le juge llama.cpp : elle se vérifie en local avec `raglab gate --run`, avant de fusionner une PR qui touche à la génération ou au retrieval.
