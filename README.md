# raglab

Projet RAG local orienté expérimentation sur des dossiers de documents `.txt`, `.pdf`, `.docx`.

Le projet fournit :

- PostgreSQL + pgvector pour le stockage vectoriel
- Ollama pour la génération locale
- une CLI pour ingérer, indexer, requêter et lancer des expériences
- trois stratégies de chunking comparables :
  - `traditional`
  - `slide`
  - `late`
- une architecture prête pour une future coexistence PostgreSQL vectoriel + Neo4j

## Documents de cadrage

- [Architecture](docs/architecture.md)
- [Choix techniques](docs/technical-choices.md)
- [Plan d'expérimentation](docs/experimentation-plan.md)
- [Roadmap](docs/roadmap.md)
- [Modèle de données](docs/data-model.md)
- [Lancer et tester le projet](docs/run-and-test.md)

## Structure

```text
.
├── docs/
├── data/
│   ├── documents/
│   ├── experiments/
│   └── reports/
├── src/raglab/
│   ├── chunking/
│   ├── db/
│   ├── embeddings/
│   ├── experiments/
│   ├── generation/
│   ├── graph/
│   ├── indexing/
│   ├── ingestion/
│   ├── retrieval/
│   └── stores/
├── tests/
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Démarrage rapide

### 1. Lancer les services

```bash
docker compose up -d postgres ollama
```

### 2. Télécharger le modèle de génération Ollama

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

### 3. Installer le projet côté Python

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

### 4. Préparer la configuration

```bash
copy .env.example .env
```

### 5. Initialiser la base

```bash
raglab db init
```

### 6. Ingestion

```bash
raglab ingest data/documents --corpus demo
```

### 7. Indexation

```bash
raglab index --corpus demo --strategy traditional
raglab index --corpus demo --strategy slide
raglab index --corpus demo --strategy late
```

Exemple pour préparer un run avec un autre provider ou modèle plus tard :

```bash
raglab index --corpus demo --strategy traditional --embedding-provider transformers --embedding-model intfloat/multilingual-e5-small
```

### 8. Requête

```bash
raglab query "Que dit le document sur la maintenance ?" --corpus demo --strategy traditional
```

### 9. Expérimentation

```bash
raglab experiment run data/experiments/sample_queries.jsonl --corpus demo --strategy traditional --strategy slide --strategy late
```

## Paramètres MVP retenus

- génération : `llama3.2:3b` via Ollama
- embeddings : `intfloat/multilingual-e5-small`
- top-k par défaut : `5`
- `traditional` : `900 / 150`
- `slide` : `900 / 300`
- `late` : chunk focal `700`, contexte `500`

## Limites actuelles

- pas d'OCR pour PDF image
- pas de reranker
- pas de Neo4j branché dans cette première version
- dimension d'embeddings homogène par instance de projet
