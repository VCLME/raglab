from __future__ import annotations

import json
from pathlib import Path

import typer

from raglab.benchmarks import AVAILABLE_LOADERS, get_loader
from raglab.benchmarks.lexml_questions import generate_questions, review_question_set
from raglab.config import get_settings
from raglab.db import initialize_database, session_scope
from raglab.domain.enums import ChunkingStrategy
from raglab.experiments.ragas import JudgeConfig
from raglab.experiments.recall import RecallBenchmarkService
from raglab.experiments.service import ExperimentService
from raglab.indexing.service import IndexingService
from raglab.ingestion.service import IngestionService
from raglab.lexml import LexMLLoadService, getDataFromLexML
from raglab.lexml.fulltext import FullTextCollector
from raglab.logging_utils import configure_logging
from raglab.ollama import OllamaService
from raglab.retrieval.filters import build_retrieval_filters
from raglab.retrieval.service import QueryService

app = typer.Typer(no_args_is_help=True, help="RAG local oriente experimentation.")
db_app = typer.Typer(no_args_is_help=True, help="Commandes base de donnees.")
experiment_app = typer.Typer(no_args_is_help=True, help="Commandes d'experimentation.")
lexml_app = typer.Typer(no_args_is_help=True, help="Collecte LexML Brasil.")
ollama_app = typer.Typer(no_args_is_help=True, help="Pilotage du service Ollama.")
bench_app = typer.Typer(no_args_is_help=True, help="Datasets de benchmark.")

app.add_typer(db_app, name="db")
app.add_typer(experiment_app, name="experiment")
app.add_typer(lexml_app, name="lexml")
app.add_typer(ollama_app, name="ollama")
app.add_typer(bench_app, name="bench")


@app.callback()
def main(
    log_json: bool | None = typer.Option(
        None,
        "--log-json/--no-log-json",
        help="Activer des logs structures au format JSON.",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Override du niveau de log.",
    ),
) -> None:
    configure_logging(settings=get_settings(), log_level=log_level, log_json=log_json)


@db_app.command("init")
def db_init() -> None:
    initialize_database()
    typer.echo("Base initialisee avec pgvector.")


@ollama_app.command("status")
def ollama_status() -> None:
    service = OllamaService()
    typer.echo(json.dumps(service.status(), indent=2, ensure_ascii=False))


@ollama_app.command("list")
def ollama_list() -> None:
    service = OllamaService()
    typer.echo(json.dumps(service.list_models(), indent=2, ensure_ascii=False))


@ollama_app.command("pull")
def ollama_pull(
    model: str = typer.Option(
        get_settings().generation_model,
        "--model",
        help="Modele Ollama a telecharger.",
    ),
) -> None:
    service = OllamaService()
    typer.echo(json.dumps(service.pull_model(model), indent=2, ensure_ascii=False))


@bench_app.command("list")
def bench_list() -> None:
    """Lister les loaders de benchmark disponibles."""
    rows = [
        {
            "name": loader_cls.name,
            "language": loader_cls.language,
            "licence": loader_cls.licence,
            "description": loader_cls.description,
            "default_corpus_name": loader_cls.default_corpus_name,
            "source": loader_cls.source,
        }
        for loader_cls in AVAILABLE_LOADERS.values()
    ]
    typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))


