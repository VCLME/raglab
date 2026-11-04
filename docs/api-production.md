# API en production (phase 9.5)

Ce document décrit le durcissement de l'API FastAPI (`src/raglab/api/`) :
streaming des réponses, budgets de temps par étape, identifiant de
corrélation, clé d'API, limitation de débit, sondes de santé et erreurs
Ollama typées. Par défaut tout reste compatible avec l'usage local du
laboratoire : pas de clé, pas de limite, `POST /api/query` inchangé.

## Vue d'ensemble

| Brique | Réglage | Par défaut | Effet |
|---|---|---|---|
| Streaming SSE | — | actif | `POST /api/query/stream` : sources puis réponse au fil de l'eau |
| Budget embedding | `RAGLAB_EMBED_TIMEOUT_SECONDS` | 30 | 504 `stage=embed` |
| Budget recherche | `RAGLAB_RETRIEVAL_TIMEOUT_SECONDS` | 15 | 504 `stage=retrieval` (`statement_timeout` Postgres) |
| Budget génération | `RAGLAB_GENERATION_TIMEOUT_SECONDS` | 120 | 504 `stage=generation` |
| Corrélation | en-tête `X-Request-ID` | généré | renvoyé dans la réponse et présent dans chaque ligne de log |
| Clé d'API | `RAGLAB_API_KEY` | vide = désactivée | 401 sans la bonne clé |
| Limite de débit | `RAGLAB_API_RATE_LIMIT_REQUESTS` / `RAGLAB_API_RATE_LIMIT_WINDOW_SECONDS` | 0 = désactivée / 60 | 429 + `Retry-After` |
| OOM Ollama | `RAGLAB_OLLAMA_RETRY_AFTER_SECONDS` | 30 | 503 + `Retry-After` |
| Sonde `/ready` | `RAGLAB_READY_TIMEOUT_SECONDS` | 3 | délai max pour interroger Ollama |
| Collecte d'une source officielle | `RAGLAB_SOURCE_FETCH_TIMEOUT_SECONDS` | 3600 | tâche `failed`, erreur 504 avec l'étape (`fetch`, `verify`, `ingest`) |
| Appel git (Légifrance) | `RAGLAB_LEGIFRANCE_GIT_TIMEOUT_SECONDS` | 600 | tâche `failed`, erreur 504 `stage=fetch` |
| Requêtes CELLAR (EUR-Lex) | `RAGLAB_EURLEX_REQUEST_DELAY_SECONDS` / `RAGLAB_EURLEX_REQUEST_TIMEOUT_SECONDS` | 1 (min. 0,2) / 60 | espacement et délai de chaque requête |

Un budget à `0` désactive la limite correspondante.

## Streaming : `POST /api/query/stream`

