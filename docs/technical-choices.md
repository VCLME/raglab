# Choix techniques

## 1. Stack retenue

### Langage et outillage

- Python 3.12
- Typer pour la CLI
- Pydantic Settings pour la configuration
- pytest pour les tests

### Données

- PostgreSQL 16
- pgvector ≥ 0.7 pour la similarité vectorielle, avec colonne `vector` non dimensionnée et index HNSW **partiels par dimension** (voir [data-model.md](data-model.md))
- SQLAlchemy 2.x pour le modèle relationnel et la persistance

### Web

- API HTTP FastAPI dans `src/raglab/api/` qui réutilise directement les services Python (pas de sous-processus CLI)
- frontend React + TypeScript + Vite, i18n fr/en/pt-BR, servi par nginx en production, voir [frontend-ui.md](frontend-ui.md)

### LLM

- rédacteur des réponses : Qwen3.6-35B-A3B (MoE) servi par llama.cpp, démarré à la demande par l'API ([§ 3 bis](#3-bis-pourquoi-qwen36-via-llamacpp-pour-rédiger-les-réponses))
- repli et Docker : Ollama avec `qwen2.5:7b`, le générateur du MVP

### Embeddings

- modèle de référence recommandé pour le MVP : `intfloat/multilingual-e5-small`

### Parsing documentaire

- `pypdf` pour les PDF texte
- `python-docx` pour les `.docx`
- lecteur natif Python pour les `.txt`

## 2. Pourquoi PostgreSQL + pgvector

Avantages pour ce projet :

- stack simple et robuste
- stockage du relationnel et du vectoriel au même endroit
- traçabilité des runs d’indexation
- facilité pour les jointures entre documents, chunks, embeddings et expériences
- bon compromis avant de complexifier l’architecture

Ce choix est particulièrement cohérent ici car le projet n’est pas seulement un moteur de recherche sémantique ; c’est aussi un banc d’essai expérimental.

## 3. Pourquoi Ollama pour la génération

Ollama apporte :

- déploiement local simple
- API standardisée
- bon confort de test
- possibilité de changer rapidement de modèle

### Modèle recommandé : `qwen2.5:7b`

Raisons :

- meilleure robustesse instructionnelle pour un usage RAG
- bon comportement multilingue pour un corpus juridique local
- compromis qualité / coût adapté à une machine locale correctement dimensionnée
- intégration simple avec Ollama et bonne cohérence avec un workflow 100 % local

Alternatives plus tard :

- `llama3.2:3b` si la machine cible est plus contrainte
- modèles plus gros si la machine cible le permet : c'est ce qu'a fait le § 3 bis

## 3 bis. Pourquoi Qwen3.6 via llama.cpp pour rédiger les réponses

`qwen2.5:7b` a été le générateur de tous les runs jusqu'à `prompt-v4`. Le run `gen-qwen36-v1` a remplacé le seul générateur : mêmes questions, mêmes passages (hybride + re-ranking + références), même prompt, même juge (Gemma 4 26B-A4B, d'une autre famille que les deux générateurs), 100 réponses notées par jeu.

| Métrique RAGAS | PIAF `prompt-v4` → `gen-qwen36-v1` | LexML `prompt-v4` → `gen-qwen36-v1` |
|---|---|---|
| answer correctness | 0,763 → **0,935** | 0,550 → **0,710** |
| faithfulness | 0,970 → **0,995** | 0,895 → **0,980** |
| answer relevancy | 0,890 → **0,975** | 0,875 → **0,965** |

Le gain le plus net est sur LexML (portugais juridique, articles longs) : +16 points de correctness, et la fidélité au contexte passe de 0,895 à 0,980, ce qui compte pour un outil qui doit citer la loi sans l'inventer.

Pourquoi ce modèle tient sur 8 Go : c'est un MoE de 35 milliards de paramètres dont environ 3 milliards servent à chaque token. Les couches d'attention et les poids partagés restent sur le GPU, les experts de 32 couches restent en RAM (`--n-cpu-moe 32`). La génération reste rapide (~26 tok/s) malgré 17 Go de poids.

Pourquoi llama.cpp et pas Ollama : le déchargement des experts en RAM (`--n-cpu-moe`), le cache KV en `q8_0` et la taille de lot se règlent par profil dans llama-server ; c'est ce réglage qui fait tenir le modèle. Le serveur était déjà là pour le juge et le générateur de questions (`LocalLLMServer`).

Ce que ça coûte :

