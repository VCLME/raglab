from __future__ import annotations

import json
from pathlib import Path

import typer

from raglab.config import get_settings
from raglab.db import initialize_database, session_scope
from raglab.domain.enums import ChunkingStrategy
from raglab.experiments.service import ExperimentService
from raglab.indexing.service import IndexingService
from raglab.ingestion.service import IngestionService
from raglab.retrieval.service import QueryService

app = typer.Typer(no_args_is_help=True, help="RAG local oriente experimentation.")
db_app = typer.Typer(no_args_is_help=True, help="Commandes base de donnees.")
experiment_app = typer.Typer(no_args_is_help=True, help="Commandes d'experimentation.")

app.add_typer(db_app, name="db")
app.add_typer(experiment_app, name="experiment")


@db_app.command("init")
def db_init() -> None:
    initialize_database()
    typer.echo("Base initialisee avec pgvector.")


@app.command()
def ingest(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    corpus: str = typer.Option(get_settings().default_corpus_name, "--corpus", help="Nom du corpus cible."),
    description: str | None = typer.Option(None, "--description", help="Description optionnelle du corpus."),
) -> None:
    with session_scope() as session:
        service = IngestionService(session)
        summary = service.ingest_folder(folder, corpus_name=corpus, description=description)
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
) -> None:
    with session_scope() as session:
        service = IndexingService(session)
        result = service.index_corpus(
            corpus_name=corpus,
            strategy=strategy,
            run_name=run_name,
            embedding_provider=embedding_provider,
            embedding_model_name=embedding_model,
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
) -> None:
    with session_scope() as session:
        service = QueryService(session)
        response = service.query(
            question=question,
            corpus_name=corpus,
            strategy=strategy,
            index_run_id=index_run_id,
            top_k=top_k,
            generate_answer=generate,
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


if __name__ == "__main__":
    app()