Même corps que `POST /api/query` (`question`, `corpus`, `index_run_id`,
`top_k`, `generate`, `filters`). La réponse est un flux
[Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
(`text/event-stream`) :

| Événement | Quand | Contenu |
|---|---|---|
| `retrieval` | une fois, avant la génération | un `QueryResponse` partiel : `retrieved_chunks` (scores, rangs), `timings_ms.embed`, `timings_ms.retrieval`, `answer: null` |
| `token` | à chaque fragment produit par Ollama | `{"text": "..."}` |
| `done` | une fois, à la fin | le `QueryResponse` complet (`answer`, `timings_ms.generation`, `generation_stats`) + `first_token_ms` |
| `error` | si la génération échoue en cours de route | `{"status": 503, "detail": "...", "error": "OllamaOutOfMemoryError", ...}` |

### Mode pédagogique : événements `pipeline` et `stage`

Événements additifs, intercalés dans la séquence ci-dessus sans la modifier
(un client qui ne les connaît pas les ignore ; `/api/query` ne change pas) :

| Événement | Quand | Contenu |
|---|---|---|
| `pipeline` | une fois, en premier | `{"stages": ["embed", "retrieval", "prompt", "generation"]}` : les étapes que la requête exécute, dans l'ordre |
| `stage` | au début et à la fin de chaque étape | `{"stage", "status": "start" \| "end", "t_ms", "live"}` ; à la fin, en plus `duration_ms`, `counts` et `data` |

Ordre : `pipeline`, étapes de recherche rejouées (`live: false`), `retrieval`,
`prompt` (début / fin), `generation` (début), `token`…, `generation` (fin),
`done`. Si la génération échoue, `generation` reste ouverte et `error` suit.

La liste des étapes est déduite de ce que la requête a réellement exécuté
(`src/raglab/retrieval/stages.py`) : clés de `timings_ms` (`embed`,
`retrieval`, et `dense`, `lexical`, `fusion`, `rerank` quand la recherche
hybride ou le re-ranking ont tourné), décision du routeur si présente, puis
`prompt` et `generation` si une réponse est demandée. Avec la recherche
hybride, l'étape `retrieval` porte la durée de la partie vectorielle
(`dense`). Aucune de ces étapes n'est requise.

| Étape | `counts` | `data` |
|---|---|---|
| `embed` | `dimension` | `head` (8 premières valeurs), `norm`, `dimension` |
| `retrieval`, `lexical`, `fusion`, `rerank` | `chunks_out` (+ `top_k`, `candidates_in`) | `top_chunks` : 5 premiers passages (`rank`, `file_name`, `excerpt` de 160 caractères, tous les champs `*score`) |
| `routing` | — | la décision du routeur (`RoutingDecision`) |
| `prompt` | `chunks_in`, `prompt_chars` | `system_prompt`, `user_prompt` (600 premiers caractères), `truncated` |
| `generation` | `output_tokens`, `prompt_tokens`, `tokens_per_second`, `fragments`, `first_token_ms` | `model` |

Embedding et recherche tournent avant l'ouverture du flux (pour garder un vrai
code HTTP en cas d'échec), d'où leur rejeu : `t_ms` est cumulé depuis le début
de l'embedding, `duration_ms` est la durée mesurée.

```bash
curl -N -X POST http://localhost:8000/api/query/stream \
  -H 'Content-Type: application/json' \
  -d '{"question": "Que dit la loi sur la durée du contrat ?", "corpus": "piaf"}'
```

```text
event: retrieval
data: {"question": "...", "retrieved_chunks": [{"chunk_id": "...", "score": 0.83, "rank": 1, ...}], "timings_ms": {"embed": 41.2, "retrieval": 18.7}, "answer": null, ...}

event: token
data: {"text": "Le contrat "}

event: done
data: {"answer": "Le contrat dure un an [Rank 1].", "timings_ms": {"embed": 41.2, "retrieval": 18.7, "generation": 2875.1}, "generation_stats": {"output_tokens": 61, "tokens_per_second": 38.4}, "first_token_ms": 412.3, ...}
```

Choix de conception :

- **La recherche s'exécute avant l'ouverture du flux.** Une requête invalide,
  un index introuvable ou un dépassement de budget embed / retrieval renvoie
  donc un vrai code HTTP (400, 504) au lieu d'un flux 200 qui échoue. Seules
  les erreurs de génération arrivent sous forme d'événement `error`, puisque
  le statut 200 est déjà parti.
- **Ollama est appelé avec `stream: true`** (`OllamaGenerator.stream_answer`) ;
  les compteurs de tokens viennent du dernier message `done` d'Ollama, comme
  en mode non streamé.
- **En-têtes** `Cache-Control: no-cache` et `X-Accel-Buffering: no` pour
  qu'un nginx placé devant ne bufferise pas le flux.
- **Le corps `done` est un `QueryResponse`** : un client peut ignorer les
  `token` et ne lire que `done`, il obtient exactement ce que renvoie
  `/api/query`.

Côté interface, la page Chat utilise ce flux : les sources s'affichent dès
l'événement `retrieval`, la réponse se construit token par token, et le temps
jusqu'au premier token apparaît sous la réponse. Si le flux n'est pas
utilisable (API plus ancienne qui répond 404/405, proxy qui coupe le flux
avant le premier événement, navigateur sans `ReadableStream`), le client
retombe sur `POST /api/query` sans rien changer pour l'utilisateur
(`queryWithStreaming` dans `frontend/src/api/client.ts`).

En CLI, `raglab query "..." --corpus piaf --stream` affiche la réponse au fil
de l'eau sur stderr et garde le JSON final sur stdout.

## Budgets de temps par étape

Chaque étape de `/api/query` et `/api/query/stream` a son budget. En cas de
dépassement, l'API répond **504** en nommant l'étape :

```json
{
  "detail": "Timeout a l'etape embed : pas de resultat apres 30 s. Augmente RAGLAB_EMBED_TIMEOUT_SECONDS si la charge est normale.",
  "error": "StageTimeoutError",
  "stage": "embed",
  "timeout_seconds": 30
}
```

| Étape | Mécanisme | Ce qui se passe au-delà du budget |
|---|---|---|
| `embed` | l'appel tourne dans un pool de threads dédié, attendu avec un délai (`run_with_timeout`) | la requête répond 504 tout de suite ; le calcul en cours se termine en arrière-plan (un thread Python ne s'interrompt pas). Le pool (4 threads) borne le nombre de calculs orphelins |
| `retrieval` | `statement_timeout` Postgres posé pour la seule requête de recherche, puis restauré | Postgres annule la requête (SQLSTATE 57014) : rien ne continue côté base |
| `generation` | délai de lecture HTTP vers Ollama ; en streaming, budget **total** vérifié entre deux tokens | la connexion à Ollama est fermée |