- **latence** : génération p50 de 7 à 9 s, contre 2,2 s (PIAF) et 4,3 s (LexML) pour `qwen2.5:7b` ([reranking.md](reranking.md)) ; le streaming affiche les premiers mots bien avant ;
- **chargement** : le premier appel démarre llama-server (quelques dizaines de secondes) ; le serveur reste ensuite chargé ;
- **mémoire** : environ 16 Go de RAM pour les experts, et un budget VRAM serré à côté du cross-encoder. Mesuré avec 10 questions : à 64k de contexte, l'ensemble déborde de la VRAM et la génération tombe à 2,9 tok/s ; le rédacteur tourne donc avec son propre profil, 16k de contexte et 34 couches d'experts en RAM (5,41 Go seul, 7,10 Go au pic avec le re-ranking, 33,6 tok/s, génération p50 7,2 s) ([run-and-test.md](run-and-test.md#rédacteur-qwen36-sur-llamacpp)).

Le repli reste Ollama `qwen2.5:7b` : si llama.cpp ne répond pas et ne peut pas être démarré, s'il charge encore ou s'il sert un autre modèle (le juge d'un benchmark), la requête part sur Ollama et la réponse le dit (`generator_notice`). Une requête n'échoue jamais parce que llama.cpp est arrêté. Docker garde Ollama par défaut ; l'override `docker-compose.llamacpp.yml` ajoute le rédacteur dans son propre conteneur ([run-and-test.md](run-and-test.md#rédacteur-qwen36-sur-llamacpp)).

## 4. Réflexion pragmatique sur les embeddings

### Recommandation de baseline : `intfloat/multilingual-e5-small`

Raisons pragmatiques :

- multilingue
- léger pour un usage local
- dimension de sortie raisonnable : 384
- très bon candidat de baseline pour un corpus mixte français / anglais
- surtout : il se prête bien à une implémentation locale contrôlée via `transformers`, utile pour expérimenter du late chunking contextualisé

`RAGLAB_EMBEDDING_DIMENSION` **n'est plus une contrainte** au niveau de la colonne `chunk_embeddings.embedding` — c'est seulement une valeur par défaut utilisée au moment de créer un nouvel `embedding_space` (et encore, le moteur d'indexation sonde le modèle à chaque run pour écrire la vraie dimension produite, voir `IndexingService.index_corpus`). Plusieurs dimensions (384, 768, 1024, …) coexistent désormais dans la même instance.

### Pourquoi ne pas choisir Ollama pour le modèle d’embeddings du MVP

Ollama propose aujourd’hui des modèles d’embeddings intéressants comme `embeddinggemma` et `all-minilm`.

Mais pour ce projet précis, le MVP doit aussi préparer :

- plusieurs stratégies de chunking
- une variante de late chunking contextualisé
- une interface expérimentale flexible

Le choix d’un provider local basé sur `transformers` offre plus de contrôle sur :

- la tokenisation
- le pooling
- la contextualisation
- l’évolution future vers du token-level pooling plus fidèle

### Position de conception

Le MVP part donc sur :

- génération : Ollama
- embeddings : provider Python local de référence

L’architecture garde néanmoins une interface `EmbeddingProvider` pour ajouter ensuite :

- un provider Ollama embeddings
- un provider SentenceTransformers
- un provider OpenAI ou autre si un mode distant est souhaité plus tard

## 5. Pourquoi SQLAlchemy

SQLAlchemy est pertinent ici car on manipule des objets métier stables :

- corpus
- documents
- runs d’indexation
- chunks
- expériences

Cela améliore :

- la lisibilité du modèle de données
- la maintenabilité
- la capacité à migrer vers Alembic ensuite

## 6. Pourquoi Typer

Typer est adapté à un projet orienté opérations locales :

- commandes claires
- autocomplétion
- typage simple
- bonne ergonomie pour un workflow `ingest -> index -> query -> experiment`

## 7. Pourquoi une architecture orientée expérimentation

Sans cette séparation, les comparaisons deviennent vite floues :

- quel chunking a été utilisé ?
- avec quel recouvrement ?
- avec quel modèle d’embeddings ?
- sur quel corpus exact ?

Le projet stocke donc explicitement le contexte expérimental, même pour le MVP.

## 8. Limites assumées

- pas d'OCR PDF image dans cette version
- pas de reranker cross-encoder dans cette version
- pas de pipeline asynchrone distribué
- authentification minimale : une clé d'API partagée optionnelle (`RAGLAB_API_KEY`), pas de comptes utilisateurs
- les opérations longues (ingestion, indexation, `lexml load`, `bench download`) sont synchrones côté API — pas de file de jobs

Ces limites sont volontaires pour conserver un socle simple, testable et extensible.
