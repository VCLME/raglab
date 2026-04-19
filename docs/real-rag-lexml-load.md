# Cas Réel RAG Sans LLM

## Objectif

Ce document couvre un cas reel de chargement RAG sans phase de prompting LLM :

- collecte de donnees juridiques depuis LexML Brasil
- stockage des documents localement
- initialisation de PostgreSQL + pgvector via Docker
- ingestion dans la base
- indexation vectorielle avec une strategie RAG
- verification que les donnees persistent bien

Le but ici est de remplir la base et preparer le retrieval. Le prompting LLM viendra dans un second temps.

> **Note sur le benchmark.** La commande `raglab experiment recall --corpus lexml_real` genere automatiquement un jeu de tests a partir des metadata LexML locales. Ce jeu est utile comme **smoke test** (valider que le retrieval fonctionne sur un corpus reel), **pas comme benchmark rigoureux** : les questions sont des templates `"{titre}. {resume}"`, la verite terrain est heuristique (match de nom de fichier / URN), et il n'y a qu'une seule source pertinente par question. Pour une vraie evaluation comparative entre strategies, utiliser `raglab bench download <loader>` (ex : FQuAD) — voir [run-and-test.md](run-and-test.md) section 11b.

## Choix d'architecture

### Pourquoi ne pas faire une table par strategie ?

Ce projet ne cree pas une table `chunks_traditional`, `chunks_slide`, `chunks_late`.

On garde une seule structure logique :

- `documents`
- `index_runs`
- `chunks`
- `chunk_embeddings`

Chaque strategie est portee par un `index_run` distinct. Les chunks sont relies a ce `index_run`.

Ce choix est meilleur pour ce projet parce que :

- il evite la duplication de schema SQL
- il simplifie les migrations et la maintenance
- il permet de comparer plusieurs strategies sur le meme corpus
- il reste compatible avec la reindexation incrementale deja implemente

## Persistance Docker

Le `docker-compose.yml` utilise maintenant des volumes Docker nommes explicites :

- `raglab_postgres_data`
- `raglab_ollama_data`

Il expose aussi Adminer sur `http://localhost:8080` pour explorer la base visuellement.

Les donnees PostgreSQL persistent tant que tu ne fais pas :

```bash
docker compose down -v
```

Un simple :

```bash
docker compose down
docker compose up -d postgres
```

ne supprime pas les donnees.

## Workflow recommande

### 1. Demarrer PostgreSQL + pgvector

Pour ce cas sans LLM, seul PostgreSQL est indispensable :

```bash
docker compose up -d postgres
```

Si tu veux verifier la base visuellement pendant le chargement :

```bash
docker compose up -d postgres adminer
```

Connexion Adminer :

- systeme : `PostgreSQL`
- serveur : `postgres`
- utilisateur : `raglab`
- mot de passe : `raglab`
- base : `raglab`

### 2. Charger le corpus LexML dans la base

Commande orchestree :

```bash
raglab lexml load --corpus lexml_real --strategy traditional --page-limit 1
```

Cette commande fait automatiquement :

1. collecte LexML si le dossier local est vide
2. `db init`
3. ingestion du dossier LexML
4. indexation vectorielle dans PostgreSQL + pgvector

Par defaut, elle utilise :

- dossier de documents : `data/lexml/documents`
- tags : `legal`, `lexml`, `brasil`
- corpus : `lexml_real`
- strategie : `traditional`
- mode incremental active

### 3. Verifier les donnees chargees

Exemple de verification SQL :

```bash
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS corpora FROM corpora;"
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS documents FROM documents;"
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS index_runs FROM index_runs;"
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS chunks FROM chunks;"
```

### 4. Verifier la persistance

```bash
docker compose stop postgres
docker compose start postgres
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS documents FROM documents;"
```

Le nombre de documents doit rester stable.

## Variante manuelle

Si tu veux voir chaque etape separement :

```bash
docker compose up -d postgres
raglab db init
raglab lexml get-data --output-dir data/lexml/documents --page-limit 1
raglab lexml ingest --corpus lexml_real
raglab index --corpus lexml_real --strategy traditional
```

## Variante 100% Docker

Si tu veux rejouer exactement le test end-to-end sans dependre d'un Python local :

```bash
docker compose up -d postgres
docker compose --profile app up -d app
docker compose exec app python -m pytest -q
docker compose exec -e PYTHONPATH=/workspace/src app python -m raglab.cli lexml load --corpus lexml_real --strategy traditional --page-limit 1
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS documents FROM documents;"
docker compose exec -e PYTHONPATH=/workspace/src app python -m raglab.cli query "portaria advocacia geral uniao" --corpus lexml_real --strategy traditional --no-generate --top-k 3
docker compose restart postgres
docker compose exec postgres psql -U raglab -d raglab -c "SELECT COUNT(*) AS documents FROM documents;"
```

Cette variante est utile pour :

- valider l'image applicative en Python 3.12
- charger et indexer LexML sans LLM
- verifier le retrieval sans generation finale
- confirmer la persistance du volume `raglab_postgres_data`

## Notes pratiques

- pour un premier test rapide, garde `--page-limit 1`
- pour rerun plus tard, `raglab lexml load` reutilise le dossier local existant et peut profiter de l'indexation incrementale
- aucun appel Ollama n'est necessaire pour cette etape de chargement
