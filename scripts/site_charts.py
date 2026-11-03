"""Charts and the pipeline explainer for the showcase site, built from the run files.

Stdlib only. Every chart is HTML plus an inline SVG drawn in a 0-100 box with
``preserveAspectRatio="none"``: lines and whiskers stretch with the container
while dots, labels and ticks are HTML positioned in percent, so text keeps its
real size at 375 px. ``site/assets/site.js`` adds the switches, the slider and
the tooltips; without it the default view and the data tables still read.

Series colours were run through the dataviz palette validator against the
paper surface (#f9f6f2): baseline slate #4f7cc0, raglab green #0e7348.
"""

from __future__ import annotations

import html
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
METRICS = [("recall@1", "Recall@1"), ("recall@5", "Recall@5"), ("recall@10", "Recall@10"), ("mrr", "MRR")]

# The stage-by-stage story, in the order the bricks were added.
STAGE_RUNS = [
    ("baseline-v1", "Baseline v1"),
    ("hybrid-v1", "+ BM25 hybrid"),
    ("rerank-v1", "+ re-ranking"),
    ("citations-v1", "Citations only"),
    ("full-v1", "Full pipeline"),
]
SWEEP_RUNS = [("rerank-sorted-c20", 20), ("rerank-sorted-c30", 30), ("rerank-sorted-c40", 40)]


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


def cat_x(i: int, n: int) -> float:
    return (i + 0.5) / n * 100


def legend(items: list[tuple[str, str]]) -> str:
    return (
        '<ul class="legend">' + "".join(f'<li><span class="key s-{s}"></span>{esc(t)}</li>' for s, t in items) + "</ul>"
    )


