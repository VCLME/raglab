# Lancer et tester le projet

## Objectif

Ce document explique comment :

- preparer l'environnement local
- lancer les dependances du projet
- initialiser la base
- ingerer des documents
- indexer le corpus
- interroger le RAG
- executer les tests

Les commandes ci-dessous sont pensees pour Windows PowerShell.

## 1. Prerequis

Il faut disposer de :

- Python 3.12
- Docker Desktop avec `docker compose`
- un acces reseau pour telecharger les dependances Python et les modeles

Sur cette machine, Python a ete installe ici :

```powershell
C:\Users\lucme\AppData\Local\Programs\Python\Python312\python.exe
```

Si `python` ou `py -3.12` ne fonctionne pas encore dans ton terminal, utilise directement ce chemin.

## 2. Creer l'environnement virtuel

### Option recommandee

```powershell
& 'C:\Users\lucme\AppData\Local\Programs\Python\Python312\python.exe' -m venv .venv
```

### Activer l'environnement

```powershell
.venv\Scripts\Activate.ps1
```

### Installer les dependances

```powershell
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## 3. Configurer le projet

Copier le fichier d'environnement :

```powershell
Copy-Item .env.example .env
```

Variables importantes :

- `RAGLAB_DATABASE_URL`
- `RAGLAB_OLLAMA_BASE_URL`
- `RAGLAB_GENERATION_MODEL`
- `RAGLAB_EMBEDDING_MODEL_NAME`
- `RAGLAB_LOG_FORMAT`

## 4. Lancer les services

Demarrer PostgreSQL + pgvector et Ollama :

```powershell
docker compose up -d postgres ollama
```

Telecharger le modele de generation recommande :

```powershell
docker compose exec ollama ollama pull llama3.2:3b
```

## 5. Initialiser la base

```powershell
raglab db init
```

Si le script `raglab` n'est pas resolu dans le shell, utiliser :

```powershell
.venv\Scripts\raglab.exe db init
```

## 6. Ajouter des documents

Placer les fichiers `.txt`, `.pdf`, `.docx` dans `data/documents/`, puis lancer :

```powershell
raglab ingest data/documents --corpus demo
```

Si un document possede un sidecar JSON adjacent, par exemple `sample.txt` et `sample.json`, les champs du JSON sont fusionnes dans `metadata_json` au moment de l'ingestion. Les tags peuvent aussi etre poses en CLI :

```powershell
raglab ingest data/documents --corpus demo --tag legal --tag hr
```

## 7. Construire les index

### Traditional chunking

```powershell
raglab index --corpus demo --strategy traditional
```

### Reindexation incrementale legere

Le mode incremental cree un nouveau `index_run`, mais reutilise les chunks et embeddings du dernier run compatible pour les documents inchanges. Seuls les documents nouveaux ou modifies sont recalcules.

```powershell
raglab index --corpus demo --strategy traditional --incremental
```

### Slide chunking

```powershell
raglab index --corpus demo --strategy slide
```

### Late chunking

```powershell
raglab index --corpus demo --strategy late
```

### Tester un autre modele d'embeddings plus tard

```powershell
raglab index --corpus demo --strategy traditional --embedding-provider transformers --embedding-model intfloat/multilingual-e5-small
```

## 8. Poser une question au RAG

```powershell
raglab query "Que dit le document sur la maintenance ?" --corpus demo --strategy traditional
```

Exemples de filtres :

```powershell
raglab query "Resume la loi" --corpus lexml --strategy traditional --tag legal
raglab query "Resume la loi" --corpus lexml --strategy traditional --metadata-eq authority="Senado Federal"
raglab query "Resume la loi" --corpus lexml --strategy traditional --source-path-contains lexml
```

## 9. Lancer une experience comparative

Le projet contient un exemple de dataset ici :

```text
data/experiments/sample_queries.jsonl
```

Commande :

```powershell
raglab experiment run data/experiments/sample_queries.jsonl --corpus demo --strategy traditional --strategy slide --strategy late
```

Les rapports sont produits dans :

```text
data/reports/
```

Les rapports incluent maintenant aussi des metriques de ranking de retrieval comme `retrieval_precision`, `retrieval_mrr` et `mean_first_relevant_rank`.

## 10. Collecter des donnees LexML Brasil

Collecte des fiches documentaires LexML dans un dossier dedie :

```powershell
raglab lexml get-data --output-dir data/lexml/documents --page-limit 3
```

Points a connaitre :

- les fichiers sont ecrits dans `data/lexml/documents`
- si ce dossier contient deja des donnees, la collecte est entierement skippee
- la collecte applique une limite dure codee dans le projet :

```python
MAX_LEXML_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
```

Pour injecter ensuite ces donnees dans le pipeline RAG :

```powershell
raglab lexml ingest --corpus lexml
```

Les fichiers `*.json` generes a cote des `*.txt` LexML sont automatiquement relus comme metadata au moment de cette ingestion.

## 11. Lancer le benchmark de recall

Une fois le corpus LexML ingere et indexe :

```powershell
raglab index --corpus lexml --strategy traditional
raglab experiment recall --corpus lexml --strategy traditional
```

Le benchmark :

- genere un jeu de requetes de test a partir des metadata LexML locales si aucun dataset n'est fourni
- utilise une verite terrain simple basee sur les noms de fichiers et les URN attendues
- calcule `Recall@K`, `Precision@K`, `MRR` et `mean_first_relevant_rank`
- ecrit un rapport JSON dans `data/reports/`

## 12. Executer les tests

### Suite de tests

```powershell
.venv\Scripts\python.exe -m pytest
```

Resultat verifie sur cette machine :

```text
25 passed
```

### Verifier que la CLI demarre

```powershell
.venv\Scripts\raglab.exe --help
```

## 13. Sequence minimale recommandee

Si tu veux juste verifier rapidement que tout tourne :

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
docker compose up -d postgres ollama
docker compose exec ollama ollama pull llama3.2:3b
raglab db init
raglab ingest data/documents --corpus demo
raglab index --corpus demo --strategy traditional
raglab query "Quel est le sujet principal ?" --corpus demo --strategy traditional
python -m pytest
```

## 14. Depannage

### `python` n'est pas reconnu

Utiliser le chemin complet :

```powershell
& 'C:\Users\lucme\AppData\Local\Programs\Python\Python312\python.exe' --version
```

### `raglab` n'est pas reconnu

Utiliser directement l'executable du venv :

```powershell
.venv\Scripts\raglab.exe --help
```

### Logs structures JSON

Tu peux aussi activer les logs structures pour n'importe quelle commande :

```powershell
raglab --log-json query "Resume le document" --corpus demo --strategy traditional
```

### Ollama ne repond pas

Verifier les conteneurs :

```powershell
docker compose ps
```

Puis tester le modele :

```powershell
docker compose exec ollama ollama list
```

### PostgreSQL ne repond pas

Verifier :

```powershell
docker compose logs postgres
```

## 15. Etat valide actuellement

Validation effectuee :

- Python 3.12.10 installe
- environnement virtuel cree
- dependances installees
- `pytest` execute avec succes
- CLI `raglab --help` verifiee
