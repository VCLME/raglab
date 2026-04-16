from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from raglab.config import get_settings
from raglab.db import initialize_database, session_scope
from raglab.domain.enums import ChunkingStrategy
from raglab.experiments.recall import RecallBenchmarkService
from raglab.experiments.service import ExperimentService
from raglab.indexing.service import IndexingService
from raglab.ingestion.service import IngestionService
from raglab.lexml import getDataFromLexML
from raglab.retrieval.filters import build_retrieval_filters
from raglab.retrieval.service import QueryService

app = typer.Typer(no_args_is_help=True, help="RAG local oriente experimentation.")
db_app = typer.Typer(no_args_is_help=True, help="Commandes base de donnees.")
experiment_app = typer.Typer(no_args_is_help=True, help="Commandes d'experimentation.")
lexml_app = typer.Typer(no_args_is_help=True, help="Collecte LexML Brasil.")

app.add_typer(db_app, name="db")
app.add_typer(experiment_app, name="experiment")
app.add_typer(lexml_app, name="lexml")


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(message)s", force=True)


@db_app.command("init")
def db_init() -> None:
    initialize_database()
    typer.echo("Base initialisee avec pgvector.")


@app.command()
def ingest(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    corpus: str = typer.Option(get_settings().default_corpus_name, "--corpus", help="Nom du corpus cible."),
    description: str | None = typer.Option(None, "--description", help="Description optionnelle du corpus."),
    tags: list[str] | None = typer.Option(None, "--tag", help="Tag a appliquer a tous les documents ingeres."),
) -> None:
    with session_scope() as session:
        service = IngestionService(session)
        summary = service.ingest_folder(folder, corpus_name=corpus, description=description, tags=tags)
    typer.echo(json.dumps({"corpus": corpus, **summary}, indent=2, ensure_ascii=False))


@lexml_app.command("get-data")
def lexml_get_data(
    output_dir: Path = typer.Option(
        get_settings().lexml_documents_dir,
        "--output-dir",
        help="Dossier de sortie pour les documents LexML.",
    ),
    page_limit: int | None = typer.Option(
        None,
        "--page-limit",
        help="Nombre maximum de pages de resultats LexML a collecter. Par defaut, le run s'arrete seulement sur fin des resultats, erreur reseau ou limite 2GB.",
    ),
) -> None:
    _configure_logging()
    result = getDataFromLexML(output_dir=output_dir, page_limit=page_limit)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@lexml_app.command("ingest")
def lexml_ingest(
    corpus: str = typer.Option("lexml", "--corpus", help="Corpus cible pour les donnees LexML."),
    description: str | None = typer.Option("Corpus legal collecte depuis LexML Brasil.", "--description"),
    folder: Path = typer.Option(
        get_settings().lexml_documents_dir,
        "--folder",
        help="Dossier local contenant les fichiers LexML deja collectes.",
    ),
    tags: list[str] | None = typer.Option(None, "--tag", help="Tag a appliquer a tous les documents LexML ingeres."),
) -> None:
    with session_scope() as session:
        service = IngestionService(session)
        summary = service.ingest_folder(folder, corpus_name=corpus, description=description, tags=tags)
    typer.echo(json.dumps({"corpus": corpus, **summary}, indent=2, ensure_ascii=False))


