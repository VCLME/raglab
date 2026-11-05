from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from sqlalchemy import select

from raglab.benchmarks import AVAILABLE_LOADERS, get_loader
from raglab.benchmarks.lexml_questions import generate_questions, review_question_set
from raglab.config import get_settings
from raglab.db import initialize_database, session_scope
from raglab.db.lexical import refresh_lexical_index
from raglab.db.models import Corpus, IndexRun
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.experiments.ragas import JudgeConfig
from raglab.experiments.recall import GeneratorConfig, RecallBenchmarkService
from raglab.experiments.service import ExperimentService
from raglab.indexing.service import IndexingService
from raglab.ingestion.service import IngestionService
from raglab.legifrance.collector import CodeCollector
from raglab.lexml import LexMLLoadService, getDataFromLexML
from raglab.lexml.fulltext import FullTextCollector
from raglab.logging_utils import configure_logging
from raglab.ollama import OllamaService
from raglab.retrieval.filters import build_retrieval_filters
from raglab.retrieval.service import QueryService


def _check_versions_option(value: str | None) -> str | None:
    from raglab.domain.versions import parse_versions_option

    try:
        parse_versions_option(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return value


app = typer.Typer(no_args_is_help=True, help="RAG local oriente experimentation.")
db_app = typer.Typer(no_args_is_help=True, help="Commandes base de donnees.")
experiment_app = typer.Typer(no_args_is_help=True, help="Commandes d'experimentation.")
lexml_app = typer.Typer(no_args_is_help=True, help="Collecte LexML Brasil.")
legifrance_app = typer.Typer(no_args_is_help=True, help="Codes francais (donnees LEGI de Legifrance).")
eurlex_app = typer.Typer(no_args_is_help=True, help="Actes de l'UE (EUR-Lex / CELLAR) : RGPD, AI Act, DORA, NIS 2.")
ollama_app = typer.Typer(no_args_is_help=True, help="Pilotage du service Ollama.")
bench_app = typer.Typer(no_args_is_help=True, help="Datasets de benchmark.")
graph_app = typer.Typer(no_args_is_help=True, help="Graphe structure dans Neo4j (lois, articles, renvois).")
sources_app = typer.Typer(
    no_args_is_help=True, help="Sources officielles (Legifrance, EUR-Lex) : collecte puis ingestion, comme l'Atelier."
)

app.add_typer(db_app, name="db")
app.add_typer(experiment_app, name="experiment")
app.add_typer(lexml_app, name="lexml")
app.add_typer(legifrance_app, name="legifrance")
app.add_typer(eurlex_app, name="eurlex")
app.add_typer(ollama_app, name="ollama")
app.add_typer(bench_app, name="bench")
app.add_typer(graph_app, name="graph")
app.add_typer(sources_app, name="sources")


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


@db_app.command("refresh-lexical")
def db_refresh_lexical(
    corpus: str | None = typer.Option(None, "--corpus", help="Limiter aux runs de ce corpus."),
    index_run_ids: list[str] | None = typer.Option(None, "--index-run-id", help="Run(s) a recalculer."),
) -> None:
    """Recalculer tsvector et statistiques BM25 (apres un changement de langue), sans re-embedder."""
    with session_scope() as session:
        stmt = select(IndexRun.id)
        if index_run_ids:
            stmt = stmt.where(IndexRun.id.in_(index_run_ids))
        if corpus:
            stmt = stmt.join(Corpus, Corpus.id == IndexRun.corpus_id).where(Corpus.name == corpus)
        results = {
            run_id: refresh_lexical_index(session, run_id, default_language=get_settings().default_language)
            for run_id in session.scalars(stmt).all()
        }
    typer.echo(json.dumps(results, indent=2, ensure_ascii=False))


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


@bench_app.command("all")
def bench_all(
    label: str = typer.Option(
        ..., "--label", help="Nom du run (ex. baseline-v0). Resultat: benchmarks/results/<label>.json"
    ),
    suite: list[str] | None = typer.Option(
        None,
        "--suite",
        help=(
            "piaf, lexml_fulltext, legi_consommation, eurlex_compliance, lexml_references (renvois, 9.9b), legi_versions (versions, 9.10) ou br_expat (30 questions reelles, Bresil) "
            "(defaut: piaf + lexml_fulltext)."
        ),
    ),
    strategy: ChunkingStrategy = typer.Option(ChunkingStrategy.TRADITIONAL, "--strategy"),
    ragas_limit: int = typer.Option(
        100, "--ragas-limit", min=0, help="Questions generees et notees par suite (0 = retrieval seul)."
    ),
    judge_backend: str = typer.Option(
        "llamacpp", "--judge-backend", help="llamacpp (Gemma, demarre si besoin) ou ollama."
    ),
    retrieval_mode: RetrievalMode | None = typer.Option(
        None,
        "--retrieval-mode",
        help="dense (KNN cosinus), lexical (BM25) ou hybrid (fusion RRF). Defaut: RAGLAB_DEFAULT_RETRIEVAL_MODE.",
    ),
    lexical_weight: float | None = typer.Option(
        None, "--lexical-weight", min=0.0, max=1.0, help="Poids du BM25 dans la fusion RRF (mode hybrid)."
    ),
    rrf_k: int | None = typer.Option(None, "--rrf-k", min=0, help="Constante k de la fusion RRF (defaut 60)."),
    rerank: bool | None = typer.Option(
        None,
        "--rerank/--no-rerank",
        help="Re-ranking cross-encoder des candidats (defaut: RAGLAB_DEFAULT_RERANK).",
    ),
    citations: bool | None = typer.Option(
        None,
        "--citations/--no-citations",
        help="Reconnaitre les citations juridiques (art. N da Lei X, article L. 221-18 du code de la consommation) : restreindre a la loi ou au code cite, epingler l'article. Defaut: RAGLAB_CITATION_RESOLVER.",
    ),
    graph: bool | None = typer.Option(
        None,
        "--graph/--no-graph",
        help="Branche graphe : suivre les renvois (CITES) des articles trouves dans Neo4j, fusion RRF a trois sources. Defaut: RAGLAB_GRAPH_RETRIEVAL.",
    ),
    versions: str | None = typer.Option(
        None,
        "--versions",
        callback=_check_versions_option,
        help="Versions d'articles utilisables : in_force (en vigueur aujourd'hui, ou a la date demandee par la question), all (toutes, comme un RAG classique), as_of=AAAA-MM-JJ. Defaut: RAGLAB_VERSIONS_DEFAULT.",
    ),
    generator_provider: str | None = typer.Option(
        None,
        "--generator-provider",
        help="Fournisseur qui ecrit les reponses notees : ollama (defaut, qwen2.5:7b comme les runs precedents) ou llamacpp / vllm (passe de generation separee apres la recherche ; llamacpp = redacteur de production depuis gen-qwen36-v1).",
    ),
    generator_model: str | None = typer.Option(
        None, "--generator-model", help="Modele du generateur (defaut : celui du fournisseur)."
    ),
    generator_profile: str | None = typer.Option(
        None,
        "--generator-profile",
        help="Profil llama.cpp a demarrer pour la generation (defaut : RAGLAB_WRITER_MODEL_PROFILE).",
    ),
    query_translation: bool | None = typer.Option(
        None,
        "--query-translation/--no-query-translation",
        help="Traduire la question dans la langue du corpus (redacteur llama.cpp) pour le BM25 seulement. Defaut: RAGLAB_QUERY_TRANSLATION.",
    ),
) -> None:
    """Regenerer les chiffres de benchmark (PIAF + LexML, Code de la consommation sur demande) dans benchmarks/results/."""
    from raglab.benchmarks.suite import render_markdown, run_all

    result = run_all(
        label=label,
        strategy=strategy,
        ragas_limit=ragas_limit or None,
        judge=JudgeConfig(backend=judge_backend),
        suites=suite or None,
        retrieval_mode=retrieval_mode,
        lexical_weight=lexical_weight,
        rrf_k=rrf_k,
        rerank=rerank,
        citations=citations,
        graph=graph,
        versions=versions,
        generator=GeneratorConfig(provider=generator_provider, model=generator_model, profile=generator_profile),
        query_translation=query_translation,
    )
    output = Path("benchmarks/results") / f"{label}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(render_markdown([result]))
    typer.echo(f"\nResultat: {output}")


@app.command("gate")
def gate(
    results: Path | None = typer.Option(None, "--results", help="Resultat de `raglab bench all` a verifier."),
    run: bool = typer.Option(False, "--run", help="Lancer `raglab bench all` puis verifier son resultat."),
    ragas_limit: int = typer.Option(
        100, "--ragas-limit", min=0, help="Avec --run : questions notees (0 = retrieval seul)."
    ),
    judge_backend: str = typer.Option("llamacpp", "--judge-backend", help="Avec --run : juge RAGAS."),
    thresholds: Path = typer.Option(Path("benchmarks/thresholds.json"), "--thresholds"),
    require_all: bool = typer.Option(False, "--require-all", help="Echouer aussi si une metrique n'a pas ete mesuree."),
    summary_file: Path | None = typer.Option(
        None, "--summary-file", help="Ecrire le tableau Markdown ici (ex. $GITHUB_STEP_SUMMARY)."
    ),
) -> None:
    """Echouer (code 1) si Recall@5, MRR ou faithfulness passent sous les seuils versionnes."""
    from datetime import UTC, datetime

    from raglab.benchmarks.gate import evaluate, failed, load_thresholds, render

    if run == (results is not None):
        raise typer.BadParameter("Donner soit --results, soit --run.")
    if run:
        from raglab.benchmarks.suite import run_all

        label = f"gate-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        result = run_all(label=label, ragas_limit=ragas_limit or None, judge=JudgeConfig(backend=judge_backend))
        results = Path("benchmarks/results") / f"{label}.json"
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        assert results is not None
        result = json.loads(results.read_text(encoding="utf-8"))
    checks = evaluate(result, load_thresholds(thresholds))
    table = render(checks, label=result.get("label", str(results)))
    typer.echo(table)
    if summary_file:
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(table + "\n")
    if failed(checks, require_all=require_all):
        raise typer.Exit(code=1)


@bench_app.command("compare")
def bench_compare(
    before: str = typer.Argument(..., help="Run de reference (ex. baseline-v1)."),
    after: str = typer.Argument(..., help="Run compare (ex. hybrid-v1)."),
    k: int = typer.Option(5, "--k", help="Recall@k compare."),
    suites: list[str] | None = typer.Option(
        None,
        "--suites",
        help="Paire de suites a comparer, suite_avant:suite_apres (ex. lexml_fr_pt:lexml_fr, memes questions en deux langues). Defaut: les suites de meme nom.",
    ),
) -> None:
    """Comparer deux runs question par question (McNemar sur le recall, bootstrap apparie sur le MRR)."""
    from raglab.benchmarks.compare import compare_runs, render

    pairs: list[tuple[str, str]] | None = None
    if suites:
        if any(pair.count(":") != 1 for pair in suites):
            raise typer.BadParameter("Format attendu: suite_avant:suite_apres.")
        pairs = [(before_suite, after_suite) for before_suite, after_suite in (pair.split(":") for pair in suites)]
    load = lambda name: json.loads((Path("benchmarks/results") / f"{name}.json").read_text(encoding="utf-8"))  # noqa: E731
    typer.echo(render(compare_runs(load(before), load(after), k=k, pairs=pairs), k=k))


@bench_app.command("rejudge")
def bench_rejudge(
    report: Path = typer.Argument(..., help="Rapport detaille d'un run (data/reports/recall-*.json)."),
    out: Path = typer.Option(
        ..., "--out", help="Fichier JSON des nouvelles notes (les resultats historiques ne changent pas)."
    ),
    clock: str = typer.Option(
        ..., "--clock", help="Date du run (AAAA-MM-JJ) : le contexte presente est reconstruit avec cette horloge."
    ),
    judge_backend: str = typer.Option(
        "llamacpp", "--judge-backend", help="llamacpp (Gemma, defaut des runs publies) ou ollama."
    ),
) -> None:
    """Re-noter la fidelite des memes reponses : contexte brut (protocole v1) et contexte presente au redacteur (v2)."""
    from datetime import date

    from raglab.experiments.rejudge import rejudge

    result = rejudge(report, today=date.fromisoformat(clock), judge=JudgeConfig(backend=judge_backend))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(json.dumps(result["summary"], ensure_ascii=False, indent=1))


@bench_app.command("report")
def bench_report(
    labels: list[str] = typer.Argument(..., help="Runs a comparer, dans l'ordre des colonnes."),
) -> None:
    """Afficher le tableau comparatif Markdown de plusieurs runs de `raglab bench all`."""
    from raglab.benchmarks.suite import render_markdown

    runs = [json.loads((Path("benchmarks/results") / f"{name}.json").read_text(encoding="utf-8")) for name in labels]
    typer.echo(render_markdown(runs))


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


@graph_app.command("build")
def graph_build(
    corpus: str | None = typer.Option(None, "--corpus", help="Corpus (dernier index run pgvector)."),
    index_run_id: str | None = typer.Option(None, "--index-run", help="Index run explicite."),
    profile: str | None = typer.Option(
        None, "--profile", help="laws, eu_acts, generic ou auto (defaut: RAGLAB_GRAPH_PROFILES, sinon auto)."
    ),
) -> None:
    """Construire (ou reconstruire) le graphe structure d'un index run dans Neo4j."""
    from raglab.graph.structured import StructuredGraphService

    with session_scope() as session:
        service = StructuredGraphService(session)
        try:
            result = service.build(corpus_name=corpus, index_run_id=index_run_id, profile=profile)
        finally:
            service.store.close()
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@graph_app.command("status")
def graph_status(
    corpus: str | None = typer.Option(None, "--corpus", help="Corpus (dernier index run pgvector)."),
    index_run_id: str | None = typer.Option(None, "--index-run", help="Index run explicite."),
) -> None:
    """Etat du graphe d'un index run : profil, date, comptes relus dans Neo4j."""
    from raglab.graph.structured import StructuredGraphService

    with session_scope() as session:
        service = StructuredGraphService(session)
        try:
            run = service.resolve_index_run(corpus_name=corpus, index_run_id=index_run_id)
            info = service.store.run_info(run.id)
            counts = service.store.counts(run.id) if info else {}
        finally:
            service.store.close()
    typer.echo(json.dumps({"index_run_id": run.id, "graph": info, "counts": counts}, indent=2, ensure_ascii=False))


@graph_app.command("sample")
def graph_sample(
    output: Path = typer.Option(..., "--output", help="Fichier JSON de l'echantillon a relire."),
    corpus: str | None = typer.Option(None, "--corpus"),
    index_run_id: str | None = typer.Option(None, "--index-run"),
    seed: int = typer.Option(42, "--seed"),
    cites: int = typer.Option(60, "--cites", min=0, help="Aretes CITES tirees."),
    amendments: int = typer.Option(30, "--amendments", min=0, help="Aretes AMENDS / REVOKES tirees."),
) -> None:
    """Tirer un echantillon d'aretes a verifier a la main (precision de l'extraction)."""
    from raglab.graph.evaluation import draw_sample
    from raglab.graph.structured import StructuredGraphService

    with session_scope() as session:
        service = StructuredGraphService(session)
        run = service.resolve_index_run(corpus_name=corpus, index_run_id=index_run_id)
        payload, documents = service.payload_with_documents(run)
    sample = draw_sample(payload, documents, seed=seed, cites=cites, amendments=amendments)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(f"{len(sample['items'])} aretes -> {output}")


@graph_app.command("report")
def graph_report(
    sample: Path = typer.Option(..., "--sample", exists=True, dir_okay=False, help="Echantillon relu (verdicts)."),
    corpus: str | None = typer.Option(None, "--corpus"),
    index_run_id: str | None = typer.Option(None, "--index-run"),
    questions: Path | None = typer.Option(
        None, "--questions", exists=True, dir_okay=False, help="ground_truth.jsonl LexML (couverture des articles)."
    ),
) -> None:
    """Precision de l'extraction (echantillon relu) et questions LexML qui tombent sur un noeud Article."""
    from raglab.graph.evaluation import article_coverage, load_cases, precision_report
    from raglab.graph.structured import StructuredGraphService

    report: dict = {"precision": precision_report(json.loads(sample.read_text(encoding="utf-8")))}
    if questions is not None:
        with session_scope() as session:
            service = StructuredGraphService(session)
            run = service.resolve_index_run(corpus_name=corpus, index_run_id=index_run_id)
            payload, documents = service.payload_with_documents(run)
        report["coverage"] = article_coverage(payload, load_cases(questions), documents)
        report["extraction"] = payload.stats
        report["nodes"] = payload.node_counts()
        report["relationships"] = payload.relationship_counts()
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


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
    language: str | None = typer.Option(
        None,
        "--language",
        help="Langue du corpus (fr, pt) pour la recherche lexicale. Defaut: metadata.json du loader, sinon RAGLAB_DEFAULT_LANGUAGE.",
    ),
) -> None:
    with session_scope() as session:
        service = IngestionService(session)
        summary = service.ingest_folder(
            folder, corpus_name=corpus, description=description, tags=tags, language=language
        )
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


