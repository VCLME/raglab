# Interface web raglab

raglab expose desormais une interface web pour piloter ingestion, indexation, retrieval, generation, collecte LexML et pilotage Ollama depuis un navigateur. L'interface est une couche additionnelle : la CLI `raglab` reste le mode d'emploi premier, l'UI reutilise les memes services Python via une API HTTP.

## Architecture

- **API** : FastAPI expose dans `src/raglab/api/`, servie par uvicorn. Les handlers appellent directement les services existants (`IngestionService`, `IndexingService`, `QueryService`, `OllamaService`, `LexMLLoadService`, `RecallBenchmarkService`). Aucune invocation de la CLI Typer en sous-processus.
- **Frontend** : application React + TypeScript + Vite dans `frontend/`. React Router pour les pages, `fetch` natif cote client, pas de dependance UI lourde. En production, bundle statique servi par nginx qui proxy `/api` vers le conteneur `api`.
- **Reutilisation** : aucun duplicata de logique metier. La methode `OllamaService.chat(...)` a ete ajoutee pour le Prompt Playground, elle est aussi disponible en Python pur.

Ports :

| Service | Port | URL |
| --- | --- | --- |
| PostgreSQL | 5432 | — |
| Adminer | 8080 | http://localhost:8080 |
| Ollama | 11434 | http://localhost:11434 |
| API raglab | 8000 | http://localhost:8000 (Swagger sur `/docs`) |
| Frontend (prod) | 8081 | http://localhost:8081 |
| Frontend (dev) | 5173 | http://localhost:5173 |

## Demarrage

### Mode Docker complet (recommande pour une demo)

```bash
docker compose up -d postgres ollama adminer
docker compose --profile app up -d api frontend
```

Puis :

- Frontend : http://localhost:8081
- Swagger de l'API : http://localhost:8000/docs
- Adminer : http://localhost:8080

Arret : `docker compose --profile app down` puis `docker compose down`.

### Mode dev local (boucle courte sur le frontend)

Dans un terminal :

```bash
docker compose up -d postgres ollama
raglab db init
raglab serve --dev
```

Dans un autre terminal :

```bash
cd frontend
npm install
npm run dev
```

Ouvrir http://localhost:5173. Le serveur Vite proxy `/api` vers `http://localhost:8000` (voir `frontend/vite.config.ts`).

## Deux modes

L'interface se scinde en deux modes accessibles via un toggle en haut a droite :

- **Mode Chat** (route `/`, icone bulle) : interface conversationnelle epuree pour interroger le RAG. Un seul ecran avec barre de parametres compacte, suggestions de questions, conversation et composer.
- **Mode Expert** (route `/expert`, icone fiole) : ensemble des ecrans techniques (Dashboard, RAG Query avec filtres fins, Playground Ollama, Ingestion, Indexation, LexML, Ollama, Experiments, Gestion).

Le top-bar affiche en plus un indicateur de sante (point colore) qui ping `/api/health` toutes les 15 s, et un **selecteur de langue** (drapeau + code pays) avec menu deroulant a gauche du toggle Chat/Expert.

## Internationalisation (i18n)

L'UI est traduite en trois langues via `react-i18next` :

- 🇫🇷 Francais (defaut, fallback)
- 🇬🇧 Anglais
- 🇧🇷 Portugais (Bresil)

La langue est persistee dans `localStorage.raglab.lang`, avec detection auto depuis `navigator.language` au premier chargement. Les chaines de l'UI sont regroupees dans `frontend/src/i18n/locales/{fr,en,pt-BR}.json` par domaine (`common`, `topbar`, `nav`, `chat`, `dashboard`, `query`, `playground`, `ingest`, `index`, `lexml`, `ollama`, `experiments`, `manage`).

Le composant `LanguageSwitcher` affiche le drapeau courant + code, et ouvre un menu avec les trois langues. Les drapeaux sont des SVG inline (`FlagIcon.tsx`) — pas de dependance externe.

Ce qui reste en francais cote serveur :
- messages d'erreur API (ex : `Corpus introuvable`, `Timeout Ollama`)
- dates/heures format ISO brut

## Mode Chat (`/`)

Ecran par defaut. Trois elements verticaux :

