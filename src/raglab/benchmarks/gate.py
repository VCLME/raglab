"""Quality gate: fail when a benchmark run falls under versioned thresholds.

`benchmarks/thresholds.json` holds, per suite, the minimum acceptable value
of each metric (set from the official baseline minus a tolerance). `raglab
gate` reads a `raglab bench all` result (or runs one) and exits with a
non-zero code if any measured metric is below its floor. Metrics a run did
not compute (e.g. faithfulness in a retrieval-only CI run) are reported as
"not measured", never as passed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Check:
    suite: str
    metric: str
    floor: float
    value: float | None

    @property
    def status(self) -> str:
        if self.value is None:
            return "not_measured"
        return "pass" if self.value >= self.floor else "fail"


def load_thresholds(path: Path) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {suite: dict(metrics) for suite, metrics in payload["suites"].items()}


def evaluate(result: dict[str, Any], thresholds: dict[str, dict[str, float]]) -> list[Check]:
    checks: list[Check] = []
    by_suite = {suite["suite"]: suite for suite in result["suites"]}
    for suite_name, floors in sorted(thresholds.items()):
        summary = (by_suite.get(suite_name) or {}).get("summary", {})
        for metric, floor in sorted(floors.items()):
            value = summary.get(metric)
            checks.append(Check(suite_name, metric, float(floor), float(value) if value is not None else None))
    return checks


def failed(checks: list[Check], *, require_all: bool = False) -> bool:
    """A gate fails on any metric under its floor; with `require_all`, a
    metric that was not measured fails too."""
    return any(check.status == "fail" or (require_all and check.status == "not_measured") for check in checks)


_STATUS = {"pass": "✅ ok", "fail": "❌ sous le seuil", "not_measured": "— non mesuré"}


def render(checks: list[Check], *, label: str) -> str:
    lines = [
        f"### Porte de qualité — `{label}`",
        "",
        "| Jeu | Métrique | Seuil | Mesuré | Statut |",
        "|---|---|---|---|---|",
    ]
    for check in checks:
        value = "—" if check.value is None else f"{check.value:.3f}"
        lines.append(f"| {check.suite} | {check.metric} | {check.floor:.3f} | {value} | {_STATUS[check.status]} |")
    return "\n".join(lines)