def table(caption: str, head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
    body = "".join(
        "<tr>"
        + f'<th scope="row">{esc(r[0])}</th>'
        + "".join(f'<td class="num">{esc(c)}</td>' for c in r[1:])
        + "</tr>"
        for r in rows
    )
    return (
        f'<details class="chart-data"><summary>{esc(caption)}</summary>'
        f'<div class="table-wrap" tabindex="0" role="region" aria-label="{esc(caption)}">'
        f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div></details>"
    )


def switch(name: str, label: str, options: list[tuple[str, str]], default: str) -> str:
    buttons = "".join(
        f'<button type="button" data-value="{esc(v)}" aria-pressed="{"true" if v == default else "false"}">{esc(t)}</button>'
        for v, t in options
    )
    return f'<div class="switch" role="group" aria-label="{esc(label)}" data-switch="{esc(name)}">{buttons}</div>'


# ── a. Stage by stage, with 95% bootstrap intervals ──────────────────────────


def stage_values(
    run: dict[str, Any] | None, corpus: str, metric: str
) -> tuple[float | None, float | None, float | None]:
    if corpus == "reference":
        return by_type(run, "lexml_fulltext", "reference", metric), None, None
    return (
        summary(run, corpus, metric),
        summary(run, corpus, f"{metric}_ci_low"),
        summary(run, corpus, f"{metric}_ci_high"),
    )


def stage_chart(runs: dict[str, dict[str, Any]]) -> str:
    stages = [(label, name) for label, name in STAGE_RUNS if label in runs]
    if len(stages) < 2:
        return ""
    corpora = [("lexml_fulltext", "LexML"), ("piaf", "PIAF"), ("reference", "Article-number questions")]
    n = len(stages)
    panels, rows = [], []
    for corpus, corpus_name in corpora:
        for metric, metric_name in METRICS:
            values = [stage_values(runs[label], corpus, metric) for label, _ in stages]
            lows = [lo if lo is not None else v for v, lo, _ in values if v is not None]
            if not lows:
                continue
            lo = max(0.0, nice_floor(min(lows) - 0.05, 0.1))
            step = 0.1 if 1 - lo <= 0.6 else 0.2
            plot = Plot(
                ydom=(lo, 1.0),
                yticks=ticks(lo, 1.0, step, lambda v: f"{v:.1f}"),
                xticks=[(cat_x(i, n), name) for i, (_, name) in enumerate(stages)],
                xlabel="",
                ylabel=metric_name,
                height="240px",
                cats=n,
            )
            for i, ((_, name), (v, vlo, vhi)) in enumerate(zip(stages, values, strict=True)):
                if v is None:
                    continue
                ci = f", 95% interval {vlo:.3f}–{vhi:.3f}" if vlo is not None else ""
                if vlo is not None:
                    plot.whiskers.append(("main", cat_x(i, n), vlo, vhi))
                first_or_last = i in (0, n - 1)
                plot.dots.append(
                    Dot(
                        cat_x(i, n),
                        v,
                        "main",
                        f"{name}: {metric_name} {v:.3f}{ci}",
                        f"{v:.2f}" if first_or_last else "",
                        "right" if i == 0 else "left",
                    )
                )
            hidden = "" if (corpus, metric) == ("lexml_fulltext", "recall@5") else " hidden"
            panels.append(f'<div class="chart-panel" data-panel="{corpus}|{metric}"{hidden}>{plot.render()}</div>')
            for (_, name), (v, vlo, vhi) in zip(stages, values, strict=True):
                interval = f"{vlo:.3f}–{vhi:.3f}" if vlo is not None else "—"
                rows.append([f"{corpus_name}, {metric_name}, {name}", ratio(v), interval])
    controls = (
        '<div class="chart-controls">'
        + switch("corpus", "Question set", [(c, t) for c, t in corpora], "lexml_fulltext")
        + switch("metric", "Metric", METRICS, "recall@5")
        + "</div>"
    )
    return (
        '<figure class="chart" data-chart="stages" data-corpus="lexml_fulltext" data-metric="recall@5">'
        '<p class="chart-title">Each brick, measured on the same frozen questions</p>'
        f"{controls}{''.join(panels)}"
        "<figcaption>Dots are the share of questions answered from the right passage; bars are 95% bootstrap "
        "intervals over the questions (none for the article-number subset, 97 questions). “Citations only” is a "
        "comparison run: dense search plus the citation resolver, without BM25 or re-ranking.</figcaption>"
        + table("Data table", ["Run", "Value", "95% interval"], rows)
        + "</figure>"
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
    # Direct labels only on the frontier, alternating above and below so neighbours never collide.
    place = {
        p[3]: ("above" if i % 2 == 0 else "below") + ("-end" if lx(p[0]) > 70 else "") for i, p in enumerate(frontier)
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
        "axes; moving right along it buys recall with latency. Re-ranking is the expensive step.</figcaption>"
        + table("Data table", ["Run", "LexML Recall@5", "Search p50", "Frontier"], rows)
        + "</figure>"
    )


# ── c. Re-ranking candidates sweep ───────────────────────────────────────────


def sweep_chart(runs: dict[str, dict[str, Any]]) -> str:
    pts = [(n, runs[label]) for label, n in SWEEP_RUNS if label in runs]
    if len(pts) < 2:
        return ""
    ns = [n for n, _ in pts]
    lo_n, hi_n = min(ns) - 5, max(ns) + 5

    def px(n: float) -> float:
        return (n - lo_n) / (hi_n - lo_n) * 100

    xt = [(px(n), str(n)) for n in ns]
    default_i = len(pts) - 1

    def small(
        title: str, key: str, fmt: Callable[[float], str], dom: tuple[float, float], yt: list[tuple[float, str]]
    ) -> str:
        # LexML only: the hard set, where the candidates matter. PIAF stays in the readout and the table.
        plot = Plot(
            ydom=dom, yticks=yt, xticks=xt, xlabel="Candidates re-ranked", ylabel=title, height="200px", cls="is-small"
        )
        line = []
        for i, (n, run) in enumerate(pts):
            v = summary(run, "lexml_fulltext", key)
            if v is None:
                continue
            line.append((px(n), v))
            plot.dots.append(
                Dot(px(n), v, "main", f"LexML, {n} candidates: {fmt(v)}", fmt(v), "above", attrs=f' data-i="{i}"')
            )
        plot.lines.append(("main", line, ""))
        return f'<div class="sweep-cell">{plot.render()}</div>'

    recalls = [summary(r, "lexml_fulltext", "recall@5") for _, r in pts]
    lats = [summary(r, "lexml_fulltext", "latency_query_p50_ms") for _, r in pts]
    rlo = max(0.0, nice_floor(min(v for v in recalls if v is not None) - 0.05, 0.05))
    lhi = math.ceil(max(v for v in lats if v is not None) / 200) * 200
    recall_plot = small("LexML Recall@5", "recall@5", ratio, (rlo, 1.0), ticks(rlo, 1.0, 0.05, lambda v: f"{v:.2f}"))
    latency_plot = small(
        "LexML search p50", "latency_query_p50_ms", ms, (0, lhi), ticks(0, lhi, 200, lambda v: f"{v:.0f} ms")
    )
    readouts = "".join(
        f'<p class="sweep-readout" data-i="{i}"{"" if i == default_i else " hidden"}><strong>{n} candidates</strong>: '
        f"LexML Recall@5 {ratio(summary(r, 'lexml_fulltext', 'recall@5'))}, search {ms(summary(r, 'lexml_fulltext', 'latency_query_p50_ms'))} p50; "
        f"PIAF {ratio(summary(r, 'piaf', 'recall@5'))}, {ms(summary(r, 'piaf', 'latency_query_p50_ms'))}.</p>"
        for i, (n, r) in enumerate(pts)
    )
    rows = [
        [
            f"{n} candidates",
            ratio(summary(r, "lexml_fulltext", "recall@5")),
            ms(summary(r, "lexml_fulltext", "latency_query_p50_ms")),
            ratio(summary(r, "piaf", "recall@5")),
            ms(summary(r, "piaf", "latency_query_p50_ms")),
        ]
        for n, r in pts
    ]
    return (
        f'<figure class="chart" data-chart="sweep" data-sel="{default_i}">'
        '<p class="chart-title">How many candidates to re-rank</p>'
        '<label class="slider"><span>Candidates</span>'
        f'<input type="range" min="0" max="{len(pts) - 1}" step="1" value="{default_i}" '
        f'aria-valuetext="{pts[default_i][0]} candidates" data-labels="{esc(",".join(str(n) for n in ns))}">'
        f"<output>{pts[default_i][0]}</output></label>"
        f'{readouts}<div class="sweep-grid">{recall_plot}{latency_plot}</div>'
        "<figcaption>The cross-encoder reads every (question, passage) pair it is given, so fewer candidates mean "
        "less work. Twenty is clearly faster than forty for a small loss in recall; thirty loses recall yet is barely "
        "faster than forty on LexML and slower on PIAF, a reminder that one run's latency is noisy. Re-ranking pairs are sorted by length in all three.</figcaption>"
        + table("Data table", ["Run", "LexML Recall@5", "LexML p50", "PIAF Recall@5", "PIAF p50"], rows)
        + "</figure>"
    )


# ── d. Per question type, before and after ───────────────────────────────────


def types_chart(runs: dict[str, dict[str, Any]], before: str = "baseline-v1", after: str = "full-v1") -> str:
    b, a = runs.get(before), runs.get(after)
    types = [t for t in TYPE_NAMES if by_type(b, "lexml_fulltext", t, "recall@5") is not None]
    if not types or a is None:
        return ""
    n = len(types)
    plot = Plot(
        ydom=(0, 1),
        yticks=ticks(0, 1, 0.25, lambda v: f"{v * 100:.0f}%"),
        xticks=[(cat_x(i, n), TYPE_NAMES[t]) for i, t in enumerate(types)],
        xlabel="",
        ylabel="Recall@5, LexML",
        height="240px",
        cats=n,
    )
    rows = []
    for i, t in enumerate(types):
        vb, va = by_type(b, "lexml_fulltext", t, "recall@5"), by_type(a, "lexml_fulltext", t, "recall@5")
        cases = by_type(a, "lexml_fulltext", t, "cases")
        x = cat_x(i, n)
        plot.lines.append(("main", [(x, vb), (x, va)], "link"))
        plot.dots.append(
            Dot(x, vb, "base", f"{TYPE_NAMES[t]}, baseline v1: {pct(vb)}", pct(vb), "below" if va >= vb else "above")
        )
        plot.dots.append(
            Dot(x, va, "main", f"{TYPE_NAMES[t]}, full pipeline: {pct(va)}", pct(va), "above" if va >= vb else "below")
        )
        rows.append([f"{TYPE_NAMES[t]} ({int(cases) if cases else '?'} questions)", pct(vb), pct(va)])
    return (
        '<figure class="chart" data-chart="types">'
        '<p class="chart-title">Recall@5 by kind of question, before and after</p>'
        + legend([("base", "Baseline v1"), ("main", "Full pipeline")])
        + plot.render()
        + "<figcaption>Questions that cite an article number were the blind spot of dense search. The citation "
        "resolver closes most of that gap, and the other two kinds improve as well.</figcaption>"
        + table("Data table", ["Question kind", "Baseline v1", "Full pipeline"], rows)
        + "</figure>"
    )


# ── e. Recall@k curves ───────────────────────────────────────────────────────


def recall_k_chart(runs: dict[str, dict[str, Any]], before: str = "baseline-v1", after: str = "full-v1") -> str:
    b, a = runs.get(before), runs.get(after)
    if b is None or a is None:
        return ""
    ks = [1, 5, 10]

    def px(k: float) -> float:  # padded so the end dots and labels stay inside the plot
        return 4 + (k - 1) / 9 * 92

    panels, rows = [], []
    for corpus, cname in (("lexml_fulltext", "LexML"), ("piaf", "PIAF")):
        vals = {lab: [summary(r, corpus, f"recall@{k}") for k in ks] for lab, r in (("base", b), ("main", a))}
        flat = [v for vs in vals.values() for v in vs if v is not None]
        if not flat:
            continue
        lo = max(0.0, nice_floor(min(flat) - 0.05, 0.1))
        plot = Plot(
            ydom=(lo, 1),
            yticks=ticks(lo, 1, 0.1, lambda v: f"{v:.1f}"),
            xticks=[(px(k), f"k = {k}") for k in ks],
            xlabel="Passages kept (k)",
            ylabel=f"Recall@k, {cname}",
            height="240px",
        )
        for s, name in (("base", "Baseline v1"), ("main", "Full pipeline")):
            line = [(px(k), v) for k, v in zip(ks, vals[s], strict=True) if v is not None]
            plot.lines.append((s, line, ""))
            for j, (k, v) in enumerate(zip(ks, vals[s], strict=True)):
                if v is None:
                    continue
                end = f"{name} {v:.2f}" if j == len(ks) - 1 else ""
                plot.dots.append(
                    Dot(px(k), v, s, f"{name}, Recall@{k} {v:.3f}", end, "above-end" if s == "main" else "below-end")
                )
            rows.append([f"{cname}, {name}"] + [ratio(v) for v in vals[s]])
        hidden = "" if corpus == "lexml_fulltext" else " hidden"
        panels.append(f'<div class="chart-panel" data-panel="{corpus}"{hidden}>{plot.render()}</div>')
    return (
        '<figure class="chart" data-chart="recallk" data-corpus="lexml_fulltext">'
        '<p class="chart-title">Recall at 1, 5 and 10 passages</p>'
        '<div class="chart-controls">'
        + switch("corpus", "Question set", [("lexml_fulltext", "LexML"), ("piaf", "PIAF")], "lexml_fulltext")
        + "</div>"
        + legend([("base", "Baseline v1"), ("main", "Full pipeline")])
        + "".join(panels)
        + "<figcaption>The full pipeline is ahead at every k on both sets. On PIAF the gain is largest at k = 1: "
        "re-ranking moves the right passage to the top, which is what a short prompt needs.</figcaption>"
        + table("Data table", ["Run", "Recall@1", "Recall@5", "Recall@10"], rows)
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