1. **Barre de parametres compacte** : deux dropdowns seulement.
   - **Corpus** : liste les corpus indexes, auto-selection du premier.
   - **Index** : liste les `index_run` disponibles pour ce corpus, chaque option etiquetee `strategie · modele_embedding · date`. Option par defaut `(plus recent) · <label du run le plus recent>`. Message explicite `— aucun index pour ce corpus —` si rien n'a ete indexe.

   La strategie de chunking et le modele d'embedding ne sont **plus** des selecteurs separes : ils sont figes par l'`index_run` choisi (ce sont des proprietes de l'indexation, pas du query). Voir [data-model.md](data-model.md) section 4.

2. **Zone de conversation** :
   - Etat vide : carte de bienvenue + 4 suggestions de questions cliquables, localisees par langue.
   - Etat rempli : bulles user/assistant. Chaque reponse assistant affiche les sources en pills (`1 fichier.txt · 0.84`), filtrables par clic ; un toggle « Afficher les N chunks » deplie les ChunkCard detailles (score, rank, texte, source_path). Bas de bulle : strategie, `index_run_id` tronque, temps d'execution.
   - **Citations inline cliquables** : le LLM inclut `[Rank N]` dans sa reponse. Chaque `[Rank N]` est rendu comme un petit badge accent monospace. Clic → active la pill de la source correspondante. Les sources reellement citees sont affichees d'office, les autres sont derriere un toggle `+N non cites`.
   - Le chargement et les erreurs sont affiches **inline** sous la bulle user (trois points pulsants pour le loading, ligne rouge `⚠` pour l'erreur avec un `detail` souligne pour deplier la trace technique).

3. **Composer** sticky en bas : textarea (Ctrl/Cmd + Entree pour envoyer), selecteur compact du modele LLM avec la valeur par defaut visible, bouton envoyer, bouton « Nouvelle conversation » dans la barre de parametres pour reset. Un helper sous le select rappelle l'index resolu : `index : traditional · intfloat/multilingual-e5-small`.

Chaque envoi declenche un appel `/api/query` independant. L'historique conversationnel est conserve cote React (pas de multi-tour cote backend : le Playground couvre ce cas sans RAG).

## Pages de l'interface

### Dashboard (`/expert`)

- Cartes d'etat : API, PostgreSQL, Ollama, Adminer.
- Badge « installe / manquant » sur le modele de generation par defaut + bouton de pull direct.
- Liste des corpus avec nombre de documents et de index runs.
- Tableau des 10 derniers index runs avec strategie, statut, nombre de chunks.

### RAG Query (`/expert/query`)

Le cœur experimental. Deux colonnes :

- Colonne gauche : parametres (question, corpus, strategie, index_run_id explicite, top_k, toggle generation) et filtres de retrieval (`document_ids`, `file_names`, `source_path_contains`, `tags`, `metadata_equals` au format `cle=valeur` par ligne).
- Colonne droite : reponse LLM (si generation activee), liste des `ChunkCard` avec score, rank, file_name, source_path et apercu du texte, temps d'execution, payload brut.
- Historique local (localStorage, 20 dernieres requetes) avec bouton « Rejouer ».

### Prompt Playground (`/expert/playground`)

Dialogue direct avec Ollama, **sans** retrieval. Conforme a la suggestion de livrable « interaction directe avec le modele Ollama ».

Parametres :

| Champ | Role |
| --- | --- |
| Modele | Modele Ollama (dropdown alimente par `/api/ollama/models`). Vide = defaut serveur. |
| System prompt | Message systeme optionnel. |
| Temperature | Slider 0 → 2. |
| top_p | Slider 0 → 1. |
| num_predict | Nombre max de tokens en sortie. |
| num_ctx | Taille de la fenetre de contexte. |
| seed | Graine pour la reproductibilite. |
| options JSON | Objet JSON additionnel, fusionne avec les champs ci-dessus (ex : `{"repeat_penalty": 1.1}`). |

Affichage :

- Conversation en bulles (user / assistant) persistee en memoire React.
- Payload envoye a Ollama affiche en JSON pour comprendre exactement ce qui a ete transmis.
- Temps d'execution (ms) renvoye par l'API.
- Bouton « Reset » pour repartir d'une conversation vide.

### Ingestion (`/expert/ingest`)

- Chemin de dossier **cote serveur** (memes semantiques que la CLI — le front n'upload pas de fichier pour le MVP).
- Nom de corpus, description optionnelle, tags separes par virgules.
- Resume visuel des compteurs `ingeres / maj / ignores` + payload JSON complet.

### Indexation (`/expert/index`)

- Corpus via dropdown alimente depuis `/api/corpora`.
- Strategie radio `traditional` / `slide` / `late`.
- Run name, embedding provider et embedding model optionnels.
- Toggle incremental pour reutiliser le dernier run compatible.

### LexML (`/expert/lexml`)

Deux cartes :

- **get-data** : `output_dir` et `page_limit`. Lance `getDataFromLexML`.
- **load** : orchestration complete (collecte + ingest + indexation). Parametres corpus, strategie, tags, `page_limit`, incremental.

Note : `load` est tres long. Le spinner indique simplement que l'appel est en cours — laissez la page ouverte.

### Ollama (`/expert/ollama`)

- Statut (URL, joignabilite, nombre de modeles, modele par defaut, installation).
- Tableau des modeles installes avec nom, taille, date, digest tronque. `qwen2.5:7b` est mis en valeur par la ligne surlignee « defaut ». Bouton `Supprimer` par ligne (avec confirmation ; avertissement special si c'est le modele de generation par defaut).
- Formulaire pour `pull` d'un modele arbitraire.

### Experiments (`/expert/experiments`)

- Exposition du benchmark Recall existant. Parametres corpus, strategie, `dataset_path` optionnel, `case_limit`.
- Reponse affichee en JSON.

### Gestion (`/expert/manage`)

Ecran de maintenance pour garder une base et un stock de modeles propres. Deux cartes :

- **Corpus** : tableau des corpus avec compteurs documents / index runs + bouton `Supprimer` (confirmation navigateur, cascade `documents -> chunks -> embeddings` + `index_runs`). Boutons `Importer un dossier…` et `Charger depuis LexML…` qui redirigent vers les pages dediees.
- **Modeles Ollama** : tableau des modeles installes avec taille et bouton `Supprimer` par ligne (refuse par defaut si c'est le modele de generation, simple avertissement via `confirm`). Formulaire `Importer un modele` pour declencher un `ollama pull` sans quitter la page.

La meme capacite de suppression est exposee sur la page Ollama (`/expert/ollama`) ligne par ligne.

## Endpoints API

Tous prefixes par `/api`. Swagger disponible sur http://localhost:8000/docs.

| Methode | Chemin | Role |
| --- | --- | --- |
| GET | `/api/health` | Etat API / PostgreSQL / Ollama / Adminer |
| GET | `/api/config` | Config non sensible (URL Ollama, modeles, chunk sizes, top_k) |
| GET | `/api/ollama/status` | Delegation a `OllamaService.status()` |
| GET | `/api/ollama/models` | Delegation a `OllamaService.list_models()` |
| POST | `/api/ollama/pull` | Delegation a `OllamaService.pull_model(model)` |
| DELETE | `/api/ollama/models/{name}` | Delegation a `OllamaService.delete_model(name)` |
| POST | `/api/ollama/chat` | Delegation a `OllamaService.chat(...)` — appel direct Ollama `/api/chat` sans RAG |
| GET | `/api/corpora` | Liste des corpus + compteurs |
| DELETE | `/api/corpora/{name}` | Supprime un corpus et cascade sur documents, chunks, embeddings et index runs |
| GET | `/api/index-runs?corpus=…` | Liste des index runs (avec `embedding_space_name`, `embedding_provider`, `embedding_model_name`, `embedding_dimension`) — consommé par l'Index picker du Chat |
| POST | `/api/ingest` | `IngestionService.ingest_folder(...)` |
| POST | `/api/index` | `IndexingService.index_corpus(...)` |
| POST | `/api/query` | `QueryService.query(...)` |
| POST | `/api/lexml/get-data` | `getDataFromLexML(...)` |
| POST | `/api/lexml/load` | `LexMLLoadService.run(...)` |
| POST | `/api/experiments/recall` | `RecallBenchmarkService.run(...)` |

## Tests

Backend :

```bash
pytest tests/api tests/test_ollama_chat.py -v
pytest
```

Frontend :

```bash
cd frontend
npm install
npm run build
```

`npm run build` invoque `tsc --noEmit` puis `vite build` — la compilation TS echoue si un type diverge.

Smoke test manuel :

1. `docker compose up -d postgres ollama adminer` puis `raglab db init`.
2. `raglab serve --dev` et `cd frontend && npm run dev`.
3. Ouvrir http://localhost:5173, verifier que le Dashboard affiche les statuts.
4. Aller dans Prompt Playground, envoyer « Bonjour » → reponse attendue d'Ollama.
5. Apres une ingestion et une indexation, aller dans RAG Query, poser une question et verifier les chunks + reponse.

## Exemple de session

1. Collecter LexML et indexer en une commande via l'UI : `LexML → load` avec `corpus=lexml_real`, `strategy=traditional`, `page_limit=1`.
2. Aller dans `RAG Query`, choisir `corpus=lexml_real`, poser une question : l'UI affiche les chunks et la reponse generee.
3. Basculer sur `Prompt Playground` pour comparer la meme question envoyee directement au modele, sans contexte : utile pour documenter l'apport du RAG.

## Variables d'environnement ajoutees

| Nom | Defaut | Role |
| --- | --- | --- |
| `RAGLAB_API_HOST` | `0.0.0.0` | Interface d'ecoute uvicorn |
| `RAGLAB_API_PORT` | `8000` | Port uvicorn |
| `RAGLAB_API_CORS_ORIGINS` | `["http://localhost:5173","http://localhost:8081",…]` | Liste JSON d'origines autorisees |
| `RAGLAB_ADMINER_URL` | `http://localhost:8080` | Affichee par le dashboard et `/api/health` |

## Limites actuelles

- Les operations longues (ingest, indexation, lexml load) sont synchrones : le front reste en spinner le temps de l'appel HTTP. Pas de file de jobs ni de stream de progression — a ajouter ulterieurement si besoin.
- Pas d'upload de fichiers depuis le navigateur : l'ingestion prend un chemin cote serveur raglab, comme la CLI.
- Pas d'authentification. L'API est prevue pour un usage local (equivalent a la CLI).
- Pas de test E2E automatise ; le smoke test est manuel.
