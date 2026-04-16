# Roadmap

## Phase 0 - Cadrage

- architecture documentée
- choix techniques explicités
- modèle de données défini
- plan d’expérimentation cadré

## Phase 1 - Socle exécutable

- Docker Compose pour PostgreSQL + pgvector + Ollama
- configuration centralisée
- initialisation de la base
- CLI opérationnelle
- ingestion `.txt`, `.pdf`, `.docx`

## Phase 2 - Baseline RAG

- chunking `traditional`
- indexation complète
- retrieval pgvector
- génération via Ollama
- tests unitaires de base

## Phase 3 - Expérimentation chunking

- ajout du `slide chunking`
- ajout du `late chunking` contextualisé
- runner d’expérimentation
- rapport JSON comparatif

## Phase 4 - Qualité et optimisation

- filtres par corpus / document / tags / metadata sidecar
- prompts plus robustes
- métriques supplémentaires de retrieval (`Recall@K`, `Precision@K`, `MRR`)
- logs structurés
- meilleure gestion de réindexation incrémentale

## Phase 5 - Embeddings multi-providers

- provider Ollama embeddings
- comparaison multi-modèles
- gestion plus avancée des espaces d’embeddings
- éventuelle prise en charge de dimensions hétérogènes

## Phase 6 - Extension graphe

- interface `GraphStore`
- extraction entités / relations
- branchement Neo4j
- requêtes hybrides vectorielles + graphe

## Phase 7 - Industrialisation légère

- API HTTP
- migrations Alembic
- observabilité
- jeux d’évaluation plus riches
- packaging et documentation d’exploitation
