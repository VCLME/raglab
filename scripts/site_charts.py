"""Charts and the pipeline explainer for the showcase site, built from the run files.

Stdlib only. Every chart is HTML plus an inline SVG drawn in a 0-100 box with
``preserveAspectRatio="none"``: lines and whiskers stretch with the container
while dots, labels and ticks are HTML positioned in percent, so text keeps its
real size at 375 px. ``site/assets/site.js`` animates the results chart between
question sets, toggles its series and adds the readouts; without it the default
view still reads. Each chart carries a visually hidden data table.

Series colours were run through the dataviz palette validator against the
paper surface (#f9f6f2), all pairs: Recall@1 blue #2a78d6, Recall@5 raglab
green #0e7348, Recall@10 amber #c98500 (below 3:1, so every line is labelled at
its end); the trade-off chart keeps slate #4f7cc0 against the green.
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

esc = html.escape

SUITES = {"piaf": "PIAF (French Wikipedia)", "lexml_fulltext": "LexML (Brazilian law)"}
TYPE_NAMES = {
    "entity": "Names an acronym or entity",
    "paraphrase": "Paraphrases the passage",
    "reference": "Cites an article number",
}

# The results chart: each stage adds one brick to the previous one, in the order they were added.
RESULT_STAGES = [
    ("baseline-v1", "Baseline v1"),
    ("hybrid-v1", "+ BM25 hybrid"),
    ("rerank-v1", "+ re-ranking"),
    ("full-v1", "+ citation resolver"),
]
SHORT_STAGES = {
    "Baseline v1": "Baseline",
    "+ BM25 hybrid": "+ BM25",
    "+ re-ranking": "+ rerank",
    "+ citation resolver": "+ citations",
}
# Question sets offered by the switch; one appears as soon as a stage run has its suite.
CORPORA = [
    ("lexml_fulltext", "LexML"),
    ("piaf", "PIAF"),
    ("reference", "Article-number questions"),
    ("legi_consommation", "Code de la consommation"),
]
# Three cut-offs on one 0-1 scale. MRR stays in the tables: a fourth hue cannot clear the
# all-pairs colour-blind floor next to these three.
SERIES = [("recall@1", "Recall@1"), ("recall@5", "Recall@5"), ("recall@10", "Recall@10")]
SERIES_IDS = ["r1", "r5", "r10"]
Y_TICKS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
PLOT_HEIGHT = 320


def suite(run: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    for s in (run or {}).get("suites", []):
        if s.get("suite") == name:
            return s
    return None


def summary(run: dict[str, Any] | None, name: str, key: str) -> float | None:
    s = suite(run, name)
    return None if s is None else s.get("summary", {}).get(key)


def by_type(run: dict[str, Any] | None, name: str, qtype: str, key: str) -> float | None:
    s = suite(run, name)
    return None if s is None else s.get("by_type", {}).get(qtype, {}).get(key)


def ratio(v: float | None) -> str:
    return "—" if v is None else f"{v:.3f}"


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def ms(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms" if v >= 10 else f"{v:.1f} ms"


# ── Generic plot ──────────────────────────────────────────────────────────────


@dataclass
class Dot:
    x: float
    y: float
    series: str  # "base" or "main"
    tip: str
    label: str = ""
    label_pos: str = "above"  # above | below | right | left
    attrs: str = ""


@dataclass
class Plot:
    """A plot area with HTML ticks and dots over a stretched SVG."""

    ydom: tuple[float, float]
    yticks: list[tuple[float, str]]
    xticks: list[tuple[float, str]]  # x already in 0-100 percent
    xlabel: str
    ylabel: str
    dots: list[Dot] = field(default_factory=list)
    lines: list[tuple[str, list[tuple[float, float]], str]] = field(
        default_factory=list
    )  # (series, points in %, extra class)
    whiskers: list[tuple[str, float, float, float]] = field(default_factory=list)  # (series, x%, y_low, y_high)
    height: str = "260px"
    cls: str = ""
    cats: int = 0  # number of categories on x; 0 for a numeric axis

    def py(self, y: float) -> float:
        lo, hi = self.ydom
        return 100 - (y - lo) / (hi - lo) * 100

    def render(self) -> str:
        grid = "".join(
            f'<line x1="0" x2="100" y1="{self.py(v):.2f}" y2="{self.py(v):.2f}" class="grid"/>' for v, _ in self.yticks
        )
        lines = "".join(
            f'<polyline class="line s-{s} {extra}" points="{" ".join(f"{x:.2f},{self.py(y):.2f}" for x, y in pts)}"/>'
            for s, pts, extra in self.lines
        )
        whisk = "".join(
            f'<line class="whisker s-{s}" x1="{x:.2f}" x2="{x:.2f}" y1="{self.py(lo):.2f}" y2="{self.py(hi):.2f}"/>'
            for s, x, lo, hi in self.whiskers
        )
        dots = "".join(
            f'<button type="button" class="dot s-{d.series}" style="left:{d.x:.2f}%;top:{self.py(d.y):.2f}%" '
            f'data-tip="{esc(d.tip)}" aria-label="{esc(d.tip)}"{d.attrs}></button>'
            for d in self.dots
        )
        labels = "".join(
            f'<span class="plot-label at-{d.label_pos}" style="left:{d.x:.2f}%;top:{self.py(d.y):.2f}%" aria-hidden="true">{esc(d.label)}</span>'
            for d in self.dots
            if d.label
        )
        yt = "".join(f'<span style="top:{self.py(v):.2f}%">{esc(t)}</span>' for v, t in self.yticks)

        def edge(x: float) -> str:
            return ' class="at-start"' if x <= 0.5 else ' class="at-end"' if x >= 99.5 else ""

        xt = "".join(f'<span style="left:{x:.2f}%"{edge(x)}>{esc(t)}</span>' for x, t in self.xticks)
        return (
            f'<div class="plot {self.cls}{" is-cat" if self.cats else ""}" style="--plot-h:{self.height};--n:{self.cats or 1}">'
            f'<div class="plot-ylabel">{esc(self.ylabel)}</div>'
            f'<div class="plot-y" aria-hidden="true">{yt}</div>'
            f'<div class="plot-area"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
            f"{grid}{whisk}{lines}</svg>{dots}{labels}</div>"
            f'<div class="plot-x" aria-hidden="true">{xt}</div>'
            f'<div class="plot-xlabel">{esc(self.xlabel)}</div></div>'
        )


def nice_floor(v: float, step: float) -> float:
    return math.floor(v / step) * step


def ticks(lo: float, hi: float, step: float, fmt: Callable[[float], str]) -> list[tuple[float, str]]:
    out, v = [], lo
    while v <= hi + 1e-9:
        out.append((round(v, 6), fmt(v)))
        v += step
    return out


def legend(items: list[tuple[str, str]]) -> str:
    return (
        '<ul class="legend">' + "".join(f'<li><span class="key s-{s}"></span>{esc(t)}</li>' for s, t in items) + "</ul>"
    )


def sr_table(caption: str, head: list[str], rows: list[list[str]]) -> str:
    """A data table for screen readers only: the charts' text alternative."""
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
    body = "".join(
        "<tr>" + f'<th scope="row">{esc(r[0])}</th>' + "".join(f"<td>{esc(c)}</td>" for c in r[1:]) + "</tr>"
        for r in rows
    )
    # Wrapped: a table grows to fit its cells, so the clipping goes on a block around it.
    return (
        f'<div class="sr-only"><table><caption>{esc(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def switch(name: str, label: str, options: list[tuple[str, str]], default: str) -> str:
    buttons = "".join(
        f'<button type="button" data-value="{esc(v)}" aria-pressed="{"true" if v == default else "false"}">{esc(t)}</button>'
        for v, t in options
    )
    return f'<div class="switch" role="group" aria-label="{esc(label)}" data-switch="{esc(name)}">{buttons}</div>'


# ── a. The results chart: every stage, three cut-offs, one question set at a time ──


def corpus_values(run: dict[str, Any] | None, corpus: str, metric: str) -> list[float] | None:
    """[value, ci_low, ci_high] for a suite, [value] for the article-number subset, None if absent."""
    if corpus == "reference":
        v = by_type(run, "lexml_fulltext", "reference", metric)
        return None if v is None else [round(v, 4)]
    v = summary(run, corpus, metric)
    if v is None:
        return None
    lo, hi = summary(run, corpus, f"{metric}_ci_low"), summary(run, corpus, f"{metric}_ci_high")
    return [round(v, 4)] if lo is None or hi is None else [round(v, 4), round(lo, 4), round(hi, 4)]


def corpus_cases(runs: list[dict[str, Any] | None], corpus: str) -> int | None:
    for run in runs:
        if corpus == "reference":
            n = by_type(run, "lexml_fulltext", "reference", "cases")
        else:
            n = (suite(run, corpus) or {}).get("total_cases")
        if n:
            return int(n)
    return None


def stage_x(i: int, n: int) -> float:
    return 6 + i / max(n - 1, 1) * 88


def dodge(ys: list[tuple[str, float]], height: float, gap: float = 18) -> dict[str, float]:
    """Spread end labels (y in % of the plot height) so no two sit closer than ``gap`` pixels."""
    placed: dict[str, float] = {}
    last = -1e9
    for key, y in sorted(ys, key=lambda p: p[1]):
        px = max(y / 100 * height, last + gap)
        placed[key] = px / height * 100
        last = px
    return placed


def results_chart(runs: dict[str, dict[str, Any]]) -> str:
    stages = [(label, name) for label, name in RESULT_STAGES if label in runs]
    if len(stages) < 2:
        return ""
    stage_runs = [runs[label] for label, _ in stages]
    corpora = []
    for key, name in CORPORA:
        values = {m: [corpus_values(r, key, m) for r in stage_runs] for m, _ in SERIES}
        if any(v for vs in values.values() for v in vs):
            corpora.append({"key": key, "name": name, "cases": corpus_cases(stage_runs, key), "values": values})
    if not corpora:
        return ""
    data = {
        "stages": [name for _, name in stages],
        "series": [{"key": k, "name": n, "id": sid} for (k, n), sid in zip(SERIES, SERIES_IDS, strict=True)],
        "corpora": corpora,
    }
    first = corpora[0]
    n = len(stages)

    def py(v: float) -> float:
        return 100 - v * 100

    # Static render of the default view: what reads without JS, and what the script animates from.
    grid = "".join(f'<line x1="0" x2="100" y1="{py(v):.2f}" y2="{py(v):.2f}" class="grid"/>' for v in Y_TICKS)
    paths, dots, ends, whiskers = [], [], [], []
    end_ys = []
    for (key, _), sid in zip(SERIES, SERIES_IDS, strict=True):
        vals = first["values"][key]
        pts = [(stage_x(i, n), py(v[0])) for i, v in enumerate(vals) if v]
        d = " ".join(f"{'M' if j == 0 else 'L'}{x:.2f},{y:.2f}" for j, (x, y) in enumerate(pts))
        paths.append(f'<path class="line s-{sid}" data-series="{sid}" d="{d}"/>')
        for i, v in enumerate(vals):
            style = f"left:{stage_x(i, n):.2f}%;top:{py(v[0]):.2f}%" if v else "display:none"
            dots.append(f'<span class="mark s-{sid}" data-series="{sid}" data-col="{i}" style="{style}"></span>')
            lo, hi = (py(v[1]), py(v[2])) if v and len(v) == 3 else (0, 0)
            whiskers.append(
                f'<line class="whisker s-{sid}" data-series="{sid}" data-col="{i}" x1="{stage_x(i, n):.2f}" '
                f'x2="{stage_x(i, n):.2f}" y1="{lo:.2f}" y2="{hi:.2f}"/>'
            )
        last = next((v for v in reversed(vals) if v), None)
        if last:
            end_ys.append((sid, py(last[0])))
    placed = dodge(end_ys, PLOT_HEIGHT)
    for (key, name), sid in zip(SERIES, SERIES_IDS, strict=True):
        last = next((v for v in reversed(first["values"][key]) if v), None)
        value = f"{last[0]:.2f}" if last else ""
        top = placed.get(sid, 0)
        ends.append(
            f'<span class="end-label" data-series="{sid}" style="top:{top:.2f}%"><span class="end-key s-{sid}"></span>'
            f'<span class="end-name"><span class="end-pre">Recall</span>{esc(name.removeprefix("Recall"))}</span> '
            f"<b>{value}</b></span>"
        )
    cols = "".join(
        f'<button type="button" class="col" data-col="{i}" style="left:{stage_x(i, n):.2f}%" '
        f'aria-label="{esc(name)}"></button>'
        for i, (_, name) in enumerate(stages)
    )
    yt = "".join(f'<span style="top:{py(v):.2f}%">{v:.1f}</span>' for v in Y_TICKS)
    xt = "".join(
        f'<span style="left:{stage_x(i, n):.2f}%"><span class="long">{esc(name)}</span>'
        f'<span class="short">{esc(SHORT_STAGES.get(name, name))}</span></span>'
        for i, (_, name) in enumerate(stages)
    )
    plot = (
        f'<div class="plot results-plot" style="--plot-h:{PLOT_HEIGHT}px">'
        f'<div class="plot-y" aria-hidden="true">{yt}</div>'
        '<div class="plot-area">'
        f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
        f'{grid}<g class="whiskers">{"".join(whiskers)}</g>{"".join(paths)}</svg>'
        f'<span class="crosshair" aria-hidden="true"></span>'
        f'<div class="marks" aria-hidden="true">{"".join(dots)}</div>'
        f'<div class="ends" aria-hidden="true">{"".join(ends)}</div>'
        f'<div class="cols">{cols}</div>'
        '<div class="readout" aria-hidden="true" hidden></div></div>'
        f'<div class="plot-x" aria-hidden="true">{xt}</div></div>'
    )
    legend_buttons = "".join(
        f'<button type="button" class="s-{sid}" data-series="{sid}" aria-pressed="true">'
        f'<span class="key"></span>{esc(name)}</button>'
        for (_, name), sid in zip(SERIES, SERIES_IDS, strict=True)
    )
    controls = (
        '<div class="chart-controls">'
        + switch("corpus", "Question set", [(c["key"], c["name"]) for c in corpora], first["key"])
        + f'<div class="legend" role="group" aria-label="Series shown">{legend_buttons}</div>'
        + "</div>"
    )
    tables = "".join(
        sr_table(
            f"{c['name']}, {c['cases'] or '?'} questions: recall by stage"
            + ("" if c["key"] == "reference" else ", with 95% bootstrap intervals"),
            ["Stage", *(name for _, name in SERIES)],
            [
                [stage]
                + [
                    "—" if not v else f"{v[0]:.3f}" + (f" ({v[1]:.3f}–{v[2]:.3f})" if len(v) == 3 else "")
                    for v in (c["values"][key][i] for key, _ in SERIES)
                ]
                for i, (_, stage) in enumerate(stages)
            ],
        )
        for c in corpora
    )
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return (
        f'<figure class="chart results-chart" data-chart="results" data-corpus="{first["key"]}">'
        '<p class="chart-title">Share of questions whose answer passage is retrieved, stage by stage</p>'
        f'<p class="chart-sub" aria-live="polite">{esc(first["name"])}: {first["cases"] or "?"} frozen questions</p>'
        f"{controls}{plot}"
        "<figcaption>Each stage adds one brick to the one before, measured on the same frozen questions. "
        "Recall@k counts a question as found when its answer passage is in the first k retrieved chunks. "
        "Hover or focus a stage for the values and their 95% bootstrap intervals (none for the article-number "
        "subset, a slice of LexML).</figcaption>"
        f"{tables}"
        f'<script type="application/json" class="chart-json">{payload}</script>'
        "</figure>"
    )


# ── b. Quality against latency, with the Pareto frontier ────────────────────


def tradeoff_chart(runs: dict[str, dict[str, Any]], stages: list[Any]) -> str:
    points = []
    for st in stages:
        if st.label in ("baseline-v0", "baseline-v0-cache"):
            continue  # earlier protocol (approximate HNSW search): not comparable
        run = runs.get(st.label)
        r5 = summary(run, "lexml_fulltext", "recall@5")
        lat = summary(run, "lexml_fulltext", "latency_query_p50_ms")
        if r5 is not None and lat:
            points.append((lat, r5, st.name, st.label))
    if len(points) < 3:
        return ""
    xmin, xmax = (
        10 ** math.floor(math.log10(min(p[0] for p in points))),
        10 ** math.ceil(math.log10(max(p[0] for p in points))),
    )

    def lx(v: float) -> float:
        return (math.log10(v) - math.log10(xmin)) / (math.log10(xmax) - math.log10(xmin)) * 100

    ylo = max(0.0, nice_floor(min(p[1] for p in points) - 0.05, 0.1))
    xt, v = [], xmin
    while v <= xmax:
        xt.append((lx(v), ms(v)))
        v *= 10
    # Pareto frontier: no other run is both faster and better.
    frontier = sorted(
        (p for p in points if not any(q[0] <= p[0] and q[1] >= p[1] and q != p for q in points)), key=lambda p: p[0]
    )
    plot = Plot(
        ydom=(ylo, 1.0),
        yticks=ticks(ylo, 1.0, 0.1, lambda v: f"{v:.1f}"),
        xticks=xt,
        xlabel="Search latency p50, LexML (log scale)",
        ylabel="LexML Recall@5",
        height="300px",
    )
    steps: list[tuple[float, float]] = []
    for i, (lat, r5, _, _) in enumerate(frontier):
        if i:
            steps.append((lx(lat), frontier[i - 1][1]))
        steps.append((lx(lat), r5))
    plot.lines.append(("main", steps, "frontier"))
    # Direct labels only on the frontier. Near the right edge they end at their dot, alternating above and
    # below from the last run so close neighbours never collide; elsewhere they sit above, clear of the steps.
    place = {
        p[3]: ("above-end" if (len(frontier) - 1 - i) % 2 == 0 else "below-end") if lx(p[0]) > 70 else "above"
        for i, p in enumerate(frontier)
    }
    for lat, r5, name, label in points:
        front = label in place
        plot.dots.append(
            Dot(
                lx(lat),
                r5,
                "main" if front else "base",
                f"{name}: Recall@5 {r5:.3f}, {ms(lat)} p50" + (" (on the frontier)" if front else ""),
                name if front else "",
                place.get(label, "above"),
            )
        )
    rows = [[name, ratio(r5), ms(lat), "yes" if label in place else "no"] for lat, r5, name, label in sorted(points)]
    return (
        '<figure class="chart" data-chart="tradeoff">'
        '<p class="chart-title">What each gain costs in search time</p>'
        + legend([("main", "On the frontier: nothing is both faster and better"), ("base", "Dominated run")])
        + plot.render()
        + "<figcaption>Each dot is a recorded run. The step line joins the runs no other run beats on both "
        "axes; moving right along it buys recall with latency. Re-ranking is the expensive step: twenty "
        "candidates instead of forty is clearly faster for a small loss in recall.</figcaption>"
        + sr_table(
            "Every run: LexML Recall@5 against search latency",
            ["Run", "LexML Recall@5", "Search p50", "Frontier"],
            rows,
        )
        + "</figure>"
    )


# ── Pipeline explainer ───────────────────────────────────────────────────────


def pipeline(runs: dict[str, dict[str, Any]], repo_url: str) -> str:
    v1, hyb, rr, cit, full = (runs.get(k) for k in ("baseline-v1", "hybrid-v1", "rerank-v1", "citations-v1", "full-v1"))
    default = runs.get("rerank-sorted-c40") or full
    lx, pf = "lexml_fulltext", "piaf"

    def ref(r: dict[str, Any] | None) -> str:
        return pct(by_type(r, lx, "reference", "recall@5"))

    def r5(r: dict[str, Any] | None, s: str) -> str:
        return ratio(summary(r, s, "recall@5"))

    stages = [
        (
            "question",
            "Question",
            "",
            "The question typed in the chat, sent with the chosen corpus and index.",
            "Every stage below works on this same text.",
            "",
        ),
        (
            "citation",
            "Citation resolver",
            "",
            "Spots a law-article reference in the question (“art. 49 da Lei 8.078”) with regular expressions.",
            "When an article is cited, searching the whole corpus drowns it among similar texts: the search is restricted to that law and the article goes first.",
            f"Article-number questions: {ref(v1)} → {ref(cit)} found in the top 5 with the resolver alone, {ref(full)} in the full pipeline. "
            f"Cost: {ms(summary(full, lx, 'latency_citation_p50_ms'))} p50.",
        ),
        (
            "dense",
            "Vector search",
            "parallel",
            "An embedding model turns the question into a vector; pgvector compares it with every indexed passage and keeps the closest.",
            "Finds passages about the topic even when they use other words.",
            f"The baseline: Recall@5 {r5(v1, pf)} on PIAF, {r5(v1, lx)} on LexML, {ms(summary(v1, pf, 'latency_query_p50_ms'))} p50 on PIAF.",
        ),
        (
            "bm25",
            "BM25",
            "parallel",
            "Classic full-text search in PostgreSQL: scores passages by the exact words of the question and how rare they are.",
            "Embeddings miss precise terms (acronyms, proper names) that BM25 always finds.",
            f"With fusion: PIAF Recall@5 {r5(v1, pf)} → {r5(hyb, pf)}, LexML {r5(v1, lx)} → {r5(hyb, lx)}; "
            f"article-number questions unchanged ({ref(hyb)}). Its real value is a better pool for re-ranking.",
        ),
        (
            "graph",
            "Citation graph",
            "parallel",
            "A third branch that follows the references between articles in a Neo4j graph built at indexing time.",
            "The answer is often in the article that the retrieved one cites, not in the retrieved one itself.",
            "In measurement (phase 9.9): no result yet, so nothing is claimed.",
        ),
        (
            "fusion",
            "RRF fusion",
            "",
            "Merges the rankings into one with Reciprocal Rank Fusion.",
            "Gets the strengths of each search without comparing scores on different scales.",
            f"Cost: {ms(summary(full, lx, 'latency_fusion_p50_ms'))} p50.",
        ),
        (
            "rerank",
            "Re-ranking",
            "",
            f"A cross-encoder ({(full or {}).get('rerank_model', 'cross-encoder').rsplit('/', 1)[-1]}) reads each (question, passage) pair and re-orders the {(default or {}).get('rerank_candidates', '')} best candidates.",
            "More accurate than search but too slow for the whole corpus, so it only sees the candidates.",
            f"On top of hybrid search: LexML Recall@5 {r5(hyb, lx)} → {r5(rr, lx)}, PIAF {r5(hyb, pf)} → {r5(rr, pf)}. "
            f"The largest gain and the largest cost: {ms(summary(default, lx, 'latency_rerank_p50_ms'))} p50 on LexML.",
        ),
        (
            "prompt",
            "Prompt",
            "",
            f"Assembles the instructions, the question and the top {(full or {}).get('top_k', '')} passages with their rank.",
            "It is what forces the model to answer only from the sources, cite them, or say the answer is not in the documents.",
            "",
        ),
        (
            "llm",
            "Local LLM",
            "",
            f"{(full or {}).get('environment', {}).get('generation_model', 'A local model').split(' (')[0].removeprefix('ollama:')} on Ollama writes the answer, token by token, on the same machine.",
            "Turns raw passages into a sourced answer; the most expensive stage in time and GPU.",
            f"Faithfulness to the passages: {ratio(summary(full, pf, 'faithfulness_mean'))} (PIAF) and {ratio(summary(full, lx, 'faithfulness_mean'))} (LexML); "
            f"{summary(full, lx, 'generation_tokens_per_second_p50') or 0:.0f} tokens/s, {ms(summary(full, lx, 'latency_generation_p50_ms'))} p50 per answer on LexML.",
        ),
        (
            "answer",
            "Answer",
            "",
            "The answer with clickable citations to the passages it used.",
            "Every claim can be checked against its source.",
            f"Answer correctness on LexML, judged by another model family: {ratio(summary(v1, lx, 'answer_correctness_mean'))} → {ratio(summary(full, lx, 'answer_correctness_mean'))}.",
        ),
    ]

    def node(sid: str, name: str) -> str:
        chip = '<span class="stage-chip">in measurement</span>' if sid == "graph" else ""
        return (
            f'<button type="button" class="stage" id="stage-btn-{sid}" data-stage="{sid}" aria-expanded="false" '
            f'aria-controls="stage-{sid}">{esc(name)}{chip}</button>'
        )

    flow, parallel = [], []
    for sid, name, kind, *_ in stages:
        if kind == "parallel":
            parallel.append(node(sid, name))
            continue
        if parallel:
            flow.append(
                '<div class="flow-parallel" role="group" aria-label="Run in parallel">' + "".join(parallel) + "</div>"
            )
            parallel = []
        flow.append(node(sid, name))
    arrow = '<span class="flow-arrow" aria-hidden="true"></span>'
    panels = "".join(
        f'<section class="stage-panel" id="stage-{sid}" aria-labelledby="stage-btn-{sid}">'
        f"<h3>{esc(name)}</h3><dl>"
        f"<div><dt>What it does</dt><dd>{esc(what)}</dd></div>"
        f"<div><dt>Why</dt><dd>{esc(why)}</dd></div>"
        + (f"<div><dt>Measured</dt><dd>{esc(measured)}</dd></div>" if measured else "")
        + "</dl></section>"
        for sid, name, _, what, why, measured in stages
    )
    return (
        '<div class="pipeline" data-pipeline>'
        f'<div class="flow">{arrow.join(flow)}</div>'
        f'<div class="stage-panels">{panels}</div></div>'
    )