@lexml_app.command("br-expat")
def lexml_br_expat(
    output_dir: Path = typer.Option(
        get_settings().br_expat_dir,
        "--output-dir",
        help="Dossier de sortie (corpus/ + raw/ + manifest.json).",
    ),
    only: str | None = typer.Option(
        None, "--only", help="Cles des textes a collecter, separees par des virgules (defaut: les 19)."
    ),
) -> None:
    """Collecter les 19 textes federaux du corpus "Bresil expat" (Planalto compile + Receita Federal)."""
    from raglab.lexml.br_expat import BrExpatCollector

    keys = {key.strip() for key in only.split(",") if key.strip()} if only else None
    result = BrExpatCollector().collect(output_dir=output_dir, keys=keys)
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
    profile: str | None = typer.Option(
        None, "--profile", help="Profil llama.cpp a demarrer (defaut: question_model_profile)."
    ),
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


@lexml_app.command("reference-questions")
def lexml_reference_questions(
    corpus_dir: Path = typer.Option(
        get_settings().lexml_fulltext_dir / "corpus",
        "--corpus-dir",
        help="Corpus texte integral produit par `raglab lexml fulltext` (le meme que le jeu LexML).",
    ),
    output_dir: Path = typer.Option(
        Path("benchmarks") / "lexml_references",
        "--output-dir",
        help="Dossier du jeu fige (ground_truth.jsonl + metadata.json).",
    ),
    count: int = typer.Option(100, "--count", min=1, help="Nombre de questions a garder."),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des renvois et du partage dev / heldout."),
    backend: str = typer.Option(
        "llamacpp",
        "--backend",
        help="llamacpp (serveur compatible OpenAI, demarre si besoin) ou ollama.",
    ),
    model: str | None = typer.Option(None, "--model", help="Modele (defaut: question_model ou generation_model)."),
    profile: str | None = typer.Option(
        None, "--profile", help="Profil llama.cpp a demarrer (defaut: question_model_profile)."
    ),
    mix: str = typer.Option(
        "via_topic=0.5,scenario=0.3,via_article=0.2",
        "--mix",
        help="Part de chaque type : via_topic (sujet de A), scenario (situation concrete), via_article (cite A).",
    ),
) -> None:
    """Generer le jeu « renvois » : l'article A renvoie a l'article B, la reponse est dans B (9.9b)."""
    from raglab.benchmarks.lexml_references import generate_reference_questions, parse_mix

    try:
        shares = parse_mix(mix)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--mix") from exc
    result = generate_reference_questions(
        get_settings(),
        backend=backend,
        corpus_dir=corpus_dir,
        output_dir=output_dir,
        count=count,
        seed=seed,
        model=model,
        profile=profile,
        shares=shares,
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


@legifrance_app.command("fetch")
def legifrance_fetch(
    code: str = typer.Option("consommation", "--code", help="Code a collecter (slug, ex. consommation)."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Dossier de sortie (source.git, corpus/, manifest.json). Defaut: data/legifrance/<code>/",
    ),
    commit: str | None = typer.Option(
        None, "--commit", help="Commit du depot tricoteuses (defaut: celui fige pour le benchmark)."
    ),
    versions: str = typer.Option(
        "all", "--versions", help="all (toutes les versions, defaut) ou current (versions en vigueur seulement)."
    ),
) -> None:
    """Collecter un code avec l'historique de ses versions : un document par version d'article."""
    result = CodeCollector().collect(code=code, output_dir=output_dir, commit=commit, versions=versions)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@legifrance_app.command("questions")
def legifrance_questions(
    corpus_dir: Path = typer.Option(
        get_settings().legifrance_dir / "consommation" / "corpus",
        "--corpus-dir",
        help="Corpus produit par `raglab legifrance fetch`.",
    ),
    output_dir: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "legi_consommation",
        "--output-dir",
        help="Dossier du dataset (ground_truth.jsonl + metadata.json).",
    ),
    count: int = typer.Option(300, "--count", min=1, help="Nombre de questions a garder."),
    seed: int = typer.Option(
        42, "--seed", help="Graine du tirage des passages, des types et de la partie dev / heldout."
    ),
    backend: str = typer.Option(
        "llamacpp",
        "--backend",
        help="llamacpp (serveur compatible OpenAI, demarre si besoin) ou ollama.",
    ),
    model: str | None = typer.Option(None, "--model", help="Modele (defaut: question_model ou generation_model)."),
    profile: str | None = typer.Option(
        None, "--profile", help="Profil llama.cpp a demarrer (defaut: question_model_profile)."
    ),
) -> None:
    """Generer un jeu de questions typees (scenario / paraphrase / reference / entity) sur un code francais."""
    from raglab.benchmarks.legi_questions import generate_questions as generate_legi_questions

    result = generate_legi_questions(
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


@legifrance_app.command("version-questions")
def legifrance_version_questions(
    corpus_dir: Path = typer.Option(
        get_settings().legifrance_dir / "consommation" / "corpus",
        "--corpus-dir",
        help="Corpus produit par `raglab legifrance fetch` (toutes les versions).",
    ),
    output_dir: Path = typer.Option(
        Path("benchmarks") / "legi_versions",
        "--output-dir",
        help="Dossier du jeu fige (ground_truth.jsonl + metadata.json).",
    ),
    count: int = typer.Option(100, "--count", min=1, help="Nombre de questions a garder."),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des pieges et du partage dev / heldout."),
    backend: str = typer.Option(
        "llamacpp",
        "--backend",
        help="llamacpp (serveur compatible OpenAI, demarre si besoin) ou ollama.",
    ),
    model: str | None = typer.Option(None, "--model", help="Modele (defaut: question_model ou generation_model)."),
    profile: str | None = typer.Option(
        None, "--profile", help="Profil llama.cpp a demarrer (defaut: question_model_profile)."
    ),
) -> None:
    """Generer le jeu « versions » : questions dont la reponse naive vient d'une version abrogee ou reecrite (9.10)."""
    from raglab.benchmarks.legi_versions import generate_version_questions

    result = generate_version_questions(
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


@legifrance_app.command("review-questions")
def legifrance_review_questions(
    ground_truth: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "legi_consommation" / "ground_truth.jsonl",
        "--ground-truth",
        help="Jeu de questions a re-verifier avec les regles actuelles.",
    ),
) -> None:
    """Marquer `rejected` les questions qui echouent aux regles actuelles (sans les supprimer)."""
    from raglab.benchmarks.legi_questions import review_question_set as review_legi_question_set

    counts = review_legi_question_set(ground_truth)
    typer.echo(json.dumps({"ground_truth": str(ground_truth), "newly_rejected": counts}, indent=2, ensure_ascii=False))


def _csv(value: str | None) -> list[str] | None:
    return [item.strip() for item in value.split(",") if item.strip()] if value else None


@eurlex_app.command("fetch")
def eurlex_fetch(
    acts: str | None = typer.Option(
        None, "--acts", help="Actes (cles separees par des virgules, ex. gdpr,ai_act,dora,nis2). Defaut: les 15."
    ),
    languages: str = typer.Option("fr,en,pt", "--lang", help="Langues (fr, en, pt)."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Dossier de sortie (raw/, corpus/, manifest.json). Defaut: data/eurlex/compliance/"
    ),
    delay: float = typer.Option(1.0, "--delay", min=0.2, help="Secondes entre deux requetes CELLAR."),
) -> None:
    """Collecter les actes : un document par considerant, article ou annexe, par langue et par version."""
    from raglab.eurlex.collector import EurlexCollector

    result = EurlexCollector().collect(acts=_csv(acts), languages=_csv(languages), output_dir=output_dir, delay=delay)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@sources_app.command("list")
def sources_list() -> None:
    """Sources officielles connues, avec leur corpus et leur commande de collecte."""
    from raglab.sources.jobs import SOURCE_COMMANDS, official_sources

    rows = [
        {
            "source": name,
            "corpus": suite.corpus_name,
            "corpus_dir": str(suite.corpus_dir),
            "command": SOURCE_COMMANDS[name],
        }
        for name, suite in official_sources(get_settings()).items()
    ]
    typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))


