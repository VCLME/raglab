# Architecture du projet RAG local

## 1. Objectif

Construire un RAG local orienté expérimentation sur un dossier de documents `.txt`, `.pdf`, `.docx`, avec :

- stockage vectoriel dans PostgreSQL + pgvector
- génération locale via Ollama
- séparation claire entre ingestion, chunking, embeddings, indexation, retrieval, génération et expérimentation
- possibilité de comparer plusieurs stratégies de chunking sans réécrire le pipeline
- architecture prête à accueillir plus tard un graphe Neo4j en complément du stockage vectoriel

## 2. Principes de conception

### Modulaire

Chaque couche a une responsabilité explicite :

- `ingestion` : lecture et normalisation des documents
- `chunking` : production de chunks selon une stratégie
- `embeddings` : vectorisation des chunks et des requêtes
- `db` / `stores.vector` : persistance et recherche vectorielle
- `generation` : synthèse finale avec Ollama
- `experiments` : exécution comparative et reporting
- `api` : couche HTTP FastAPI réutilisant les services ci-dessus (`src/raglab/api/`), consommée par le frontend `frontend/` (React + Vite). Voir [frontend-ui.md](frontend-ui.md).

### Orientée expérimentation

Le pipeline stocke explicitement :

- le corpus
- les documents ingérés
- les runs d’indexation
- la stratégie de chunking utilisée
- la configuration exacte d’un run
- le modèle d’embeddings utilisé
- les résultats d’expérimentation

L’idée n’est pas seulement de “faire un RAG”, mais de pouvoir dire plus tard :

- quelle stratégie de chunking marche le mieux sur ce corpus
- avec quel coût
- avec quel rappel
- avec quel niveau de qualité de réponse

### Pragmatique pour le MVP

Le MVP optimise la lisibilité, la reproductibilité et la capacité d’évolution, pas la sophistication maximale dès le jour 1.

Conséquences :

- pipeline synchrone
- ORM SQLAlchemy pour la majorité du modèle
- CLI Typer comme point d’entrée principal
- une seule voie de génération par défaut
- un modèle d’embeddings de référence pour le MVP
- une interface prête pour plusieurs providers d’embeddings ensuite

## 3. Vue d’ensemble

```text
Documents (.txt/.pdf/.docx)
        |
        v
  Ingestion / Extraction
        |
        v
   DocumentRepository
        |
        v
   ChunkingStrategy
        |
        v
  EmbeddingProvider
        |
        v
PostgreSQL + pgvector
        |
        v
 Vector Retrieval
        |
        v
 Prompt Builder
        |
        v
   Ollama Generator
        |
        v
      Réponse

         +------------------------------+
         | Experiment Runner            |
         | compare index runs / metrics |
         +------------------------------+
```

## 4. Flux principaux

### 4.1 Ingestion

1. Le CLI scanne un dossier.
2. Chaque fichier compatible est lu par un reader dédié.
3. Le texte est normalisé.
4. Le document est stocké en base avec son checksum.

### 4.2 Indexation

1. L’utilisateur choisit un corpus et une stratégie de chunking.
2. Un `index_run` est créé.
3. Les documents du corpus sont chunkés.
4. Chaque chunk est vectorisé.
5. Les chunks et embeddings sont persistés.

### 4.3 Requête

1. La question est vectorisée avec le même espace d’embeddings que l’index.
2. Le top-k de chunks les plus proches est récupéré via pgvector.
3. Le contexte est construit.
4. Ollama produit la réponse finale.

### 4.4 Expérimentation

1. Un dataset de questions est chargé.
2. Le runner exécute les mêmes requêtes sur plusieurs `index_runs`.
3. Les résultats sont comparés.
4. Un rapport JSON est sauvegardé.

## 5. Stratégies de chunking prévues

### Traditional chunking

Chunks contigus de taille cible avec léger recouvrement.

Cas d’usage :

- baseline simple
- implémentation robuste
- bonne lisibilité opérationnelle

### Slide chunking

Fenêtres glissantes avec stride inférieur à la taille de fenêtre.

Cas d’usage :

- réduire le risque de couper une information importante entre deux chunks
- améliorer le rappel au prix d’un stockage plus élevé

### Late chunking

Version MVP : chunks focaux stockés comme unités de récupération, mais embeddings calculés avec un contexte plus large autour du chunk.

Cela permet de conserver :

- un chunk final court et lisible
- une représentation sémantique plus contextualisée

Note d’architecture :

La vraie variante “late chunking” au sens strict peut nécessiter un accès bas niveau aux embeddings token-level sur un contexte long. L’architecture proposée prépare cette évolution, mais le MVP implémente une version pragmatique : contextualisation locale autour du chunk focal.

## 6. Préparation à PostgreSQL vectoriel + Neo4j

Le projet sépare déjà deux responsabilités :

- recherche dense vectorielle
- navigation / raisonnement relationnel

Le design prévoit les interfaces suivantes :

- `VectorStore`
- `GraphStore`

Dans le MVP :

- `VectorStore` est implémenté avec PostgreSQL + pgvector
- `GraphStore` est un placeholder

Dans l’itération suivante :

- extraction d’entités / relations depuis les documents
- projection de ces entités dans Neo4j
- requêtes hybrides :
  - récupération vectorielle initiale
  - expansion graphe
  - fusion de contexte

## 7. Découpage des modules

### `src/raglab/config.py`

Chargement centralisé de la configuration avec Pydantic Settings.

### `src/raglab/ingestion`

Lecture des fichiers, normalisation, calcul de checksum, service d’ingestion.

### `src/raglab/chunking`

Stratégies interchangeables avec factory et interface commune.

### `src/raglab/embeddings`

Interface de vectorisation et provider de référence basé sur Transformers.

### `src/raglab/db`

Session SQLAlchemy, modèles ORM, initialisation de la base.

### `src/raglab/stores/vector`

Couche de retrieval pgvector.

### `src/raglab/generation`

Client Ollama et construction du prompt de réponse.

### `src/raglab/experiments`

Lecture de datasets, exécution comparative, calcul de métriques simples, sauvegarde de rapports.

### `src/raglab/graph`

Plomberie Neo4j en place. Le service `neo4j` (image `neo4j:5.20-community`) est défini dans `docker-compose.yml`. Le driver Python `neo4j>=5.20` est listé en dépendance.

Le Protocol `GraphStore` est aligné sur `VectorStore` (méthodes `upsert_chunks`, `search`, `expand_neighbors`, `delete_index_run`, plus `ping` pour le healthcheck). `Neo4jGraphStore` implémente `ping()` ; les autres méthodes lèvent `NotImplementedError` tant que le PR vector-in-graph n'a pas atterri.

Les endpoints `/api/graph/index`, `/api/graph/query`, `/api/graph/runs` répondent `501` pour matérialiser la surface dans Swagger.

## 8. Décisions structurantes

- Le chunking est versionné par `index_run`, pas par document seul.
- Les embeddings sont rattachés à un `embedding_space`.
- La requête travaille contre un `index_run` explicite ou résolu automatiquement.
- La génération n’est pas couplée au moteur vectoriel.
- Le projet reste exécutable en CLI locale sans UI au départ.

## 9. Ce que cette architecture rend facile ensuite

- tester plusieurs modèles d’embeddings
- ajouter du reranking
- ajouter du hybrid search lexical + dense
- brancher Neo4j
- ajouter un service API FastAPI sans changer le coeur métier
- exécuter des benchmarks reproductibles sur plusieurs corpus
