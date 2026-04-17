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
- [Cas réel RAG sans LLM](docs/real-rag-lexml-load.md)
- [Interface web raglab](docs/frontend-ui.md)

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

Pour ouvrir la base dans un navigateur avec Adminer :

```bash
docker compose up -d postgres adminer
```

Puis ouvrir `http://localhost:8080` avec :

- systeme : `PostgreSQL`
- serveur : `postgres`
- utilisateur : `raglab`
- mot de passe : `raglab`
- base : `raglab`

Pour obtenir des logs structures JSON dans la CLI :

```bash
raglab --log-json query "Que dit le document ?" --corpus demo --strategy traditional
```

### 2. Telecharger le modele de generation Ollama

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

Ou via la CLI du projet :

```bash
raglab ollama pull --model qwen2.5:7b
raglab ollama list
raglab ollama status
```

En mode 100 % Docker :

```bash
docker compose --profile app up -d app
docker compose exec app python -m raglab.cli ollama pull --model qwen2.5:7b
docker compose exec app python -m raglab.cli ollama list
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

Pour ne reindexer que les documents nouveaux ou modifies, tout en reutilisant les chunks/embeddings du dernier run compatible :

```bash
raglab index --corpus demo --strategy traditional --incremental
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

Le rapport compare maintenant aussi des metriques de ranking utiles pour le retrieval :

- `retrieval_hit_rate`
- `retrieval_precision`
- `retrieval_mrr`
- `mean_first_relevant_rank`

## LexML Brasil

La fonctionnalite LexML collecte des fiches documentaires juridiques depuis le portail public LexML Brasil, les stocke localement en `.txt` et `.json`, puis les reinjecte dans le pipeline RAG existant.

Commandes principales :

```bash
raglab lexml get-data --output-dir data/lexml/documents --page-limit 3
raglab lexml ingest --corpus lexml
raglab index --corpus lexml --strategy traditional
raglab experiment recall --corpus lexml --strategy traditional
```

Pour un vrai chargement sans LLM, tu peux aussi tout enchainer en une commande :

```bash
docker compose up -d postgres
raglab lexml load --corpus lexml_real --strategy traditional --page-limit 1
```

Points importants :

- les donnees LexML sont stockees dans `data/lexml/documents`
- si des donnees LexML locales existent deja, la collecte est skippee integralement
- la limite dure est codee en dur dans `MAX_LEXML_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024`
- le benchmark Recall genere un jeu de requetes simple depuis les metadata LexML locales puis calcule `Recall@K`, `Precision@K`, `MRR` et `mean_first_relevant_rank`
- les sidecars `.json` produits par LexML sont automatiquement reintegres comme metadata lors de `raglab lexml ingest`
- la persistance PostgreSQL est assuree par le volume Docker `raglab_postgres_data`
- Adminer est disponible sur `http://localhost:8080` pour explorer la base visuellement

## Parametres MVP retenus

- generation : `qwen2.5:7b` via Ollama
- embeddings : `intfloat/multilingual-e5-small`
- top-k par defaut : `5`
- `traditional` : `900 / 150`
- `slide` : `900 / 300`
- `late` : chunk focal `700`, contexte `500`
- generation : fallback explicite si le contexte est insuffisant, avec consigne de citation des sources

## Ollama

Le projet expose maintenant une CLI dediee a Ollama :

```bash
raglab ollama status
raglab ollama list
raglab ollama pull --model qwen2.5:7b
```

Le modele de generation par defaut est `qwen2.5:7b`.

Notes pratiques :

- le conteneur `ollama` persiste ses modeles dans le volume `raglab_ollama_data`
- `qwen2.5:7b` est plus exigeant que `llama3.2:3b` en RAM/VRAM
- si le modele n'est pas present localement, la generation indique maintenant explicitement la commande de pull a lancer

## Interface web

Une UI web React est disponible pour piloter ingestion, indexation, retrieval, generation et Ollama sans quitter le navigateur, ainsi qu'un Prompt Playground pour dialoguer directement avec Ollama. Voir [docs/frontend-ui.md](docs/frontend-ui.md).

Lancement Docker complet :

```bash
docker compose up -d postgres ollama adminer
docker compose --profile app up -d api frontend
```

- Frontend : http://localhost:8081
- API Swagger : http://localhost:8000/docs

Lancement dev local :

```bash
raglab serve --dev
cd frontend && npm install && npm run dev
```

L'UI est en http://localhost:5173 et parle a l'API http://localhost:8000 via proxy Vite.

## Limites actuelles

- pas d'OCR pour PDF image
- pas de reranker
- pas de Neo4j branche dans cette premiere version
- dimension d'embeddings homogene par instance de projet
- la collecte LexML V1 sauvegarde des fiches documentaires structurees issues du portail LexML, sans suivre encore les liens de texte integral des fournisseurs
- l'API web execute les operations longues (ingest, index, lexml load) en synchrone, sans file de jobs