Les réglages de `statement_timeout` sont hors de la mesure `timings_ms.retrieval`
pour que la latence reste comparable à la baseline 9.1.

## Identifiant de corrélation : `X-Request-ID`

- Si l'appelant envoie `X-Request-ID` (1 à 128 caractères parmi
  `A-Z a-z 0-9 . _ : -`), il est réutilisé ; sinon l'API en génère un
  (UUID hexadécimal). Une valeur non conforme est remplacée, pour éviter
  l'injection dans les logs.
- L'identifiant est renvoyé dans l'en-tête `X-Request-ID` de **toutes** les
  réponses, y compris 401, 429 et les flux SSE (exposé au navigateur via CORS).
- Il est stocké dans une `ContextVar` (`raglab.logging_utils.request_id_var`) :
  toutes les lignes de log émises pendant la requête le portent, y compris
  celles émises dans le pool de threads de FastAPI, dans le générateur SSE et
  dans le thread d'embedding (le contexte y est copié).
- Une ligne d'accès `http.request` (méthode, chemin, statut, durée) est émise
  à la fin de chaque requête.

Avec `RAGLAB_LOG_FORMAT=json` :

```json
{"timestamp": "2026-11-02T10:31:07.412Z", "level": "INFO", "logger": "raglab.retrieval.service", "message": "query.completed", "service": "raglab", "environment": "prod", "request_id": "3f9c0d6a6c1e4bb0a3f1f0f1d1f3e2aa", "event": "query.completed", "context": {"timings_ms": {"embed": 41.2, "retrieval": 18.7, "generation": 2875.1}, "...": "..."}}
{"timestamp": "2026-11-02T10:31:07.413Z", "level": "INFO", "logger": "raglab.api.access", "message": "http.request", "request_id": "3f9c0d6a6c1e4bb0a3f1f0f1d1f3e2aa", "event": "http.request", "context": {"method": "POST", "path": "/api/query", "status": 200, "duration_ms": 2941.6}}
```

En format texte, l'identifiant est ajouté en fin de ligne (`request_id=...`).

## Clé d'API

- `RAGLAB_API_KEY` vide (défaut) : authentification désactivée.
- `RAGLAB_API_KEY` renseignée : chaque requête doit envoyer
  `X-API-Key: <clé>` (ou `Authorization: Bearer <clé>`), sinon **401** avec
  `WWW-Authenticate`. La comparaison est à temps constant (`hmac.compare_digest`).
- Toujours accessibles sans clé : `/health`, `/ready`, `/docs`, `/redoc`,
  `/openapi.json` et les requêtes `OPTIONS` (préflight CORS).
- Frontend : bouton **Clé d'API** dans la barre du haut ; la clé est gardée
  dans le `localStorage` du navigateur et envoyée sur tous les appels, y
  compris le flux SSE. Pour un déploiement figé, `VITE_API_KEY` au build sert
  de valeur par défaut (elle est alors lisible dans le bundle : à réserver à
  un réseau de confiance).

