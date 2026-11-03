# Documentation de raglab

Par où commencer selon ce que vous voulez faire. Le [README du dépôt](../README.md) donne la présentation et les résultats mesurés ; le [rapport technique](rapport/raglab-rapport.tex) (LaTeX, PDF à construire, voir [rapport/README.md](rapport/README.md)) rassemble le tout en un document.

## Comprendre le projet

| Document | Pour savoir |
|---|---|
| [base-idea.md](base-idea.md) | pourquoi raglab existe, ce qu'on compare |
| [architecture.md](architecture.md) | les composants, le chemin d'une requête, la chaîne de mesure (diagrammes) |
| [technical-choices.md](technical-choices.md) | pourquoi pgvector, Ollama, e5-small, Typer… |
| [data-model.md](data-model.md) | le schéma PostgreSQL (corpus, documents, index runs, espaces d'embedding) |
| [roadmap.md](roadmap.md) | ce qui est livré, phase par phase, et ce qui vient |

## Le faire tourner

| Document | Pour savoir |
|---|---|
| [run-and-test.md](run-and-test.md) | installer, lancer en Docker ou en local, exécuter les tests |
| [frontend-ui.md](frontend-ui.md) | les pages de l'interface (Chat, mode Expert) |
| [real-rag-lexml-load.md](real-rag-lexml-load.md) | charger le corpus LexML historique (fiches) en une commande |

## Le mesurer

| Document | Pour savoir |
|---|---|
| [benchmarks/protocole.md](benchmarks/protocole.md) | comment raglab mesure : jeux figés, corpus complet, pertinence au niveau du passage, questions LexML typées |
| [benchmarks/juges.md](benchmarks/juges.md) | les juges RAGAS (Gemma 4 via llama.cpp), la notation en deux passes, la calibration |
| [benchmarks/baseline.md](benchmarks/baseline.md) | la configuration de référence et ses chiffres |
| [../benchmarks/README.md](../benchmarks/README.md) | le contenu des jeux figés versionnés |
| [experimentation-plan.md](experimentation-plan.md) | le plan d'expérimentation d'origine (comparaison des chunkings) |
| [portes-qualite.md](portes-qualite.md) | `raglab gate`, les seuils versionnés, la porte hebdomadaire en CI |

## L'étendre

| Document | Pour savoir |
|---|---|
| [architecture.md](architecture.md) §2 et §11 | où placer une nouvelle brique et les règles à respecter |
| [roadmap.md](roadmap.md), phase 9 | la règle : une brique = une PR avec tableau avant / après, derrière un drapeau tant qu'elle n'apporte rien |
| [../CLAUDE.md](../CLAUDE.md) | les règles de la maison (langues, PR, budget GPU, conventions d'API) |

## L'exploiter

| Document | Pour savoir |
|---|---|
| [exploitation.md](exploitation.md) | démarrer / arrêter, budget GPU, réglages llama.cpp, sauvegardes, dépannage des erreurs Ollama |
| [api-production.md](api-production.md) | streaming SSE, budgets par étape, `X-Request-ID`, clé d'API, rate limit, `/health` et `/ready` |
| [portes-qualite.md](portes-qualite.md) | vérifier qu'un changement ne dégrade pas la qualité |
