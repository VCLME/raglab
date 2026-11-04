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

Sous Windows, l'installateur officiel place Python 3.12 ici :

```powershell
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe
```

Si `python` ou `py -3.12` ne fonctionne pas encore dans ton terminal, utilise directement ce chemin.

## 2. Creer l'environnement virtuel

### Option recommandee

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
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
- `RAGLAB_OLLAMA_PULL_TIMEOUT_SECONDS`
- `RAGLAB_GENERATION_MODEL`
- `RAGLAB_GENERATION_NO_CONTEXT_ANSWER`
- `RAGLAB_EMBEDDING_MODEL_NAME`
- `RAGLAB_LOG_FORMAT`

## 4. Lancer les services

Demarrer PostgreSQL + pgvector et Ollama :

```powershell
docker compose up -d postgres ollama
```

Si tu veux inspecter PostgreSQL dans un navigateur, demarre aussi Adminer :

```powershell
docker compose up -d postgres adminer
```

Acces Adminer :

- URL : `http://localhost:8080`
- Systeme : `PostgreSQL`
- Serveur : `postgres`
- Utilisateur : `raglab`
- Mot de passe : `raglab`
- Base : `raglab`

Telecharger le modele de generation recommande :

```powershell
docker compose exec ollama ollama pull qwen2.5:7b
```

Ou via la CLI du projet :

```powershell
raglab ollama pull --model qwen2.5:7b
raglab ollama list
raglab ollama status
```

En mode 100 % Docker :

```powershell
docker compose --profile app up -d app
docker compose exec app python -m raglab.cli ollama pull --model qwen2.5:7b
docker compose exec app python -m raglab.cli ollama list
docker compose exec app python -m raglab.cli ollama status
```

### Rédacteur Qwen3.6 sur llama.cpp