Il s'agit d'une clé partagée unique, adaptée à un service interne ou à une
démo. Plusieurs clés, des rôles ou de l'OAuth relèveraient d'un reverse proxy
ou d'une passerelle d'API.

## Limitation de débit

- `RAGLAB_API_RATE_LIMIT_REQUESTS=120` et
  `RAGLAB_API_RATE_LIMIT_WINDOW_SECONDS=60` : 120 requêtes par fenêtre
  glissante de 60 s.
- Compté par clé d'API quand l'authentification est active (la clé est
  hachée, jamais journalisée), sinon par adresse IP du client. Une mauvaise
  clé est rejetée en 401 avant de consommer le quota.
- Au-delà : **429** avec `Retry-After` (secondes, arrondi au supérieur) et le
  même délai dans le corps (`retry_after`).
- `/health` et `/ready` ne sont jamais limités, pour ne pas faire échouer les
  sondes d'un orchestrateur.

Limites assumées : l'état est en mémoire, dans le processus. Avec plusieurs
workers uvicorn, chaque worker compte de son côté (limite effective
multipliée par le nombre de workers) ; derrière un reverse proxy, lancer
uvicorn avec `--proxy-headers --forwarded-allow-ips=<ip du proxy>` pour que
l'IP comptée soit celle du client et non celle du proxy. Une limite partagée
entre plusieurs nœuds demanderait un Redis, donc un nouveau service : hors
périmètre.

## Santé : `/health`, `/ready`, `/api/health`

| Route | Rôle | Dépendances interrogées | Codes |
|---|---|---|---|
| `GET /health` | *liveness* : le processus répond | aucune | 200 `{"status": "ok"}` |
| `GET /ready` | *readiness* : prêt à répondre à une question | Postgres (`SELECT 1`), Ollama (`/api/tags`, délai `RAGLAB_READY_TIMEOUT_SECONDS`), modèle de génération par défaut installé | 200 `ready` / 503 `not_ready` |
| `GET /api/health` | tableau de bord de l'interface | Postgres, Ollama, Neo4j | toujours 200, `status` `ok` / `degraded` |

`/health` ne touche volontairement à aucune dépendance : un orchestrateur qui
redémarrerait l'API parce que Postgres est indisponible n'arrangerait rien.
Neo4j n'entre pas dans `/ready` car il ne sert qu'aux pages graphe.

```jsonc
// GET /ready -> 503
{"status": "not_ready", "checks": {"postgres": "ok", "ollama": "ok", "default_generation_model": "missing"}, "default_generation_model": "qwen2.5:7b"}
```

Exemple de sonde Docker Compose (non activée dans `docker-compose.yml`) :

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')"]
  interval: 15s
  timeout: 5s
  retries: 3