@app.command()
def index(
    corpus: str = typer.Option(..., "--corpus", help="Corpus a indexer."),
    strategy: ChunkingStrategy = typer.Option(..., "--strategy", help="Strategie de chunking."),
    run_name: str | None = typer.Option(None, "--run-name", help="Nom explicite du run d'indexation."),
    embedding_provider: str | None = typer.Option(
        None,
        "--embedding-provider",
        help="Override du provider d'embeddings pour ce run.",
    ),
    embedding_model: str | None = typer.Option(
        None,
        "--embedding-model",
        help="Override du modele d'embeddings pour ce run.",
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental/--full",
        help="Reutiliser les chunks/embeddings du dernier run compatible pour les documents inchanges.",
    ),
) -> None:
    with session_scope() as session:
        service = IndexingService(session)
        result = service.index_corpus(
            corpus_name=corpus,
            strategy=strategy,
            run_name=run_name,
            embedding_provider=embedding_provider,
            embedding_model_name=embedding_model,
            incremental=incremental,
        )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def query(
    question: str = typer.Argument(..., help="Question utilisateur."),
    corpus: str | None = typer.Option(None, "--corpus", help="Corpus a interroger."),
    strategy: ChunkingStrategy | None = typer.Option(None, "--strategy", help="Strategie de chunking a cibler."),
    index_run_id: str | None = typer.Option(None, "--index-run-id", help="Run d'indexation explicite."),
    top_k: int | None = typer.Option(None, "--top-k", help="Nombre de chunks a recuperer."),
    generate: bool = typer.Option(True, "--generate/--no-generate", help="Activer la generation finale."),
    document_ids: list[str] | None = typer.Option(None, "--document-id", help="Limiter a un ou plusieurs documents."),
    file_names: list[str] | None = typer.Option(None, "--file-name", help="Limiter a un ou plusieurs noms de fichier."),
    source_path_contains: str | None = typer.Option(
        None,
        "--source-path-contains",
        help="Limiter aux documents dont le chemin contient cette valeur.",
    ),
    tags: list[str] | None = typer.Option(None, "--tag", help="Limiter aux documents portant ces tags."),
    metadata_equals: list[str] | None = typer.Option(
        None,
        "--metadata-eq",
        help="Filtre metadata exact, repetable, au format cle=valeur.",
    ),
) -> None:
    filters = build_retrieval_filters(
        document_ids=document_ids,
        file_names=file_names,
        source_path_contains=source_path_contains,
        tags=tags,
        metadata_equals=metadata_equals,
    )
    with session_scope() as session:
        service = QueryService(session)
        response = service.query(
            question=question,
            corpus_name=corpus,
            strategy=strategy,
            index_run_id=index_run_id,
            top_k=top_k,
            generate_answer=generate,
            filters=filters,
        )
    typer.echo(response.model_dump_json(indent=2))


@experiment_app.command("run")
def experiment_run(
    dataset_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Dataset JSONL."),
    corpus: str = typer.Option(..., "--corpus", help="Corpus a evaluer."),
    strategy: list[ChunkingStrategy] = typer.Option(
        [
            ChunkingStrategy.TRADITIONAL,
            ChunkingStrategy.SLIDE,
            ChunkingStrategy.LATE,
        ],
        "--strategy",
        help="Repeter l'option pour choisir les strategies a comparer.",
    ),
    top_k: int | None = typer.Option(None, "--top-k", help="Top-k de retrieval."),
    generate: bool = typer.Option(True, "--generate/--no-generate", help="Activer la generation."),
    name: str = typer.Option("chunking-benchmark", "--name", help="Nom du benchmark."),
) -> None:
    with session_scope() as session:
        service = ExperimentService(session)
        result = service.run(
            dataset_path=dataset_path,
            corpus_name=corpus,
            strategies=strategy,
            top_k=top_k,
            generate_answers=generate,
            name=name,
        )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@experiment_app.command("recall")
def experiment_recall(
    corpus: str = typer.Option(..., "--corpus", help="Corpus a evaluer."),
    strategy: ChunkingStrategy = typer.Option(..., "--strategy", help="Strategie de retrieval a evaluer."),
    dataset_path: Path | None = typer.Option(
        None,
        "--dataset-path",
        exists=True,
        dir_okay=False,
        help="Dataset Recall JSONL. Si absent, il est genere depuis les metadata LexML locales.",
    ),
    lexml_documents_dir: Path = typer.Option(
        get_settings().lexml_documents_dir,
        "--lexml-documents-dir",
        help="Dossier LexML utilise pour generer le dataset Recall par defaut.",
    ),
    case_limit: int = typer.Option(10, "--case-limit", min=1, help="Nombre max de cas si generation auto."),
) -> None:
    with session_scope() as session:
        service = RecallBenchmarkService(session)
        result = service.run(
            corpus_name=corpus,
            strategy=strategy,
            dataset_path=dataset_path,
            lexml_documents_dir=lexml_documents_dir,
            case_limit=case_limit,
        )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