@sources_app.command("fetch")
def sources_fetch(
    name: str = typer.Argument(..., help="legi (Code de la consommation) ou eurlex (actes de conformite de l'UE)."),
    ingest: bool = typer.Option(
        True, "--ingest/--no-ingest", help="Ingerer le corpus apres la collecte (sans indexer)."
    ),
) -> None:
    """Collecter une source officielle puis l'ingerer, comme `POST /api/sources/{name}/fetch` (sans embeddings)."""
    from raglab.sources.jobs import SourceJobs

    jobs = SourceJobs()
    if name not in jobs.sources:
        raise typer.BadParameter(f"source inconnue: {name} (connues: {', '.join(jobs.sources)})")
    status = jobs.run(name, ingest=ingest)
    typer.echo(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    if status["state"] != "succeeded":
        raise typer.Exit(code=1)


@eurlex_app.command("acts")
def eurlex_acts(
    check: bool = typer.Option(
        False, "--check", help="Interroger CELLAR (SPARQL) : versions consolidees publiees depuis le gel."
    ),
) -> None:
    """Lister les actes du corpus et leurs versions consolidees figees."""
    from raglab.eurlex.acts import ACTS
    from raglab.eurlex.cellar import list_consolidations

    rows = []
    for act in ACTS:
        row = {"key": act.key, "celex": act.celex, "role": act.role, "pinned": list(act.consolidations)}
        if check:
            available = list_consolidations(act.celex)
            row["newer"] = [celex for celex in available if celex > max(act.consolidations, default="")]
        rows.append(row)
    typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))