```

## Erreurs Ollama typées

Les appels à Ollama (`OllamaGenerator`, `OllamaService`) traduisent les échecs
en exceptions typées (`src/raglab/ollama/errors.py`), rendues par un
gestionnaire unique (`src/raglab/api/errors.py`), le même que pour
l'événement SSE `error` :

| Situation | Exception | HTTP | Message |
|---|---|---|---|
| Modèle absent (404 Ollama, ou `error` dans le flux) | `OllamaModelNotFoundError` | **424** | actionnable : `raglab ollama pull --model <modèle>` ou page Ollama |
| Mémoire (V)RAM insuffisante (`requires more system memory`, `CUDA error: out of memory`, `cudaMalloc failed`...) | `OllamaOutOfMemoryError` | **503** + `Retry-After` | un autre modèle occupe probablement le GPU |
| Connexion refusée, DNS, délai de connexion | `OllamaUnreachableError` | **502** | URL Ollama et commande pour démarrer le service |
| Pas de réponse dans le budget de génération | `OllamaTimeoutError` | **504** | `stage: "generation"` |
| Autre erreur renvoyée par Ollama | `OllamaError` | **502** | message d'Ollama dans `cause` |

Pourquoi **424** pour un modèle absent : réessayer ne servira à rien tant que
le modèle n'est pas téléchargé, alors qu'un **503** inviterait un client ou un
répartiteur de charge à réessayer. Le **503** est réservé à la saturation
mémoire, qui est transitoire (le budget GPU de 8 Go est partagé avec les
modèles llama.cpp, cf. `CLAUDE.md`).

Toutes les erreurs ont la forme `{"detail": "...", "error": "<Type>", "cause": "<message brut>"}`.
Les exceptions typées héritent de `RuntimeError` : le code existant qui
attrapait `RuntimeError` pour un modèle manquant continue de fonctionner.

## Collecte des sources officielles : `/api/sources`

Le Code de la consommation ([corpus-legi.md](corpus-legi.md)) et les actes
européens de conformité ([corpus-eurlex.md](corpus-eurlex.md)) se collectent
sans la ligne de commande. La collecte est longue (un `git clone --bare` puis
la lecture de l'historique ; une soixantaine de requêtes CELLAR à une par
seconde) : elle tourne en **tâche de fond** dans le processus de l'API, et
l'interface interroge son état.

| Endpoint | Rôle |
|---|---|
| `GET /api/sources` | état des deux sources (`legi`, `eurlex`) |
| `POST /api/sources/{legi\|eurlex}/fetch` | lance la tâche, répond **202** tout de suite ; corps optionnel `{"ingest": false}` pour n'écrire que les fichiers |
| `GET /api/sources/{legi\|eurlex}/status` | état, étape, progression, dernière erreur, résultat |

Une tâche enchaîne trois étapes :

1. `fetch` : la collecte, celle de `raglab legifrance fetch --code consommation`
   ou `raglab eurlex fetch`, dans les dossiers du benchmark
   (`data/legifrance/consommation/`, `data/eurlex/compliance/`). La
   progression compte les versions d'articles (Légifrance) ou les documents
   CELLAR (EUR-Lex), en cache compris.
2. `verify` : comparaison au manifeste figé du benchmark
   (`benchmarks/<suite>/corpus_manifest.json`). Un écart n'arrête pas la
   tâche ; il est rapporté (`result.manifest.problems`), car le benchmark
   refusera ce corpus.
3. `ingest` : ingestion dans `bench_legi_consommation_fr` ou
   `bench_eurlex_compliance`, avec la même description que le benchmark, qui
   retrouve donc les documents sans les réingérer. **Pas d'indexation** :
   les embeddings sont l'étape Vectorisation de l'Atelier, la collecte ne
   touche jamais le GPU.

```json
{
  "source": "legi",
  "corpus": "bench_legi_consommation_fr",
  "state": "running",
  "stage": "fetch",
  "progress": {"done": 3000, "total": 5998},
  "started_at": "2026-11-03T10:12:00Z",
  "finished_at": null,
  "error": null,
  "result": null,
  "command": "raglab legifrance fetch --code consommation"
}
```

`state` vaut `idle`, `running`, `succeeded` ou `failed`. Une seule tâche par
source à la fois : un second `POST` pendant qu'elle tourne répond **409**
(`SourceBusyError`). Une source inconnue répond 404.

Les erreurs passent par `describe_error`, comme celles des routes ; le corps
est rangé dans `error` avec son code HTTP (`status_code`) :

| Situation | `error` | `status_code` |
|---|---|---|
| Dépôt git ou CELLAR injoignable, `git` en échec | `SourceFetchError` (`source`, `cause` = message brut ou stderr de git) | 502 |
| Budget de la tâche dépassé (`RAGLAB_SOURCE_FETCH_TIMEOUT_SECONDS`) | `StageTimeoutError`, `stage` = étape en cours | 504 |
| Appel git bloqué (`RAGLAB_LEGIFRANCE_GIT_TIMEOUT_SECONDS`) | `StageTimeoutError`, `stage=fetch` | 504 |

Le budget de la tâche est vérifié à chaque pas de progression et entre les
étapes : une requête CELLAR en cours finit avant l'arrêt (au plus
`RAGLAB_EURLEX_REQUEST_TIMEOUT_SECONDS`). Les lignes de log
(`sources.fetch.started`, `.completed`, `.failed`) portent le `request_id` du
`POST` qui a lancé la tâche.

L'état vit en mémoire : il est perdu au redémarrage de l'API (les fichiers et
le corpus ingéré restent), et chaque worker uvicorn a le sien, ce qui suppose
un seul worker, la configuration du lab. En ligne de commande, la même tâche
s'exécute au premier plan :

```bash
raglab sources list
raglab sources fetch legi             # collecte puis ingestion
raglab sources fetch eurlex --no-ingest
```

## Fournisseurs LLM (Ollama, llama.cpp, vLLM)

La génération de la réponse (`/api/query`, `/api/query/stream`,
`raglab query`) peut passer par Ollama (défaut) ou par un serveur compatible
OpenAI : `llama-server` (llama.cpp) ou vLLM. Le prompt
(`build_prompt_bundle`), la température (`RAGLAB_GENERATION_TEMPERATURE`), le
budget `RAGLAB_GENERATION_TIMEOUT_SECONDS` (sur toute la réponse, en flux ou
non) et la réponse « contexte insuffisant » sont les mêmes quel que soit le
fournisseur (`OllamaGenerator` / `OpenAICompatGenerator`,
`src/raglab/generation/service.py`).

| Variable | Défaut | Rôle |
|---|---|---|
| `RAGLAB_LLM_PROVIDERS` | `ollama` | fournisseurs proposés, séparés par des virgules, parmi `ollama`, `llamacpp`, `vllm` |
| `RAGLAB_DEFAULT_LLM_PROVIDER` | `ollama` | fournisseur d'une requête qui n'en précise pas ; doit figurer dans la liste |
| `RAGLAB_LLAMACPP_BASE_URL` | `http://127.0.0.1:8080/v1` | serveur llama.cpp (déjà utilisé par les benchmarks) |
| `RAGLAB_LLAMACPP_API_KEY` | vide | envoyée en `Authorization: Bearer` si renseignée (`llama-server --api-key`) |
| `RAGLAB_VLLM_BASE_URL` | `http://127.0.0.1:8001/v1` | serveur vLLM |
| `RAGLAB_VLLM_API_KEY` | vide | idem pour vLLM (`vllm serve --api-key`) |

