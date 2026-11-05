# Modèle de données

## 1. Vue conceptuelle

Le modèle sépare cinq niveaux :

1. corpus
2. documents sources
3. runs d’indexation
4. chunks et embeddings
5. runs d’expérimentation

## 2. Entités principales

### `corpora`

Représente un ensemble logique de documents.

Champs principaux :

- `id`
- `name`
- `description`
- `root_path`
- `created_at`

### `documents`

Document source ingéré.

Champs principaux :

- `id`
- `corpus_id`
- `source_path`
- `file_name`
- `extension`
- `checksum`
- `mime_type`
- `content`
- `char_count`
- `metadata_json`
- `created_at`
- `updated_at`

### `embedding_spaces`

Décrit l’espace vectoriel utilisé.

Champs principaux :

- `id`
- `name`
- `provider`
- `model_name`
- `dimension`
- `distance_metric`
- `query_prefix`
- `passage_prefix`
- `is_default`
- `created_at`

### `index_runs`

Versionne une indexation précise.

Champs principaux :

- `id`
- `corpus_id`
- `name`
- `strategy`
- `embedding_space_id`
- `chunk_size`
- `chunk_overlap`
- `slide_stride`
- `late_context_chars`
- `status`
- `config_json`
- `started_at`
- `completed_at`

### `chunks`

Unités de récupération liées à un `index_run`.

Champs principaux :

- `id`
- `index_run_id`
- `document_id`
- `chunk_order`
- `text`
- `char_start`
- `char_end`
- `token_estimate`
- `metadata_json`
- `lexical_tsv` : `tsvector` du texte pour la recherche BM25 (index GIN), configuration choisie selon la langue du document ou du corpus
- `lexical_length` : nombre de tokens du chunk (|d| de BM25)
- `created_at`

### `lexical_index_stats` et `lexical_term_stats`

Statistiques BM25 par `index_run` : `doc_count`, `avg_length`, `ts_configs` d'une part, `doc_freq` par lexème d'autre part. Voir [retrieval-hybrid.md](retrieval-hybrid.md).

### `chunk_embeddings`

Embeddings associés aux chunks.

Champs principaux :

- `id`
- `chunk_id`
- `embedding_space_id`
- `embedding`
- `created_at`

### `experiment_runs`

Trace un benchmark ou une comparaison.

Champs principaux :

- `id`
- `name`
- `dataset_path`
- `strategies`
- `status`
- `config_json`
- `started_at`
- `completed_at`

### `experiment_results`

Résultat d’un cas de test pour une stratégie ou un `index_run`.

Champs principaux :

- `id`
- `experiment_run_id`
- `case_id`
- `question`
- `index_run_id`
- `retrieved_chunk_ids`
- `answer`
- `metrics_json`
- `created_at`

### `conversations` et `messages`

Historique des conversations du Chat et de la CLI (migration `0003_conversations`), écrit seulement avec `RAGLAB_CONVERSATION_HISTORY=true`. Un message par échange : question, réponse, statut, passages retrouvés avec leurs offsets et s'ils sont cités, contexte présenté au rédacteur, options résolues, fournisseur et modèle, durées, `request_id`, et un `tsvector` (index GIN) pour la recherche plein texte. Détails, API, CLI et conservation : [historique.md](historique.md).

### `runtime_settings`

Réglages basculés à l'exécution (Atelier, API, CLI) par-dessus leur variable `RAGLAB_*` : `key`, `value` (JSON), `updated_by`, `updated_at`. Aujourd'hui une clé, `conversation_history`. Migration `0003_conversations`.

## 3. Relations

```text
corpora 1---n documents
corpora 1---n index_runs
embedding_spaces 1---n index_runs
documents 1---n chunks
index_runs 1---n chunks
chunks 1---1..n chunk_embeddings
experiment_runs 1---n experiment_results
index_runs 1---n experiment_results
conversations 1---n messages
```

## 4. Décision MVP sur les embeddings

Le MVP prépare le support multi-modèles via `embedding_spaces`.

Choix pragmatique d’implémentation :

- un espace d’embeddings de référence est utilisé par défaut
- la base est structurée pour suivre plusieurs espaces, avec des provider / modèle / dimension différents
- la colonne `chunk_embeddings.embedding` est stockée en `vector` variable (pgvector ≥ 0.7) : plusieurs dimensions coexistent dans la même table
- un index HNSW partiel par dimension est créé à la volée au moment de l’indexation via `raglab.db.indexes.ensure_partial_hnsw_index`, avec le prédicat `WHERE vector_dims(embedding) = N` pour que le planner l’utilise
- la recherche ajoute explicitement le cast `embedding::vector(N)` et le filtre `vector_dims(embedding) = N` pour matcher l’index partiel (voir `src/raglab/stores/vector/postgres.py`)