Hors Docker, les réponses sont écrites par Qwen3.6-35B-A3B servi par llama-server (llama.cpp, build CUDA), et non par Ollama. Pourquoi : [technical-choices.md](technical-choices.md#3-bis-pourquoi-qwen36-via-llamacpp-pour-rédiger-les-réponses). raglab ne fournit ni le binaire ni le modèle : il appelle une commande de démarrage que tu lui donnes.

Dans `.env` :

```dotenv
RAGLAB_LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
RAGLAB_LLAMACPP_START_COMMAND=powershell -NoProfile -ExecutionPolicy Bypass -File C:\chemin\lamacpp\Start-LocalLLM.ps1 {profile}
RAGLAB_LLAMACPP_STOP_COMMAND=powershell -NoProfile -ExecutionPolicy Bypass -File C:\chemin\lamacpp\Stop-LocalLLM.ps1
RAGLAB_WRITER_MODEL_PROFILE=qwen35b-moe-rag
RAGLAB_WRITER_MODEL=qwen3.6-35b-a3b
```

Le rédacteur a **son propre profil**, `qwen35b-moe-rag` : contexte 16k et experts de 34 couches en RAM, pour laisser de la place au cross-encoder (mesures plus bas). Le profil `qwen35b-moe` (contexte 64k) reste celui du générateur de questions et de ton usage quotidien ; raglab ne le modifie pas. Avec `Start-LocalLLM.ps1`, ajoute une fois ce profil dans son `profiles.json`, à côté de `qwen35b-moe` (mêmes réglages, sauf `ctx` et `-ncmoe`, et le même alias pour que raglab reconnaisse le modèle) :

```json
"qwen35b-moe-rag": {
  "description": "Qwen3.6-35B-A3B pour raglab : contexte 16k, experts de 34 couches en RAM, laisse ~1 Go au cross-encoder.",
  "model": "Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf",
  "alias": "qwen3.6-35b-a3b",
  "label": "Qwen3.6 35B MoE · raglab",
  "benchOnly": true,
  "ctx": 16384,
  "output": 8192,
  "args": ["-np", "1", "-ngl", "all", "-ncmoe", "34", "-ub", "1024", "-b", "2048", "-fa", "on",
           "-ctk", "q8_0", "-ctv", "q8_0", "-t", "12", "--poll", "0", "--reasoning", "off",
           "--temp", "0.6", "--top-p", "0.95", "--top-k", "20", "--min-p", "0.0", "--presence-penalty", "0.0"]
}
```

(`benchOnly` le garde hors de la liste d'OpenCode.) Sans ce profil, le démarrage échoue et les réponses passent sur Ollama avec `generator_notice: "llamacpp_unavailable"` ; `/api/health` donne l'erreur dans `generator.error`. Ne pointe pas `RAGLAB_WRITER_MODEL_PROFILE` sur `qwen35b-moe` : à 64k, le rédacteur et le cross-encoder ne tiennent pas ensemble (voir le budget VRAM).

La commande doit **rendre la main** une fois llama-server lancé en arrière-plan (c'est ce que fait `Start-LocalLLM.ps1`) : `llama-server` appelé directement bloquerait jusqu'à `RAGLAB_LLAMACPP_START_TIMEOUT_SECONDS`, puis serait tué. Avec ton propre script, les réglages qui comptent pour la VRAM peuvent venir de raglab : `{model}`, `{ctx_size}` et `{n_cpu_moe}` sont remplis depuis `RAGLAB_LLAMACPP_PROFILE_OPTIONS` (défaut pour `qwen35b-moe-rag` : contexte 16 384, experts de 34 couches en RAM), à passer à `--alias`, `-c` et `--n-cpu-moe` :

```dotenv
RAGLAB_LLAMACPP_START_COMMAND=C:\llama\start-detached.cmd {model} {ctx_size} {n_cpu_moe}
RAGLAB_LLAMACPP_PROFILE_OPTIONS={"qwen35b-moe-rag": {"ctx_size": 16384, "n_cpu_moe": 34}, "qwen35b-moe": {"ctx_size": 65536, "n_cpu_moe": 32}, "gemma4-moe": {"ctx_size": 32768, "n_cpu_moe": 24}}
```

`Start-LocalLLM.ps1` ne prend que `{profile}` : ses réglages sont dans son `profiles.json`.

Ce qui se passe ensuite, sans rien lancer à la main :

1. la première question sans fournisseur explicite trouve llama.cpp arrêté : l'API décharge Ollama, lance la commande avec le profil du rédacteur dans un fil à part et attend jusqu'à `RAGLAB_LLAMACPP_AUTOSTART_WAIT_SECONDS` (120 s) ;
2. le serveur reste chargé ensuite (il n'est pas arrêté après la requête) ; arrête-le avec ta commande d'arrêt ;
3. si le démarrage échoue, prend trop longtemps, ou si llama.cpp sert un autre modèle (le juge Gemma d'un benchmark, vérifié par `GET /v1/models`), la réponse est écrite par Ollama `qwen2.5:7b` et porte `generator_notice` (`llamacpp_unavailable`, `llamacpp_starting`, `llamacpp_busy`) ; le Chat l'affiche sous la réponse et dans le choix du LLM ;
4. après un échec, l'API ne retente le démarrage qu'au bout de `RAGLAB_LLAMACPP_AUTOSTART_RETRY_SECONDS` (300 s).

`RAGLAB_LLAMACPP_AUTOSTART=false` n'utilise qu'un serveur déjà lancé. `RAGLAB_DEFAULT_LLM_PROVIDER=ollama` revient à l'ancien comportement. `RAGLAB_LLM_FALLBACK_PROVIDER=` (vide) fait échouer la requête au lieu de replier.

Vérifier l'état :

```powershell
Invoke-RestMethod http://localhost:8000/ready | ConvertTo-Json -Depth 4
```

`checks.llamacpp` vaut `ok`, `stopped` (démarrera à la prochaine question), `starting`, `busy`, `down` ou `failed` ; `generator.active_provider` dit qui écrit les réponses en ce moment. `/ready` reste à 200 tant que le rédacteur ou son repli peut répondre. `/api/health` passe en `degraded` quand c'est le repli qui répond.

**Budget VRAM (8 Go).** En production, le rédacteur et le cross-encoder du re-ranking (`bge-reranker-v2-m3`, fp16) sont chargés ensemble. Mesure du 4 novembre 2026 sur la RTX 3070 Ti Laptop du propriétaire : llama-server avec les réglages du profil `qwen35b-moe` sauf `-c` et `-ncmoe`, l'API avec le cross-encoder sur le GPU, 10 vraies questions par configuration.

| Contexte | `-ncmoe` | Rédacteur seul | Pic avec le re-ranking | Génération (tok/s, p50) | Génération p50 | Re-ranking p50 | Re-ranking sur GPU |
|---|---|---|---|---|---|---|---|
| 65 536 | 32 | 6,2 Go | dépasse 8 Go : 7,8 Go dédiés + 0,45 à 0,6 Go en mémoire partagée | **2,9** | — | — | — |
| 16 384 | 32 | 6,28 Go | 7,74 Go | 36,6 | 6,1 s | 323 ms | 10/10 |
| **16 384** | **34** | **5,41 Go** | **7,10 Go** | **33,6** | **7,2 s** | **335 ms** | **10/10** |
| 8 192 | 32 | 5,98 Go | 7,67 Go | 36,6 | 6,5 s | 311 ms | 10/10 |

Le profil 64k du quotidien déborde en mémoire partagée : sous Windows, rien n'échoue, mais la génération tombe à 2,9 tok/s. Les trois profils à 16k ou 8k tiennent. Le rédacteur de production est donc **16k, `-ncmoe 34`** (profil `qwen35b-moe-rag`) : environ 1 Go de marge, au prix de 8 % de débit et d'une seconde au p50 par rapport à `-ncmoe 32`, qui ne laisse que 0,26 Go. Passer à 8k ne fait presque rien gagner (le cache KV `q8_0` est petit) ; 16k laisse de la place aux longs passages juridiques. Valide toute autre configuration sur le compteur « Mémoire GPU partagée » du Gestionnaire des tâches pendant une requête avec re-ranking, pas seulement sur « offloaded 41/41 ». Le garde-fou du re-ranking ne change pas : sans GPU utilisable, le re-ranking par défaut est sauté et la réponse le dit (`rerank_notice`).

**Benchmarks.** `LocalLLMServer` vérifie le modèle servi : avant la passe du juge, un rédacteur resté chargé est arrêté et Gemma est démarré, puis arrêté à la fin ; la question suivante du Chat relance le rédacteur. Pendant la notation, le Chat répond avec Ollama (`llamacpp_busy`) et partage le GPU avec le juge : évite de l'utiliser pendant un benchmark.

**Docker.** Par défaut, les services `api` et `app` fixent `RAGLAB_LLM_PROVIDERS=ollama` et `RAGLAB_DEFAULT_LLM_PROVIDER=ollama`, et répondent avec `qwen2.5:7b` comme avant. L'override `docker-compose.llamacpp.yml` ajoute le rédacteur dans son propre conteneur (`raglab-llamacpp`, image `ghcr.io/ggml-org/llama.cpp:server-cuda13-b11429`, la même build qu'en natif) et bascule l'API dessus, Ollama restant le repli.

Prérequis : le GPU visible par Docker (comme pour `docker-compose.gpu.yml`) et environ 17 Go de RAM pour le conteneur, les experts du MoE restant en RAM. Sous Docker Desktop, WSL2 ne reçoit par défaut que la moitié de la RAM : dans `%USERPROFILE%\.wslconfig`, mettre `[wsl2]` puis `memory=26GB`, et lancer `wsl --shutdown`.

Une seule fois, télécharger le modèle (16,8 Go) dans le volume nommé `raglab_llamacpp_models` (un dossier Windows monté serait lent pour le `mmap`) :

```powershell
docker compose -f docker-compose.yml -f docker-compose.llamacpp.yml run --rm llamacpp-model
```

Si le GGUF est déjà sur le disque, le copier plutôt que le retélécharger :

```powershell
docker run --rm -v raglab_llamacpp_models:/models -v "C:/chemin/models:/src:ro" alpine cp /src/Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf /models/
```

Puis démarrer la pile :

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.llamacpp.yml --profile app up -d
docker logs -f raglab-llamacpp   # attendre « server is listening »
```

Dans ce mode, l'API ne démarre ni n'arrête llama-server (`RAGLAB_LLAMACPP_AUTOSTART=false`) : c'est Compose qui le fait. Pendant le chargement (quelques minutes depuis le volume), les réponses viennent d'Ollama avec `generator_notice: "llamacpp_unavailable"`. Le serveur est publié sur `127.0.0.1:8090` seulement (8080 est pris par Adminer) ; l'API le joint par le réseau Compose. Réglages, à mettre dans l'environnement ou le `.env` de Compose : `RAGLAB_WRITER_CTX_SIZE` (16 384), `RAGLAB_WRITER_N_CPU_MOE` (34, comme en natif ; 32 est un peu plus rapide si rien d'autre n'utilise le GPU), `RAGLAB_WRITER_GGUF`, `RAGLAB_LLAMACPP_IMAGE_TAG` (`server-cuda12-b11429` pour un pilote CUDA 12). L'image `api` embarque torch sans CUDA : le re-ranking par défaut y est sauté, le rédacteur n'a donc pas à partager le GPU avec le cross-encoder ; il le partage avec Ollama, que l'API décharge avant chaque réponse llama.cpp. Rien de ce mode n'a encore été mesuré (VRAM, débit, temps de chargement sous WSL2).

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

Le prompt de generation :

- force la reponse a rester strictement ancree dans le contexte
- impose un fallback explicite si le contexte est insuffisant
- demande au modele de citer chaque fait **inline** avec `[Rank N]` juste apres l'affirmation (N = rank du chunk utilise)
- interdit explicitement d'ajouter une section `Sources:` en fin de reponse : c'est l'UI qui rend les sources cote front, et la CLI affiche les `retrieved_chunks` separement

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

Corpus « Bresil expat » (19 textes federaux compiles, Planalto et Receita Federal, voir [corpus-br-expat.md](corpus-br-expat.md)) :

```powershell
raglab lexml br-expat
raglab bench all --suite br_expat --label brexpat-full-v1 --ragas-limit 0
```

La commande `bench all` ingere et indexe le corpus dans `bench_br_expat_pt` avant de lancer les 38 questions figees.

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

**Attention** : ce jeu auto-genere depuis LexML est utile comme **smoke test** mais pas comme benchmark rigoureux. Les questions sont des templates (`"{titre}. {resume}"`), la verite terrain est heuristique (match de nom de fichier / URN) et il n'y a qu'une seule source pertinente par question. Pour une vraie evaluation, passer par la commande `raglab bench download` ci-dessous.

## 11b. Lancer un benchmark sur FQuAD

Pour evaluer sur un dataset Q/R a verite terrain humaine, raglab expose le module `benchmarks`. Le premier loader disponible telecharge **FQuAD v1.0** (SQuAD francais, articles Wikipedia, CC-BY-SA-3.0).

```powershell
raglab bench download fquad --limit 50
raglab ingest data/benchmarks/fquad/corpus --corpus fquad_fr
raglab index --corpus fquad_fr --strategy traditional
raglab experiment recall --corpus fquad_fr --strategy traditional --dataset-path data/benchmarks/fquad/ground_truth.jsonl
```

Ce que produit `bench download` :

```
data/benchmarks/fquad/
├── metadata.json           # loader, source, taille, langue, licence
├── corpus/
│   ├── article_<hash>.txt  # un fichier par article Wikipedia distinct
│   └── article_<hash>.json # sidecar metadata (title, url, source)
└── ground_truth.jsonl      # une ligne par question, format ExperimentCase
```

Chaque ligne de `ground_truth.jsonl` suit le schema :

```json
{"id": "fquad-42", "question": "…", "expected_file_names": ["article_abcd1234.txt"], "ground_truth_answer": "…", "expected_substrings": ["…"]}
```

Le `RecallBenchmarkService` existant consomme ce fichier tel quel via `--dataset-path`.

`--limit N` permet de couper le volume de paires pour un premier run rapide. Sans `--limit`, le loader telecharge la totalite du split `validation` (~3 200 paires sur ~128 articles) — plusieurs minutes sur machine locale.

Les loaders supplementaires (MIRACL, PIAF, SciFact, mMARCO-fr) sont en roadmap Phase 7 — le squelette est en place pour les ajouter un par un.

## 12. Cas reel sans LLM

Pour charger un vrai corpus LexML dans PostgreSQL + pgvector sans phase de prompting :

```powershell
docker compose up -d postgres
raglab lexml load --corpus lexml_real --strategy traditional --page-limit 1
```

Cette commande :

- collecte LexML si necessaire
- initialise la base
- ingere les documents dans `documents`
- cree un `index_run`
- remplit `chunks` et `chunk_embeddings`

Le stockage PostgreSQL est persistant via le volume Docker `raglab_postgres_data`.
Tu peux verifier visuellement le contenu dans Adminer sur `http://localhost:8080`.

## 13. Executer les tests

### Suite de tests

```powershell
.venv\Scripts\python.exe -m pytest
```

Resultat verifie sur cette machine :

```text
35 passed
```

### Verifier que la CLI demarre

```powershell
.venv\Scripts\raglab.exe --help
```

### Activer le GPU Nvidia pour Ollama (optionnel)

Si tu as un GPU Nvidia et le `nvidia-container-toolkit` (ou Docker Desktop + WSL2 sous Windows), combine `docker-compose.gpu.yml` pour que le conteneur Ollama exploite le GPU :

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d ollama
```

Verifie la detection :

```bash
docker logs raglab-ollama 2>&1 | grep -i "inference compute"
```

Tu dois voir une ligne type `library=CUDA ... description="NVIDIA ..."` avec la VRAM disponible. Sans l'override, le conteneur tourne en CPU (fallback).

Bench observe sur RTX 3070 Ti Laptop 8 Go, `qwen2.5:7b` Q4 :

| Mode | eval tok/s | eval duration (40 tokens) |
| --- | --- | --- |
| CPU | 10.7 | 3.74 s |
| GPU CUDA | 38.2 | 1.04 s |

### Lancer l'API et le frontend

L'API FastAPI est cablee sur les memes services que la CLI. Dev local :

```powershell
raglab serve --dev
```

Puis dans un autre terminal :

```powershell
cd frontend
npm install
npm run build
npm run dev
```

- API : http://localhost:8000 (Swagger sur `/docs`)
- Frontend Vite : http://localhost:5173

Verification rapide :

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

La reponse doit contenir `api = ok` et `postgres = ok`.

Pour un lancement 100 % Docker :

```powershell
docker compose up -d postgres ollama adminer
docker compose --profile app up -d api frontend
```

Frontend Nginx : http://localhost:8081.

Plus de details dans [frontend-ui.md](frontend-ui.md).

## 14. Sequence minimale recommandee

Si tu veux juste verifier rapidement que tout tourne :

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
docker compose up -d postgres ollama
docker compose exec ollama ollama pull qwen2.5:7b
raglab db init
raglab ingest data/documents --corpus demo
raglab index --corpus demo --strategy traditional
raglab query "Quel est le sujet principal ?" --corpus demo --strategy traditional
python -m pytest
```

## 15. Depannage

### `python` n'est pas reconnu

Utiliser le chemin complet :

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
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
raglab ollama status
raglab ollama list
```

### PostgreSQL ne repond pas

Verifier :

```powershell
docker compose logs postgres
```

## 16. Etat valide actuellement

Validation effectuee :

- Python 3.12.10 installe
- environnement virtuel cree
- dependances installees
- `pytest` execute avec succes
- CLI `raglab --help` verifiee
- `raglab ollama status` et `raglab ollama list` verifies
- `qwen2.5:7b` telecharge avec succes via Ollama