Un nom inconnu dans `RAGLAB_LLM_PROVIDERS`, une liste vide ou un fournisseur
par défaut absent de la liste font échouer le démarrage : une faute de frappe
ne retombe pas en silence sur Ollama. Les clés ne sont jamais journalisées ni
renvoyées par l'API.

**Choisir le fournisseur.** `QueryRequest` accepte `llm_provider`
(`null` = défaut) à côté de `llm_model` ; la CLI prend `--provider` et
`--model` (alias de `--llm-model`). Sans modèle, Ollama utilise
`RAGLAB_GENERATION_MODEL` et un serveur compatible OpenAI le premier modèle
listé par `GET <base>/models` (sinon le champ `model` est omis et
llama-server répond avec son modèle chargé). L'étape `generation` du mode
pédagogique porte `data: {"provider", "model"}`.

**Lister les modèles : `GET /api/llm/models`.** Seuls les fournisseurs
actifs sont listés, dans l'ordre de `RAGLAB_LLM_PROVIDERS`, sondés en
parallèle avec `RAGLAB_READY_TIMEOUT_SECONDS` chacun. Un serveur injoignable
n'échoue pas l'appel : il apparaît avec `available: false` et une erreur
courte (`unreachable`, `timeout`, `http 401`...).

```json
{
  "default_provider": "ollama",
  "default_model": "qwen2.5:7b",
  "providers": [
    {"name": "ollama", "label": "Ollama", "kind": "ollama", "base_url": "http://localhost:11434",
     "available": true, "error": null, "models": ["qwen2.5:7b"], "default_model": "qwen2.5:7b"},
    {"name": "llamacpp", "label": "llama.cpp", "kind": "openai", "base_url": "http://127.0.0.1:8080/v1",
     "available": false, "error": "unreachable", "models": [], "default_model": null}
  ]
}
```

`GET /api/config` expose aussi `llm_providers`, `default_llm_provider` et
`citation_resolver`.

**Erreurs.** Typées dans `src/raglab/llm/errors.py` et rendues par le même
`describe_error` que les erreurs Ollama (réponse HTTP ou événement SSE
`error`), avec un champ `provider` en plus :