Conséquence :

- l'interface métier est compatible multi-modèles et multi-dimensions sans schéma séparé
- changer d'`embedding_model_name` entre deux `index_run` pour un même corpus est supporté, chaque run pointe vers son propre `embedding_space` avec sa dimension réelle
- la variable `RAGLAB_EMBEDDING_DIMENSION` ne joue plus que comme défaut logique pour créer un nouvel `embedding_space` quand elle n'est pas déduite du modèle ; elle ne contraint plus la colonne

### Probe automatique de la dimension à l'indexation

`IndexingService.index_corpus` ([src/raglab/indexing/service.py](../src/raglab/indexing/service.py)) résout la dimension à utiliser dans cet ordre :

1. Si un `embedding_space` existe déjà pour la paire `(provider, model_name)` → utilise sa `dimension` enregistrée (autorité métadonnée)
2. Sinon → construit l'embedder et appelle `embed_query("dimension probe")` pour mesurer la dimension réellement produite par le modèle
3. L'`embedding_space` est créé avec cette dimension probée, l'`index HNSW partiel` correspondant est garanti par `ensure_partial_hnsw_index(session, dim)`

Cela évite la dérive quand l'utilisateur change `embedding_model_name` sans toucher à `RAGLAB_EMBEDDING_DIMENSION`.

### Migrations (Alembic)

Le schéma est versionné par Alembic ([src/raglab/db/migrations](../src/raglab/db/migrations)). `initialize_database()` ([src/raglab/db/init_db.py](../src/raglab/db/init_db.py)), appelé par `raglab db init`, délègue à `upgrade_database` ([src/raglab/db/migrate.py](../src/raglab/db/migrate.py)) :

- base vide : `upgrade head` depuis `0001_baseline` ;
- base créée avant Alembic (tables présentes, pas de table `alembic_version`) : application des deux correctifs ci-dessous, estampille `0001_baseline`, puis `upgrade head` ;
- base déjà sous Alembic : `upgrade head`.

Les deux correctifs, idempotents, restent dans [src/raglab/db/indexes.py](../src/raglab/db/indexes.py) :

1. `migrate_chunk_embeddings_to_variable_dim` : si la colonne `embedding` est encore `vector(N)` (legacy), l'ALTER vers `vector`, supprime l'ancien index HNSW fixe et crée les index partiels pour toutes les dimensions déjà présentes
2. `reconcile_embedding_space_dimensions` : pour chaque `embedding_space`, échantillonne une ligne `chunk_embeddings` et met à jour `dimension` si divergence. Crée aussi le partial HNSW manquant. C'est le filet de sécurité contre les bases créées avec un `RAGLAB_EMBEDDING_DIMENSION` faux.

Pour une nouvelle révision : `alembic -c alembic.ini revision -m "..."` (la connexion vient de `RAGLAB_DATABASE_URL`).

## 5. Préparation Neo4j

Le modèle relationnel ne remplace pas le graphe futur.

Il prépare simplement :

- des identifiants stables de documents et chunks
- une séparation claire entre stockage dense et couche de connaissances

Dans la phase Neo4j, on pourra ajouter :

- `entities`
- `relations`
- `chunk_entity_links`

ou projeter ces objets directement dans Neo4j en gardant PostgreSQL comme source transactionnelle.

## 6. Index recommandés

### Relationnels

- index unique sur `corpora.name`
- index unique sur `documents.source_path`
- index sur `documents.corpus_id`
- index sur `chunks.index_run_id`
- index sur `chunks.document_id`
- index sur `chunk_embeddings.embedding_space_id`
- index GIN sur `chunks.lexical_tsv` (recherche BM25)

### Vectoriels

- colonne `chunk_embeddings.embedding` de type `vector` (sans dimension fixe)
- un index HNSW **partiel par dimension** créé à la volée lors de l'indexation, par exemple :
  ```
  CREATE INDEX ix_chunk_embeddings_hnsw_384
  ON chunk_embeddings USING hnsw ((embedding::vector(384)) vector_cosine_ops)
  WITH (m=16, ef_construction=64)
  WHERE vector_dims(embedding) = 384;
  ```
- la requête de retrieval ajoute `AND vector_dims(embedding) = :dim` et `ORDER BY embedding::vector(:dim) <=> :query_vec` pour que le planner utilise le partial HNSW de la bonne dimension
- distance cosine par défaut (`vector_cosine_ops`)

## 7. Règles métier importantes

- un `index_run` est immutable une fois terminé
- un chunk appartient à un seul `index_run`
- une requête doit utiliser le même espace d’embeddings que celui de l’index
- les expériences doivent référencer explicitement les `index_runs`
