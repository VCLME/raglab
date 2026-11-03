"""Build the static showcase site and the README results table.

Standard library only, so it runs in CI and locally without touching the
project environment:

    python scripts/build_site.py              # writes _site/
    python scripts/build_site.py --readme     # also refreshes the README table
    python scripts/build_site.py --check      # fails if the README table is stale

Every number comes from ``benchmarks/results/*.json``. A stage listed in
``site/stages.json`` whose result file does not exist yet is shown as
"measuring": values are never filled in by hand.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import site_charts

ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = ROOT / "site"
RESULTS_DIR = ROOT / "benchmarks" / "results"
CALIBRATION = ROOT / "benchmarks" / "judge_calibration.json"
REPORT_PDF = ROOT / "docs" / "rapport" / "raglab-rapport.pdf"
README = ROOT / "README.md"

REPO_URL = "https://github.com/VCLME/raglab"
DEFAULT_SITE_URL = "https://vclme.github.io/raglab/"
MEASURING = "measuring"

README_START = "<!-- results:start -->"
README_END = "<!-- results:end -->"

SUITE_NAMES = {"piaf": "PIAF (fr)", "lexml_fulltext": "LexML (pt)"}
JUDGE_NAMES = {
    "ollama:qwen2.5:7b": "qwen2.5:7b (Ollama)",
    "llamacpp:gemma4-26b-a4b": "Gemma 4 26B-A4B (llama.cpp)",
}
TYPE_NAMES = {
    "reference": "cites an article number",
    "entity": "names an acronym or entity",
    "paraphrase": "paraphrases the passage",
}


@dataclass(frozen=True)
class Stage:
    label: str
    name: str
    change: str
    status: str


def load_stages() -> list[Stage]:
    raw = json.loads((SITE_SRC / "stages.json").read_text(encoding="utf-8"))
    return [Stage(**item) for item in raw]


def load_results() -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        runs[data.get("label", path.stem)] = data
    return runs


def suite(run: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if run is None:
        return None
    for item in run.get("suites", []):
        if item.get("suite") == name:
            return item
    return None


def metric(run: dict[str, Any] | None, suite_name: str, key: str) -> float | None:
    found = suite(run, suite_name)
    if found is None:
        return None
    value = found.get("summary", {}).get(key)
    return float(value) if value is not None else None


def by_type(run: dict[str, Any] | None, suite_name: str, qtype: str, key: str) -> float | None:
    found = suite(run, suite_name)
    if found is None:
        return None
    value = found.get("by_type", {}).get(qtype, {}).get(key)
    return float(value) if value is not None else None


def fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value / 1000:.1f} s"
    return f"{value:.0f} ms"


# Columns of the before/after table: header, how to read a run, formatter.
COLUMNS: list[tuple[str, Any]] = [
    ("PIAF Recall@5", lambda r: fmt_ratio(metric(r, "piaf", "recall@5"))),
    ("LexML Recall@5", lambda r: fmt_ratio(metric(r, "lexml_fulltext", "recall@5"))),
    ("Article-number questions Recall@5", lambda r: fmt_pct(by_type(r, "lexml_fulltext", "reference", "recall@5"))),
    ("Search latency p50", lambda r: fmt_ms(metric(r, "piaf", "latency_query_p50_ms"))),
    ("Faithfulness (PIAF / LexML)", lambda r: faithfulness(r)),
]


def faithfulness(run: dict[str, Any]) -> str:
    fr = metric(run, "piaf", "faithfulness_mean")
    pt = metric(run, "lexml_fulltext", "faithfulness_mean")
    if fr is None and pt is None:
        return "not judged"
    marker = " †" if run.get("ragas_protocol") == "legacy" else ""
    return f"{fmt_ratio(fr)} / {fmt_ratio(pt)}{marker}"


def table_rows(stages: list[Stage], runs: dict[str, dict[str, Any]]) -> list[tuple[Stage, list[str]]]:
    rows = []
    known = {stage.label for stage in stages}
    extra = [Stage(label, label, "additional run", "") for label in runs if label not in known]
    for stage in [*stages, *extra]:
        run = runs.get(stage.label)
        if run is None:
            cells = [MEASURING] * len(COLUMNS)
        else:
            cells = [read(run) for _, read in COLUMNS]
        rows.append((stage, cells))
    return rows


def markdown_table(stages: list[Stage], runs: dict[str, dict[str, Any]]) -> str:
    header = ["Stage", "What changes", *(name for name, _ in COLUMNS)]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for stage, cells in table_rows(stages, runs):
        shown = [f"*{c}*" if c == MEASURING else c for c in cells]
        name = stage.name if not stage.status else f"{stage.name} ({stage.status})"
        lines.append("| " + " | ".join([name, stage.change, *shown]) + " |")
    lines.append("")
    lines.append(
        "*Generated by `python scripts/build_site.py --readme` from "
        "[`benchmarks/results/`](benchmarks/results/). Search latency is embedding + vector search "
        "for one question, generation excluded. Faithfulness is scored on 100 answers per corpus by "
        "an independent judge (Gemma 4 26B-A4B). † Earlier judging protocol (answers from 10 chunks, "
        "judge reading truncated chunks), fixed before baseline-v1: not comparable.*"
    )
    return "\n".join(lines)


def html_table(stages: list[Stage], runs: dict[str, dict[str, Any]]) -> str:
    esc = html.escape
    head = "".join(f'<th scope="col">{esc(name)}</th>' for name, _ in COLUMNS)
    body = []
    for stage, cells in table_rows(stages, runs):
        status = f'<span class="tag">{esc(stage.status)}</span>' if stage.status else ""
        tds = "".join(
            f'<td class="pending">{esc(c)}</td>' if c == MEASURING else f'<td class="num">{esc(c)}</td>' for c in cells
        )
        body.append(
            f'<tr><th scope="row">{status}{esc(stage.name)}<span class="change">{esc(stage.change)}</span></th>{tds}</tr>'
        )
    return (
        '<div class="table-wrap" role="region" aria-label="Before/after results" tabindex="0">'
        f'<table class="results"><thead><tr><th scope="col">Stage</th>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def run_details(runs: dict[str, dict[str, Any]]) -> str:
    """One section per run: every summary metric, per-type recall, environment."""
    esc = html.escape
    if not runs:
        return '<p class="pending-note">No run has been recorded yet.</p>'
    rows_spec = [
        ("Recall@1", "recall@1", fmt_ratio),
        ("Recall@5", "recall@5", fmt_ratio),
        ("Recall@10", "recall@10", fmt_ratio),
        ("MRR", "mrr", fmt_ratio),
        ("Search latency p50", "latency_query_p50_ms", fmt_ms),
        ("Search latency p95", "latency_query_p95_ms", fmt_ms),
        ("Generation latency p50", "latency_generation_p50_ms", fmt_ms),
        ("Generation tokens/s p50", "generation_tokens_per_second_p50", lambda v: "—" if v is None else f"{v:.0f}"),
        ("Faithfulness", "faithfulness_mean", fmt_ratio),
        ("Answer relevancy", "answer_relevancy_mean", fmt_ratio),
        ("Answer correctness", "answer_correctness_mean", fmt_ratio),
    ]
    sections = []
    for label, run in runs.items():
        suites = run.get("suites", [])
        head = "".join(
            f'<th scope="col">{esc(SUITE_NAMES.get(s["suite"], s["suite"]))}'
            f'<span class="change">{s.get("total_cases", "?")} questions, {s.get("chunks", "?")} chunks</span></th>'
            for s in suites
        )
        body = []
        for title, key, fmt in rows_spec:
            values = [s.get("summary", {}).get(key) for s in suites]
            if all(v is None for v in values):
                continue
            tds = "".join(f'<td class="num">{esc(fmt(v))}</td>' for v in values)
            body.append(f'<tr><th scope="row">{esc(title)}</th>{tds}</tr>')
        types = []
        for s in suites:
            for qtype, stats in s.get("by_type", {}).items():
                types.append(
                    f'<tr><th scope="row">{esc(SUITE_NAMES.get(s["suite"], s["suite"]))}: '
                    f"{esc(TYPE_NAMES.get(qtype, qtype))}</th>"
                    f'<td class="num">{stats.get("cases", "?")}</td>'
                    f'<td class="num">{fmt_ratio(stats.get("recall@5"))}</td>'
                    f'<td class="num">{fmt_ratio(stats.get("mrr"))}</td></tr>'
                )
        type_table = ""
        if types:
            type_table = (
                '<h4>By question type</h4><div class="table-wrap" tabindex="0" role="region" '
                f'aria-label="{esc(label)} by question type"><table><thead><tr><th scope="col">Questions that…</th>'
                '<th scope="col">Cases</th><th scope="col">Recall@5</th><th scope="col">MRR</th></tr></thead>'
                f"<tbody>{''.join(types)}</tbody></table></div>"
            )
        env = run.get("environment", {})
        env_keys = ["date", "git_commit", "command", "embedding_model", "generation_model", "judge", "gpu", "pgvector"]
        env_items = "".join(
            f"<dt>{esc(k.replace('_', ' '))}</dt><dd><code>{esc(str(env[k]))}</code></dd>"
            for k in env_keys
            if env.get(k) is not None
        )
        sections.append(
            f'<section class="run" id="run-{esc(label)}"><h3><code>{esc(label)}</code></h3>'
            f'<div class="table-wrap" tabindex="0" role="region" aria-label="{esc(label)} metrics">'
            f'<table><thead><tr><th scope="col">Metric</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
            f"{type_table}"
            f'<details><summary>Environment and exact command</summary><dl class="env">{env_items}</dl></details>'
            f'<p class="source">Source: <a href="{REPO_URL}/blob/main/benchmarks/results/{esc(label)}.json">'
            f"<code>benchmarks/results/{esc(label)}.json</code></a></p></section>"
        )
    return "\n".join(sections)


def calibration_table() -> str:
    if not CALIBRATION.exists():
        return ""
    data = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    results = data.get("results", [])
    variants = [
        ("faithful", "Faithful answer recognised as faithful"),
        ("fabricated", "Fabricated answer caught"),
        ("embellished", "Invented detail added to a correct answer caught"),
        ("on_topic", "Correct answer judged relevant"),
        ("off_topic", "Answer to another question caught"),
    ]
    esc = html.escape
    head = "".join(f'<th scope="col">{esc(JUDGE_NAMES.get(r["judge"], r["judge"]))}</th>' for r in results)
    rows = []
    for key, title in variants:
        tds = "".join(f'<td class="num">{fmt_pct(r["accuracy_by_variant"].get(key))}</td>' for r in results)
        rows.append(f'<tr><th scope="row">{esc(title)}</th>{tds}</tr>')
    return (
        f'<div class="table-wrap" tabindex="0" role="region" aria-label="Judge calibration">'
        f'<table><thead><tr><th scope="col">Share of correct verdicts ({data.get("items", "?")} answers, seed {data.get("seed", "?")})</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def gpu_label(run: dict[str, Any] | None) -> str:
    """'NVIDIA GeForce RTX 3070 Ti Laptop GPU, 8192 MiB, 595.79' -> 'RTX 3070 Ti Laptop GPU, 8 GB'."""
    gpu = (run or {}).get("environment", {}).get("gpu")
    if not gpu:
        return "—"
    parts = [p.strip() for p in gpu.split(",")]
    name = parts[0].removeprefix("NVIDIA ").removeprefix("GeForce ")
    mib = next((p for p in parts[1:] if p.endswith("MiB")), None)
    return f"{name}, {int(mib.split()[0]) / 1024:.0f} GB" if mib else name


def model_name(run: dict[str, Any] | None, key: str) -> str:
    """'ollama:qwen2.5:7b (845dbda0ea48)' -> 'qwen2.5:7b'; 'BAAI/bge-reranker-v2-m3' -> 'bge-reranker-v2-m3'."""
    value = (run or {}).get(key) or (run or {}).get("environment", {}).get(key)
    if not value:
        return "—"
    value = value.split(" (")[0].removeprefix("ollama:")
    return value.rsplit("/", 1)[-1]


def headline(runs: dict[str, dict[str, Any]]) -> dict[str, str]:
    v0 = runs.get("baseline-v0")
    cache = runs.get("baseline-v0-cache")
    v1 = runs.get("baseline-v1")
    hybrid = runs.get("hybrid-v1")
    cites = runs.get("citations-v1")
    full = runs.get("full-v1")
    default = runs.get("rerank-sorted-c40")
    fast = runs.get("rerank-sorted-c20")
    ref_cases = by_type(v0, "lexml_fulltext", "reference", "cases")
    return {
        "piaf_r5_v1": fmt_ratio(metric(v1, "piaf", "recall@5")),
        "piaf_r5_full": fmt_ratio(metric(full, "piaf", "recall@5")),
        "lexml_r5_v1": fmt_ratio(metric(v1, "lexml_fulltext", "recall@5")),
        "lexml_r5_full": fmt_ratio(metric(full, "lexml_fulltext", "recall@5")),
        "ref_r5_v1": fmt_pct(by_type(v1, "lexml_fulltext", "reference", "recall@5")),
        "ref_r5_hybrid": fmt_pct(by_type(hybrid, "lexml_fulltext", "reference", "recall@5")),
        "ref_r5_cites": fmt_pct(by_type(cites, "lexml_fulltext", "reference", "recall@5")),
        "ref_r5_full": fmt_pct(by_type(full, "lexml_fulltext", "reference", "recall@5")),
        "correct_lexml_v1": fmt_ratio(metric(v1, "lexml_fulltext", "answer_correctness_mean")),
        "correct_lexml_full": fmt_ratio(metric(full, "lexml_fulltext", "answer_correctness_mean")),
        "faith_lexml_v1": fmt_ratio(metric(v1, "lexml_fulltext", "faithfulness_mean")),
        "faith_lexml_full": fmt_ratio(metric(full, "lexml_fulltext", "faithfulness_mean")),
        "latency_v1": fmt_ms(metric(v1, "piaf", "latency_query_p50_ms")),
        "latency_default": fmt_ms(metric(default, "piaf", "latency_query_p50_ms")),
        "latency_default_lexml": fmt_ms(metric(default, "lexml_fulltext", "latency_query_p50_ms")),
        "latency_fast": fmt_ms(metric(fast, "piaf", "latency_query_p50_ms")),
        "lexml_r5_fast": fmt_ratio(metric(fast, "lexml_fulltext", "recall@5")),
        "gpu_full": gpu_label(full),
        "generator_full": model_name(full, "generation_model"),
        "reranker_full": model_name(full, "rerank_model"),
        "ref_r5_v0": fmt_pct(by_type(v0, "lexml_fulltext", "reference", "recall@5")),
        "ref_cases": "—" if ref_cases is None else str(int(ref_cases)),
        "entity_r5_v0": fmt_pct(by_type(v0, "lexml_fulltext", "entity", "recall@5")),
        "piaf_r5_v0": fmt_ratio(metric(v0, "piaf", "recall@5")),
        "latency_v0": fmt_ms(metric(v0, "piaf", "latency_query_p50_ms")),
        "latency_cache": fmt_ms(metric(cache, "piaf", "latency_query_p50_ms")),
        "faith_piaf_v0": fmt_ratio(metric(v0, "piaf", "faithfulness_mean")),
    }


def render(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"unknown placeholder {{{{{key}}}}}")
        return values[key]

    return re.sub(r"\{\{\s*([a-z0-9_]+)\s*\}\}", replace, template)


def build_site(out: Path, site_url: str) -> None:
    stages = load_stages()
    runs = load_results()
    values = {
        "results_table": html_table(stages, runs),
        "chart_stages": site_charts.stage_chart(runs),
        "chart_tradeoff": site_charts.tradeoff_chart(runs, stages),
        "chart_sweep": site_charts.sweep_chart(runs),
        "chart_types": site_charts.types_chart(runs),
        "chart_recallk": site_charts.recall_k_chart(runs),
        "pipeline": site_charts.pipeline(runs, REPO_URL),
        "run_details": run_details(runs),
        "calibration_table": calibration_table(),
        "repo_url": REPO_URL,
        "site_url": site_url,
        **headline(runs),
    }
    layout = (SITE_SRC / "layout.html").read_text(encoding="utf-8")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for page in sorted((SITE_SRC / "pages").glob("*.html")):
        raw = page.read_text(encoding="utf-8")
        meta, _, body = raw.partition("\n---\n")
        fields = dict(line.split(": ", 1) for line in meta.strip().splitlines())
        page_values = {
            **values,
            "title": fields["title"],
            "description": fields["description"],
            "nav": fields.get("nav", ""),
            "path": "" if page.stem == "index" else page.name,
        }
        page_values["content"] = render(body, page_values)
        html_out = render(layout, page_values)
        if page.stem == "index":
            # On the overview, Overview and Results scroll within the page (smoothly, see style.css).
            html_out = html_out.replace('href="./" data-nav="index"', 'href="#top" data-nav="index"')
            html_out = html_out.replace('href="results.html" data-nav="results"', 'href="#results" data-nav="results"')
        for nav in ("index", "results", "method"):
            current = ' aria-current="page"' if fields.get("nav") == nav else ""
            html_out = html_out.replace(f'data-nav="{nav}"', f'data-nav="{nav}"{current}')
        (out / page.name).write_text(html_out, encoding="utf-8")
    shutil.copytree(SITE_SRC / "assets", out / "assets")
    shutil.copy2(ROOT / "docs" / "images" / "chat-welcome.png", out / "assets" / "chat-welcome.png")
    if REPORT_PDF.exists():
        shutil.copy2(REPORT_PDF, out / "raglab-report-fr.pdf")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site written to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} ({len(runs)} runs)")


def readme_with_table(text: str) -> str:
    table = markdown_table(load_stages(), load_results())
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"README.md has no {README_START} … {README_END} block")
    return pattern.sub(lambda _: f"{README_START}\n{table}\n{README_END}", text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--readme", action="store_true", help="rewrite the results table in README.md")
    parser.add_argument("--check", action="store_true", help="fail if the README results table is out of date")
    args = parser.parse_args()

    site_url = args.site_url if args.site_url.endswith("/") else args.site_url + "/"
    build_site(args.out.resolve(), site_url)

    current = README.read_text(encoding="utf-8")
    expected = readme_with_table(current)
    if args.readme and expected != current:
        README.write_text(expected, encoding="utf-8", newline="\n")
        print("README.md results table updated")
    elif args.check and expected != current:
        print("README.md results table is out of date: run python scripts/build_site.py --readme", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