| Situation | Exception | HTTP |
|---|---|---|
| Fournisseur inconnu ou désactivé | `UnknownLLMProviderError` | **400**, avant la recherche (et avant l'ouverture du flux SSE) |
| Modèle non servi (404 « model ... does not exist ») | `LLMProviderModelNotFoundError` | **424** |
| Connexion refusée, DNS, délai de connexion | `LLMProviderUnreachableError` | **502** |
| Pas de réponse dans le budget | `LLMProviderTimeoutError` | **504**, `stage: "generation"` |
| Autre erreur HTTP ou `error` dans le flux | `LLMProviderError` | **502**, message du serveur dans `cause` |

**GPU (8 Go).** Ollama et llama.cpp ne tiennent jamais le GPU en même temps.
Pour une requête interactive, raglab ne **démarre pas** llama-server (des
dizaines de secondes de chargement) : il utilise un serveur déjà lancé, sinon
502. Avant chaque réponse llama.cpp, il demande à Ollama de décharger ses
modèles (`keep_alive: 0`, même aide que `LocalLLMServer`) ; une requête
Ollama suivante rechargera qwen2.5, ce qui peut échouer en 503 tant que
llama-server occupe la mémoire. vLLM est supposé tourner sur une autre
machine ou un autre GPU : rien n'est déchargé pour lui. Les benchmarks
continuent de passer par `LocalLLMServer`, qui démarre et arrête llama-server.

## Mesures

Reproductibles sans GPU ni base :

```bash
PYTHONPATH=src python scripts/bench_api_hardening.py
```

**Streaming** (serveur uvicorn réel, recherche et Ollama remplacés par des
faux de vitesse connue : recherche 60 ms, préremplissage 300 ms, 120 tokens à
40 tokens/s, ordre de grandeur de qwen2.5:7b sur 8 Go ; médiane de 10
exécutions) :

| Mesure | ms |
|---|---:|
| `/api/query` : réponse JSON complète | 3 381 |
| `/api/query/stream` : événement `retrieval` (sources affichables) | **65** |
| `/api/query/stream` : premier `token` | **366** |
| `/api/query/stream` : événement `done` | 3 484 |

L'utilisateur voit les sources ~52 fois plus tôt et le début de la réponse
~9 fois plus tôt. Le premier token arrive au préremplissage près (300 ms) :
le flux n'ajoute que quelques millisecondes. Le temps total est légèrement
plus long (+3 %, envoi de 120 événements) ; il n'est pas ce que perçoit
l'utilisateur.

**Coût des middlewares** (route asynchrone triviale, application ASGI
appelée directement sans client HTTP, 20 000 requêtes par variante,
variantes entrelacées sur 10 tours, µs) :

| Pile | Médiane | p95 | Écart médiane |
|---|---:|---:|---:|
| sans (CORS seul, état 9.1) | 134 | 191 | — |
| + request id et ligne d'accès | 270 | 425 | +136 |
| + clé et limite (désactivées, défaut) | 291 | 462 | +157 |
| + clé et limite (actives) | 294 | 475 | +160 |

Environ 0,16 ms par requête, dont ~72 µs pour formater et écrire la ligne
d'accès JSON (mesuré seul) : négligeable devant une requête RAG (embedding
~40 ms, génération en secondes). La vérification de clé et le comptage du
débit coûtent quelques microsecondes.

Le temps jusqu'au premier token réel (préremplissage de qwen2.5:7b sur la
RTX 8 Go) sera mesuré avec Ollama lors d'une session GPU dédiée ; le
chiffre ci-dessus ne mesure que ce que l'API ajoute ou retire.

## Ce qui reste pour la phase 9.5

- Migrations Alembic : prévues au périmètre 9.5 dans la feuille de route,
  elles arrivent avec la phase 9.2 (branche `feature/hybrid-retrieval` :
  `src/raglab/db/migrations/`, révision de base `0001_baseline`, appliquées
  par `raglab db init`). Cette PR ne change pas le schéma et n'ajoute aucune
  migration ; une évolution future se chaînera après la dernière révision.
- Limitation de débit partagée entre workers / nœuds (Redis) si l'API est un
  jour déployée sur plusieurs instances.
