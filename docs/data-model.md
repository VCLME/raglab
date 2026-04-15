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
- `created_at`

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
```

## 4. Décision MVP sur les embeddings

Le MVP prépare le support multi-modèles via `embedding_spaces`.

Choix pragmatique d’implémentation :

- un espace d’embeddings de référence est utilisé par défaut
- la base est structurée pour suivre plusieurs espaces
- la stratégie la plus simple pour la V1 reste d’utiliser une dimension active homogène par instance de projet

Conséquence :

- l’interface métier est prête pour plusieurs modèles
- une évolution future pourra gérer plusieurs dimensions simultanées avec des index partiels ou des tables dédiées

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

### Vectoriels

- index HNSW sur `chunk_embeddings.embedding`
- distance cosine pour le MVP

## 7. Règles métier importantes

- un `index_run` est immutable une fois terminé
- un chunk appartient à un seul `index_run`
- une requête doit utiliser le même espace d’embeddings que celui de l’index
- les expériences doivent référencer explicitement les `index_runs`