@eurlex_app.command("graph-sample")
def eurlex_graph_sample(
    output: Path = typer.Option(..., "--output", help="Fichier JSON de l'echantillon a relire."),
    corpus_dir: Path = typer.Option(
        get_settings().eurlex_dir / "compliance" / "corpus", "--corpus-dir", help="Corpus de `raglab eurlex fetch`."
    ),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Tirer ~40 aretes du graphe des actes (sans Postgres ni Neo4j) a verifier a la main."""
    from raglab.eurlex.graph_eval import corpus_payload, draw_sample

    payload, documents = corpus_payload(corpus_dir)
    sample = draw_sample(payload, documents, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(json.dumps({"items": len(sample["items"]), "population": sample["population"], "output": str(output)}))


@eurlex_app.command("graph-report")
def eurlex_graph_report(
    sample: Path = typer.Option(..., "--sample", exists=True, dir_okay=False, help="Echantillon relu (verdicts)."),
) -> None:
    """Precision du graphe des actes, par relation, sur un echantillon relu."""
    from raglab.eurlex.graph_eval import precision_report

    typer.echo(
        json.dumps(precision_report(json.loads(sample.read_text(encoding="utf-8"))), indent=2, ensure_ascii=False)
    )


@eurlex_app.command("questions")
def eurlex_questions(
    corpus_dir: Path = typer.Option(
        get_settings().eurlex_dir / "compliance" / "corpus", "--corpus-dir", help="Corpus de `raglab eurlex fetch`."
    ),
    output_dir: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "eurlex_compliance",
        "--output-dir",
        help="Dossier du dataset (ground_truth.jsonl + metadata.json).",
    ),
    count: int = typer.Option(300, "--count", min=1, help="Nombre de questions a garder."),
    seed: int = typer.Option(
        42, "--seed", help="Graine du tirage des passages, des types et de la partie dev / heldout."
    ),
    backend: str = typer.Option("llamacpp", "--backend", help="llamacpp (demarre si besoin) ou ollama."),
    model: str | None = typer.Option(None, "--model", help="Modele (defaut: question_model ou generation_model)."),
    profile: str | None = typer.Option(None, "--profile", help="Profil llama.cpp (defaut: question_model_profile)."),
) -> None:
    """Generer le jeu de questions typees (paraphrase, reference, entity, cross_reference, cross_language)."""
    from raglab.benchmarks.eurlex_questions import generate_questions as generate_eurlex_questions

    result = generate_eurlex_questions(
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


@eurlex_app.command("review-questions")
def eurlex_review_questions(
    ground_truth: Path = typer.Option(
        get_settings().data_dir / "benchmarks" / "eurlex_compliance" / "ground_truth.jsonl",
        "--ground-truth",
        help="Jeu de questions a re-verifier avec les regles actuelles.",
    ),
) -> None:
    """Marquer `rejected` les questions qui echouent aux regles actuelles (sans les supprimer)."""
    from raglab.benchmarks.eurlex_questions import review_question_set as review_eurlex_question_set

    counts = review_eurlex_question_set(ground_truth)
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
        summary = service.ingest_folder(folder, corpus_name=corpus, description=description, tags=tags, language="pt")
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
    retrieval_mode: RetrievalMode | None = typer.Option(
        None,
        "--retrieval-mode",
        help="dense (KNN cosinus), lexical (BM25) ou hybrid (fusion RRF). Defaut: RAGLAB_DEFAULT_RETRIEVAL_MODE.",
    ),
    lexical_weight: float | None = typer.Option(
        None,
        "--lexical-weight",
        min=0.0,
        max=1.0,
        help="Poids du BM25 dans la fusion RRF (0 = dense seul, 1 = BM25 seul). Mode hybrid.",
    ),
    rrf_k: int | None = typer.Option(None, "--rrf-k", min=0, help="Constante k de la fusion RRF (defaut 60)."),
    rerank: bool | None = typer.Option(
        None,
        "--rerank/--no-rerank",
        help="Re-ranking cross-encoder de RAGLAB_RERANK_CANDIDATES candidats (defaut: RAGLAB_DEFAULT_RERANK).",
    ),
    citations: bool | None = typer.Option(
        None,
        "--citations/--no-citations",
        help="Reconnaitre les citations juridiques (art. N da Lei X, article L. 221-18 du code de la consommation) : restreindre a la loi ou au code cite, epingler l'article. Defaut: RAGLAB_CITATION_RESOLVER.",
    ),
    graph: bool | None = typer.Option(
        None,
        "--graph/--no-graph",
        help="Branche graphe : suivre les renvois (CITES) des articles trouves dans Neo4j, fusion RRF a trois sources. Defaut: RAGLAB_GRAPH_RETRIEVAL.",
    ),
    versions: str | None = typer.Option(
        None,
        "--versions",
        callback=_check_versions_option,
        help="Versions d'articles utilisables : in_force (en vigueur aujourd'hui, ou a la date demandee par la question), all (toutes, comme un RAG classique), as_of=AAAA-MM-JJ. Defaut: RAGLAB_VERSIONS_DEFAULT.",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        help="Afficher la reponse au fil de la generation sur stderr (comme /api/query/stream) ; "
        "le JSON final reste sur stdout.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        "--model",
        help="Modele de generation (defaut : RAGLAB_GENERATION_MODEL pour Ollama, "
        "premier modele servi pour llama.cpp / vLLM).",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Fournisseur de generation : ollama, llamacpp ou vllm, parmi RAGLAB_LLM_PROVIDERS "
        "(defaut : RAGLAB_DEFAULT_LLM_PROVIDER, Qwen3.6 sur llama.cpp demarre si besoin, "
        "sinon RAGLAB_LLM_FALLBACK_PROVIDER ; generator_notice dit pourquoi).",
    ),
    routing: bool = typer.Option(
        False,
        "--routing/--no-routing",
        help="Router la question (langue, intention, corpus si --corpus est absent) et s'abstenir "
        "quand le meilleur passage est trop faible.",
    ),
    query_translation: bool | None = typer.Option(
        None,
        "--query-translation/--no-query-translation",
        help="Question dans une autre langue que le corpus : la traduire (redacteur llama.cpp) pour le BM25 seulement. "
        "Defaut: RAGLAB_QUERY_TRANSLATION.",
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
        if stream and generate:
            outcome = service.retrieve(
                question=question,
                corpus_name=corpus,
                strategy=strategy,
                index_run_id=index_run_id,
                top_k=top_k,
                filters=filters,
                retrieval_mode=retrieval_mode,
                lexical_weight=lexical_weight,
                rrf_k=rrf_k,
                rerank=rerank,
                citations=citations,
                routing=routing,
                graph=graph,
                versions=versions,
                query_translation=query_translation,
            )
            final: dict = {}
            for event, data in service.stream_answer(outcome, llm_model=llm_model, llm_provider=provider):
                if event == "token":
                    typer.echo(data["text"], nl=False, err=True)
                elif event == "done":
                    final = data
            typer.echo("", err=True)
            typer.echo(json.dumps(final, indent=2, ensure_ascii=False))
            return
        response = service.query(
            question=question,
            corpus_name=corpus,
            strategy=strategy,
            index_run_id=index_run_id,
            top_k=top_k,
            generate_answer=generate,
            filters=filters,
            retrieval_mode=retrieval_mode,
            lexical_weight=lexical_weight,
            rrf_k=rrf_k,
            rerank=rerank,
            citations=citations,
            graph=graph,
            versions=versions,
            llm_model=llm_model,
            routing=routing,
            llm_provider=provider,
            query_translation=query_translation,
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


@experiment_app.command("calibrate-judges")
def experiment_calibrate_judges(
    ground_truth: Path = typer.Option(Path("benchmarks/piaf/ground_truth.jsonl"), "--ground-truth"),
    corpus_dir: Path = typer.Option(get_settings().data_dir / "benchmarks" / "piaf" / "corpus", "--corpus-dir"),
    count: int = typer.Option(30, "--count", min=1, help="Nombre de paragraphes (5 reponses a juger par paragraphe)."),
    seed: int = typer.Option(7, "--seed"),
    output: Path | None = typer.Option(None, "--output", help="Ecrire le rapport JSON ici."),
) -> None:
    """Mesurer si les juges RAGAS distinguent bonnes et mauvaises reponses (qwen2.5 via Ollama vs Gemma via llama.cpp)."""
    from raglab.experiments.judge_calibration import calibrate

    report = calibrate(
        ground_truth_path=ground_truth,
        corpus_dir=corpus_dir,
        judges=[JudgeConfig(backend="ollama"), JudgeConfig(backend="llamacpp")],
        count=count,
        seed=seed,
    )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    typer.echo(
        json.dumps(
            [{k: v for k, v in r.items() if k != "rows"} for r in report["results"]], indent=2, ensure_ascii=False
        )
    )


@experiment_app.command("drift")
def experiment_drift(
    baseline_index_run: str | None = typer.Option(None, "--baseline-index-run", help="Index run de reference."),
    candidate_index_run: str | None = typer.Option(None, "--candidate-index-run", help="Index run candidat."),
    baseline_run: str | None = typer.Option(None, "--baseline-run", help="Experiment run de reference."),
    candidate_run: str | None = typer.Option(None, "--candidate-run", help="Experiment run candidat."),
    baseline_since: datetime | None = typer.Option(None, "--baseline-since", help="Debut de la fenetre de reference."),
    baseline_until: datetime | None = typer.Option(None, "--baseline-until", help="Fin (exclue) de la reference."),
    candidate_since: datetime | None = typer.Option(None, "--candidate-since", help="Debut de la fenetre candidate."),
    candidate_until: datetime | None = typer.Option(None, "--candidate-until", help="Fin (exclue) du candidat."),
    alpha: float = typer.Option(0.05, "--alpha", help="Seuil de p-value du test KS."),
    mean_threshold: float = typer.Option(0.05, "--mean-threshold", help="Baisse de moyenne signalee (RAGAS, MRR)."),
    min_samples: int = typer.Option(10, "--min-samples", min=2, help="Taille minimale d'echantillon pour le test KS."),
    output_format: str = typer.Option("markdown", "--format", help="markdown ou json."),
    output: Path | None = typer.Option(None, "--output", help="Ecrire le rapport ici."),
    fail_on_drift: bool = typer.Option(False, "--fail-on-drift", help="Code de sortie 1 si une derive est detectee."),
) -> None:
    """Comparer deux ensembles de resultats (index runs, experiment runs ou fenetres de dates)."""
    from raglab.observability.drift import ResultSelection, build_drift_report, render_markdown

    if output_format not in {"markdown", "json"}:
        raise typer.BadParameter("--format attend markdown ou json.")
    baseline = ResultSelection(baseline_index_run, baseline_run, baseline_since, baseline_until)
    candidate = ResultSelection(candidate_index_run, candidate_run, candidate_since, candidate_until)
    if baseline.is_empty() or candidate.is_empty():
        raise typer.BadParameter("Precisez au moins un critere (index run, run ou dates) pour chaque ensemble.")
    with session_scope() as session:
        report = build_drift_report(
            session, baseline, candidate, alpha=alpha, mean_threshold=mean_threshold, min_samples=min_samples
        )
    text = render_markdown(report) if output_format == "markdown" else json.dumps(report, indent=2, ensure_ascii=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    typer.echo(text)
    if fail_on_drift and report["drift_detected"]:
        raise typer.Exit(code=1)


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
    ragas: bool = typer.Option(
        False, "--ragas", help="Generer les reponses et les noter (faithfulness, relevancy, correctness)."
    ),
    ragas_limit: int | None = typer.Option(None, "--ragas-limit", min=1, help="Noter seulement les N premiers cas."),
    judge_backend: str = typer.Option(
        "llamacpp",
        "--judge-backend",
        help="llamacpp (juge independant, demarre si besoin) ou ollama (le generateur se note lui-meme).",
    ),
    judge_model: str | None = typer.Option(None, "--judge-model", help="Modele juge (defaut: judge_model)."),
    retrieval_mode: RetrievalMode | None = typer.Option(
        None,
        "--retrieval-mode",
        help="dense (KNN cosinus), lexical (BM25) ou hybrid (fusion RRF). Defaut: RAGLAB_DEFAULT_RETRIEVAL_MODE.",
    ),
    lexical_weight: float | None = typer.Option(
        None,
        "--lexical-weight",
        min=0.0,
        max=1.0,
        help="Poids du BM25 dans la fusion RRF (0 = dense seul, 1 = BM25 seul). Mode hybrid.",
    ),
    rrf_k: int | None = typer.Option(None, "--rrf-k", min=0, help="Constante k de la fusion RRF (defaut 60)."),
    rerank: bool | None = typer.Option(
        None,
        "--rerank/--no-rerank",
        help="Re-ranking cross-encoder des candidats (defaut: RAGLAB_DEFAULT_RERANK).",
    ),
    citations: bool | None = typer.Option(
        None,
        "--citations/--no-citations",
        help="Reconnaitre les citations juridiques (art. N da Lei X, article L. 221-18 du code de la consommation) : restreindre a la loi ou au code cite, epingler l'article. Defaut: RAGLAB_CITATION_RESOLVER.",
    ),
    graph: bool | None = typer.Option(
        None,
        "--graph/--no-graph",
        help="Branche graphe : suivre les renvois (CITES) des articles trouves dans Neo4j, fusion RRF a trois sources. Defaut: RAGLAB_GRAPH_RETRIEVAL.",
    ),
    versions: str | None = typer.Option(
        None,
        "--versions",
        callback=_check_versions_option,
        help="Versions d'articles utilisables : in_force (en vigueur aujourd'hui, ou a la date demandee par la question), all (toutes, comme un RAG classique), as_of=AAAA-MM-JJ. Defaut: RAGLAB_VERSIONS_DEFAULT.",
    ),
) -> None:
    with session_scope() as session:
        service = RecallBenchmarkService(session)
        result = service.run(
            corpus_name=corpus,
            strategy=strategy,
            dataset_path=dataset_path,
            lexml_documents_dir=lexml_documents_dir,
            case_limit=case_limit,
            retrieval_mode=retrieval_mode,
            lexical_weight=lexical_weight,
            rrf_k=rrf_k,
            rerank=rerank,
            citations=citations,
            graph=graph,
            versions=versions,
            compute_ragas=ragas,
            ragas_case_limit=ragas_limit,
            judge=JudgeConfig(backend=judge_backend, model=judge_model),
        )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@experiment_app.command("routing")
def experiment_routing(
    corpus: list[str] | None = typer.Option(
        None,
        "--corpus",
        help="Corpus parmi lesquels le routeur choisit (repetable). Defaut : tous les index compatibles.",
    ),
    strategy: ChunkingStrategy | None = typer.Option(None, "--strategy", help="Strategie de chunking a cibler."),
    sample_size: int | None = typer.Option(
        None,
        "--sample-size",
        min=1,
        help="Questions in-scope tirees (reparties entre PIAF et LexML). Defaut : la taille du jeu d'abstention.",
    ),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage des questions in-scope."),
    top_k: int = typer.Option(5, "--top-k", min=1, help="Passages recuperes par question."),
    calibration_size: int = typer.Option(
        100,
        "--calibration-size",
        min=1,
        help="Questions in-scope de calibration par corpus (disjointes des questions evaluees) "
        "pour les seuils par corpus.",
    ),
    retrieval_mode: RetrievalMode | None = typer.Option(
        None,
        "--retrieval-mode",
        help="Retrieval derriere le routeur : dense, lexical ou hybrid. Defaut: RAGLAB_DEFAULT_RETRIEVAL_MODE.",
    ),
    rerank: bool | None = typer.Option(
        None,
        "--rerank/--no-rerank",
        help="Re-ranking cross-encoder (defaut: RAGLAB_DEFAULT_RERANK, ignore sans GPU).",
    ),
    citations: bool | None = typer.Option(
        None,
        "--citations/--no-citations",
        help="Resolution des citations juridiques (defaut: RAGLAB_CITATION_RESOLVER).",
    ),
    query_translation: bool | None = typer.Option(
        None,
        "--query-translation/--no-query-translation",
        help="Traduction de la question pour le BM25 quand sa langue differe du corpus (defaut: RAGLAB_QUERY_TRANSLATION).",
    ),
    in_scope: list[str] | None = typer.Option(
        None,
        "--in-scope",
        help="Jeux de questions in-scope (repetable) : piaf, lexml_fulltext, legi_consommation, eurlex_compliance, "
        "ou lexml_fr / lexml_fr_pt (questions francaises sur LexML et les memes en portugais) et br_expat (questions "
        "francaises sur les textes federaux bresiliens), jamais dans le tirage par defaut. Defaut : les jeux par defaut.",
    ),
    abstention_path: Path | None = typer.Option(
        None, "--abstention", help="Jeu de questions a refuser (defaut : benchmarks/abstention/questions.jsonl)."
    ),
    calibration_file: list[str] | None = typer.Option(
        None,
        "--calibration-file",
        help="Questions de calibration supplementaires (repetable) : lexml_fr, lexml_pt, br_expat, eurlex.",
    ),
) -> None:
    """Mesurer le routeur : abstention (precision / rappel / F1, courbe), intention, langue, corpus, latence."""
    from raglab.experiments.routing import (
        ABSTENTION_PATH,
        IN_SCOPE_SETS,
        RoutingExperimentService,
        named_sets,
        render_markdown,
    )

    try:
        sets = named_sets(in_scope) if in_scope else IN_SCOPE_SETS
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with session_scope() as session:
        report = RoutingExperimentService(session).run(
            corpora=corpus or None,
            strategy=strategy,
            sample_size=sample_size,
            seed=seed,
            top_k=top_k,
            calibration_size=calibration_size,
            retrieval_mode=retrieval_mode,
            rerank=rerank,
            citations=citations,
            query_translation=query_translation,
            in_scope_sets=sets,
            abstention_path=abstention_path or ABSTENTION_PATH,
            calibration_files=calibration_file or None,
        )
    summary = {k: v for k, v in report["summary"].items() if k != "curve"}
    typer.echo(json.dumps({"report_path": report["report_path"], "summary": summary}, indent=2, ensure_ascii=False))
    typer.echo(render_markdown(report["summary"]), err=True)


@experiment_app.command("intent-generalization")
def experiment_intent_generalization(
    dev: list[Path] = typer.Option(..., "--dev", help="Rapports `experiment routing` qui choisissent la variante."),
    test: list[Path] | None = typer.Option(
        None, "--test", help="Rapports de validation independants, lus une fois la variante choisie."
    ),
    collect: Path = typer.Option(
        Path("benchmarks/routing/router-languages-collect-v1.json"),
        "--collect",
        help="Collecte de #78 (calibration PIAF et LexML).",
    ),
    output: Path | None = typer.Option(None, "--output", help="Ecrire le resultat complet en JSON."),
    export: str | None = typer.Option(
        None, "--export", help="Au lieu de l'etude : ecrire le modele d'une variante logistique (voir --output)."
    ),
) -> None:
    """Variantes d'intention rejouees sur des rapports en direct (docs/intentions.md), sans GPU."""
    from raglab.embeddings.factory import build_embedding_provider
    from raglab.experiments.intent_generalization import calibration_rows, export_logistic, render, study

    settings = get_settings()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))  # noqa: E731
    dev_reports = {path.stem: read(path) for path in dev}
    test_reports = {path.stem: read(path) for path in test or []}
    calibration = calibration_rows(
        read(collect), settings.routing_corpus_examples_path, [*dev_reports.values(), *test_reports.values()]
    )
    if export is not None:
        payload = export_logistic(export, calibration, build_embedding_provider(settings))
        target = output or settings.routing_intent_logistic_path
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        typer.echo(json.dumps({"variant": export, "path": str(target), "threshold": payload["logistic"]["threshold"]}))
        return
    result = study(dev_reports, test_reports, calibration, build_embedding_provider(settings))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(json.dumps({"selected": result["selected"], "best_by_family": result["best_by_family"]}, indent=2))
    typer.echo(render(result), err=True)


