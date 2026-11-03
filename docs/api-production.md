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