@bench_app.command("download")
def bench_download(
    loader_name: str = typer.Argument(..., help="Nom du loader (ex: fquad). `raglab bench list` pour la liste."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Dossier de sortie. Defaut: data/benchmarks/<loader>/",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Nombre de paires Q/R tirees au hasard (graine --seed). Le corpus reste complet.",
    ),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des questions quand --limit est fourni."),
    full_corpus: bool = typer.Option(
        True,
        "--full-corpus/--sample-corpus",
        help="Ecrire tous les passages du dataset (defaut) ou seulement ceux des questions tirees.",
    ),
) -> None:
    """Telecharger un dataset de benchmark et ecrire corpus + ground_truth sur disque."""
    loader_cls = get_loader(loader_name)
    resolved_output = (output_dir or get_settings().data_dir / "benchmarks" / loader_cls.name).resolve()
    loader = loader_cls()
    dataset = loader.download(resolved_output, limit=limit, sample_seed=seed, full_corpus=full_corpus)
    typer.echo(
        json.dumps(
            {
                "loader": loader_cls.name,
                "corpus_dir": str(dataset.corpus_dir),
                "ground_truth_path": str(dataset.ground_truth_path),
                "metadata_path": str(dataset.metadata_path),
                "corpus_name": dataset.corpus_name,
                "article_count": dataset.article_count,
                "case_count": dataset.case_count,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command()
def serve(
    host: str | None = typer.Option(None, "--host", help="Interface d'ecoute pour l'API."),
    port: int | None = typer.Option(None, "--port", help="Port d'ecoute pour l'API."),
    dev: bool = typer.Option(False, "--dev", help="Activer le mode reload pour le developpement."),
) -> None:
    """Lancer l'API FastAPI raglab (uvicorn)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "raglab.api.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=dev,
    )


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
    result = getDataFromLexML(output_dir=output_dir, page_limit=page_limit)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@lexml_app.command("fulltext")
def lexml_fulltext(
    output_dir: Path = typer.Option(
        get_settings().lexml_fulltext_dir,
        "--output-dir",
        help="Dossier de sortie (corpus/ + manifest.json).",
    ),
    year_from: int = typer.Option(1988, "--from", help="Premiere annee de signature."),
    year_to: int = typer.Option(2024, "--to", help="Derniere annee de signature (incluse)."),
    per_year: int = typer.Option(7, "--per-year", min=1, help="Nombre de lois gardees par annee."),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des lois."),
    min_chars: int = typer.Option(3000, "--min-chars", help="Ignorer les lois plus courtes."),
    max_chars: int = typer.Option(150_000, "--max-chars", help="Ignorer les lois plus longues (codes)."),
) -> None:
    """Collecter le texte integral de lois federales (Senado + Planalto)."""
    result = FullTextCollector().collect(
        output_dir=output_dir,
        years=range(year_from, year_to + 1),
        per_year=per_year,
        seed=seed,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@lexml_app.command("questions")
def lexml_questions(
    corpus_dir: Path = typer.Option(
        get_settings().lexml_fulltext_dir / "corpus",
        "--corpus-dir",
        help="Corpus texte integral produit par `raglab lexml fulltext`.",
    ),
    output_dir: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "lexml_fulltext",
        "--output-dir",
        help="Dossier du dataset (ground_truth.jsonl + metadata.json).",
    ),
    count: int = typer.Option(300, "--count", min=1, help="Nombre de questions a garder."),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des passages et des types."),
    backend: str = typer.Option(
        "llamacpp",
        "--backend",
        help="llamacpp (serveur compatible OpenAI, demarre si besoin) ou ollama.",
    ),
    model: str | None = typer.Option(None, "--model", help="Modele (defaut: question_model ou generation_model)."),
    profile: str | None = typer.Option(None, "--profile", help="Profil llama.cpp a demarrer (defaut: question_model_profile)."),
) -> None:
    """Generer un jeu de questions typees (paraphrase / reference / entity) sur le corpus LexML."""
    result = generate_questions(
        get_settings(),
        backend=backend,
        corpus_dir=corpus_dir,
        output_dir=output_dir,
        count=count,
        seed=seed,
        model=model,
        profile=profile,
    )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@lexml_app.command("review-questions")
def lexml_review_questions(
    ground_truth: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "lexml_fulltext" / "ground_truth.jsonl",
        "--ground-truth",
        help="Jeu de questions a re-verifier avec les regles actuelles.",
    ),
) -> None:
    """Marquer `rejected` les questions qui echouent aux regles actuelles (sans les supprimer)."""
    counts = review_question_set(ground_truth)
    typer.echo(json.dumps({"ground_truth": str(ground_truth), "newly_rejected": counts}, indent=2, ensure_ascii=False))


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


@lexml_app.command("load")
def lexml_load(
    corpus: str = typer.Option("lexml_real", "--corpus", help="Corpus cible pour le cas reel LexML."),
    strategy: ChunkingStrategy = typer.Option(
        ChunkingStrategy.TRADITIONAL,
        "--strategy",
        help="Strategie de chunking a indexer dans PostgreSQL+pgvector.",
    ),
    output_dir: Path = typer.Option(
        get_settings().lexml_documents_dir,
        "--output-dir",
        help="Dossier local pour stocker ou relire les documents LexML.",
    ),
    page_limit: int | None = typer.Option(
        None,
        "--page-limit",
        help="Nombre maximum de pages LexML a collecter pour ce chargement.",
    ),
    incremental: bool = typer.Option(
        True,
        "--incremental/--full",
        help="Reutiliser le dernier index_run compatible quand c'est possible.",
    ),
    tags: list[str] | None = typer.Option(
        ["legal", "lexml", "brasil"],
        "--tag",
        help="Tags a appliquer a tous les documents charges.",
    ),
    embedding_provider: str | None = typer.Option(
        None,
        "--embedding-provider",
        help="Override du provider d'embeddings pour ce chargement.",
    ),
    embedding_model: str | None = typer.Option(
        None,
        "--embedding-model",
        help="Override du modele d'embeddings pour ce chargement.",
    ),
) -> None:
    service = LexMLLoadService()
    result = service.run(
        output_dir=output_dir,
        corpus_name=corpus,
        strategy=strategy,
        page_limit=page_limit,
        incremental=incremental,
        tags=tags,
        embedding_provider=embedding_provider,
        embedding_model_name=embedding_model,
        initialize_db=True,
    )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


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
    ragas: bool = typer.Option(False, "--ragas", help="Generer les reponses et les noter (faithfulness, relevancy, correctness)."),
    ragas_limit: int | None = typer.Option(None, "--ragas-limit", min=1, help="Noter seulement les N premiers cas."),
    judge_backend: str = typer.Option(
        "llamacpp",
        "--judge-backend",
        help="llamacpp (juge independant, demarre si besoin) ou ollama (le generateur se note lui-meme).",
    ),
    judge_model: str | None = typer.Option(None, "--judge-model", help="Modele juge (defaut: judge_model)."),
) -> None:
    with session_scope() as session:
        service = RecallBenchmarkService(session)
        result = service.run(
            corpus_name=corpus,
            strategy=strategy,
            dataset_path=dataset_path,
            lexml_documents_dir=lexml_documents_dir,
            case_limit=case_limit,
            compute_ragas=ragas,
            ragas_case_limit=ragas_limit,
            judge=JudgeConfig(backend=judge_backend, model=judge_model),
        )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
