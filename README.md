# raglab

Projet RAG local oriente experimentation sur des dossiers de documents `.txt`, `.pdf`, `.docx`.

Le projet fournit :

- PostgreSQL + pgvector pour le stockage vectoriel
- Ollama pour la generation locale
- une CLI pour ingerer, indexer, requeter et lancer des experiences
- trois strategies de chunking comparables :
  - `traditional`
  - `slide`
  - `late`
- une architecture prete pour une future coexistence PostgreSQL vectoriel + Neo4j
- une collecte dediee LexML Brasil pour constituer un corpus juridique local
- un benchmark de recall pour evaluer la qualite du retrieval

## Documents de cadrage

- [Architecture](docs/architecture.md)
- [Choix techniques](docs/technical-choices.md)
- [Plan d'experimentation](docs/experimentation-plan.md)
- [Roadmap](docs/roadmap.md)
- [Modele de donnees](docs/data-model.md)
- [Lancer et tester le projet](docs/run-and-test.md)

## Structure

```text
.
├── docs/
├── data/
│   ├── documents/
│   ├── experiments/
│   ├── lexml/
│   │   ├── benchmark/
│   │   └── documents/
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
│   ├── lexml/
│   ├── retrieval/
│   └── stores/
├── tests/
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Demarrage rapide

### 1. Lancer les services

```bash
docker compose up -d postgres ollama
```

### 2. Telecharger le modele de generation Ollama

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

### 3. Installer le projet cote Python

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

### 4. Preparer la configuration

```bash
copy .env.example .env
```

### 5. Initialiser la base

```bash
raglab db init
```

### 6. Ingestion locale classique

```bash
raglab ingest data/documents --corpus demo
```

Les fichiers `.txt`, `.pdf` et `.docx` peuvent embarquer des metadonnees via un sidecar JSON portant le meme nom logique, par exemple `contrat.txt` + `contrat.json`.
Des tags peuvent aussi etre ajoutes a l'ingestion :

```bash
raglab ingest data/documents --corpus demo --tag legal --tag contrat
```

### 7. Indexation

```bash
raglab index --corpus demo --strategy traditional
raglab index --corpus demo --strategy slide
raglab index --corpus demo --strategy late
```

Exemple pour preparer un run avec un autre provider ou modele plus tard :

```bash
raglab index --corpus demo --strategy traditional --embedding-provider transformers --embedding-model intfloat/multilingual-e5-small
```

### 8. Requete

```bash
raglab query "Que dit le document sur la maintenance ?" --corpus demo --strategy traditional
```

Exemples de filtres de retrieval :

```bash
raglab query "Que dit la loi ?" --corpus lexml --strategy traditional --tag legal
raglab query "Que dit la loi ?" --corpus lexml --strategy traditional --file-name lexml_abc.txt
raglab query "Que dit la loi ?" --corpus lexml --strategy traditional --metadata-eq authority="Senado Federal"
raglab query "Que dit la loi ?" --corpus lexml --strategy traditional --metadata-eq locality=Brasil --source-path-contains lexml
```

### 9. Experimentation classique

```bash
raglab experiment run data/experiments/sample_queries.jsonl --corpus demo --strategy traditional --strategy slide --strategy late
```

## LexML Brasil

La fonctionnalite LexML collecte des fiches documentaires juridiques depuis le portail public LexML Brasil, les stocke localement en `.txt` et `.json`, puis les reinjecte dans le pipeline RAG existant.

Commandes principales :

```bash
raglab lexml get-data --output-dir data/lexml/documents --page-limit 3
raglab lexml ingest --corpus lexml
raglab index --corpus lexml --strategy traditional
raglab experiment recall --corpus lexml --strategy traditional
```

Points importants :

- les donnees LexML sont stockees dans `data/lexml/documents`
- si des donnees LexML locales existent deja, la collecte est skippee integralement
- la limite dure est codee en dur dans `MAX_LEXML_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024`
- le benchmark Recall genere un jeu de requetes simple depuis les metadata LexML locales puis calcule `Recall@1`, `Recall@5` et `Recall@10`
- les sidecars `.json` produits par LexML sont automatiquement reintegres comme metadata lors de `raglab lexml ingest`

## Parametres MVP retenus

- generation : `llama3.2:3b` via Ollama
- embeddings : `intfloat/multilingual-e5-small`
- top-k par defaut : `5`
- `traditional` : `900 / 150`
- `slide` : `900 / 300`
- `late` : chunk focal `700`, contexte `500`

## Limites actuelles

- pas d'OCR pour PDF image
- pas de reranker
- pas de Neo4j branche dans cette premiere version
- dimension d'embeddings homogene par instance de projet
- la collecte LexML V1 sauvegarde des fiches documentaires structurees issues du portail LexML, sans suivre encore les liens de texte integral des fournisseurs