@experiment_app.command("routing-compare")
def experiment_routing_compare(
    before: Path = typer.Argument(..., help="Rapport `experiment routing` de reference."),
    after: Path = typer.Argument(..., help="Rapport compare (memes questions)."),
) -> None:
    """McNemar apparie entre deux rapports du routeur : repondues par jeu, refus gardes."""
    from raglab.experiments.routing import paired_live

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in (before, after)]
    typer.echo(json.dumps(paired_live(*reports), indent=2, ensure_ascii=False))


@experiment_app.command("routing-languages")
def experiment_routing_languages(
    corpus: list[str] = typer.Option(
        ["bench_piaf_fr", "bench_lexml_pt"], "--corpus", help="Corpus candidats (repetable)."
    ),
    strategy: ChunkingStrategy | None = typer.Option(None, "--strategy", help="Strategie de chunking a cibler."),
    sample_size: int = typer.Option(
        300, "--sample-size", min=1, help="Questions in-scope (lexml_fr, lexml_fr_pt, piaf)."
    ),
    seed: int = typer.Option(42, "--seed", help="Graine du tirage (celle des runs router-crosslang-*-v1)."),
    top_k: int = typer.Option(5, "--top-k", min=1, help="Passages recuperes par question."),
    replay_path: Path | None = typer.Option(
        None, "--replay", help="Rejouer un rapport deja collecte au lieu de relancer la collecte (sans GPU)."
    ),
    intent: bool = typer.Option(
        False, "--intent", help="Comparer les options d'intention (kNN, regle jointe...) : docs/intentions.md."
    ),
    intent_calibration: Path | None = typer.Option(
        None, "--intent-calibration", help="Avec --intent : ecrire la calibration de la regle jointe retenue."
    ),
) -> None:
    """Routage multilingue : chaque question cherchee sur chaque corpus, puis les politiques rejouees hors ligne."""
    from raglab.experiments.routing_languages import MultilingualRoutingStudy, compare, render_comparison

    if replay_path is not None:
        report = json.loads(replay_path.read_text(encoding="utf-8"))
        report["report_path"] = str(replay_path)
    else:
        with session_scope() as session:
            report = MultilingualRoutingStudy(session).collect(
                corpora=corpus, strategy=strategy, sample_size=sample_size, seed=seed, top_k=top_k
            )
    if intent:
        from raglab.embeddings.factory import build_embedding_provider
        from raglab.experiments.routing_languages import compare_intent, intent_signals, selected_calibration

        settings = get_settings()
        signals = intent_signals(report, build_embedding_provider(settings), settings.routing_corpus_examples_path)
        comparison = compare_intent(report, signals)
        payload = selected_calibration(comparison)
        if intent_calibration is not None and payload is not None:
            intent_calibration.parent.mkdir(parents=True, exist_ok=True)
            intent_calibration.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        comparison = compare(report)
    typer.echo(
        json.dumps({"report_path": report["report_path"], **comparison["summary"]}, indent=2, ensure_ascii=False)
    )
    typer.echo(render_comparison(comparison), err=True)


if __name__ == "__main__":
    app()
