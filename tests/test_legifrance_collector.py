from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from raglab.legifrance.collector import CodeCollector, html_to_text, parse_article_markdown, parse_commit_message

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _article(number: str, legi_id: str, etat: str, start: str, end: str, body: str, nota: str = "") -> str:
    lines = [
        "---",
        "Nature: Article",
        f"Numéro: {number}",
        "Type: AUTONOME",
        f"État: {etat}",
        f"Date de début: {start}",
        f"Date de fin: {end}",
        f"Identifiant: {legi_id}",
        "Origine: LEGI",
        "---",
        "",
        f"# Article {number}",
        "",
        body,
        "",
    ]
    if nota:
        lines += ["### Nota", "", nota, ""]
    lines += ["", f"## [Autres formats](https://www.tricoteuses.fr/legifrance/articles/{legi_id})", ""]
    return "\n".join(lines)


def _readme(title: str, identifier: str) -> str:
    return f"---\nIdentifiant: {identifier}\n---\n\n# {title}\n"


SECTION = "partie_legislative_nouvelle/livre_ii/section_6"


def _commit(repo: Path, date: str, message: str, files: dict[str, str | None]) -> None:
    for relative, content in files.items():
        path = repo / relative
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_DATE": f"{date}T00:00:00Z", "GIT_COMMITTER_DATE": f"{date}T00:00:00Z"}
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", "-C", str(repo)]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", message], check=True, capture_output=True, env=env)


@pytest.fixture
def code_repository(tmp_path: Path) -> Path:
    """A three-commit history: creation, then L221-20 rewritten and L221-99 repealed."""
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    _commit(
        work,
        "2016-07-01",
        "Ordonnance n° 2016-301 du 14 mars 2016 relative à la partie législative du code de la consommation\n\n"
        "Lien: https://example.org\nNature: ORDONNANCE\nIdentifiant: JORFTEXT000032209352\nNOR: EINC1602822R",
        {
            "README.md": _readme("Code de la consommation", "LEGITEXT000006069565"),
            "partie_legislative_nouvelle/README.md": _readme("Partie législative nouvelle", "LEGISCTA1"),
            "partie_legislative_nouvelle/livre_ii/README.md": _readme("Livre II : CONTRATS", "LEGISCTA2"),
            f"{SECTION}/README.md": _readme("Section 6 : Droit de rétractation", "LEGISCTA3"),
            f"{SECTION}/article_l221-18.md": _article(
                "L221-18",
                "LEGIARTI18",
                "VIGUEUR",
                "2016-07-01",
                "2999-01-01",
                "Le consommateur dispose d'un délai de quatorze jours, sauf les coûts prévus aux articles "
                "L. 221-23 à L. 221-25.<br />\n\nLe délai court à compter du jour :<br />\n\n"
                "1° De la conclusion du contrat, pour ceux mentionnés à l'article L. 221-4 ;",
            ),
            f"{SECTION}/article_l221-20.md": _article(
                "L221-20",
                "LEGIARTI20A",
                "MODIFIE",
                "2016-07-01",
                "2022-05-28",
                "Dans les conditions prévues au 2° de l'article L. 221-5, le délai est prolongé de douze mois.",
            ),
            f"{SECTION}/article_l221-99.md": _article(
                "L221-99",
                "LEGIARTI99",
                "ABROGE",
                "2016-07-01",
                "2020-01-01",
                "<table><tr><td>Prêt</td><td>Montant</td></tr></table>Article voué à disparaître.",
            ),
        },
    )
    _commit(
        work,
        "2020-01-01",
        "LOI n° 2019-1 du 1er janvier 2019 relative aux tests\n\nNature: LOI\nIdentifiant: JORFTEXT2019",
        {f"{SECTION}/article_l221-99.md": None},
    )
    _commit(
        work,
        "2022-05-28",
        "Ordonnance n° 2021-1734 du 22 décembre 2021 transposant la directive 2019/2161\n\n"
        "Nature: ORDONNANCE\nIdentifiant: JORFTEXT000044546235",
        {
            f"{SECTION}/article_l221-20.md": _article(
                "L221-20",
                "LEGIARTI20B",
                "VIGUEUR",
                "2022-05-28",
                "2999-01-01",
                "Dans les conditions prévues au 7° de l'article L. 221-5, le délai est prolongé de douze mois.",
                nota="Ces dispositions entrent en vigueur le 28 mai 2022.",
            )
        },
    )
    output = tmp_path / "out"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(output / "source.git")], check=True)
    return output


def _sidecars(output: Path) -> dict[str, dict]:
    return {
        json.loads(path.read_text(encoding="utf-8"))["legi_id"]: json.loads(path.read_text(encoding="utf-8"))
        for path in (output / "corpus").glob("*.json")
    }


def test_every_version_is_a_document_with_its_state_and_amending_texts(code_repository: Path):
    result = CodeCollector().collect(code="consommation", output_dir=code_repository, commit="HEAD")

    sidecars = _sidecars(code_repository)
    assert set(sidecars) == {"LEGIARTI18", "LEGIARTI20A", "LEGIARTI20B", "LEGIARTI99"}
    old, new = sidecars["LEGIARTI20A"], sidecars["LEGIARTI20B"]
    assert (old["etat"], old["date_debut"], old["date_fin"]) == ("MODIFIE", "2016-07-01", "2022-05-28")
    assert old["amended_by"]["jorf_id"] == "JORFTEXT000032209352"
    assert old["ended_by"]["title"].startswith("Ordonnance n° 2021-1734")
    assert (new["etat"], new["date_fin"], new["ended_by"]) == ("VIGUEUR", None, None)
    assert (new["version"], new["version_count"]) == (2, 2)
    assert [row["legi_id"] for row in new["versions"]] == ["LEGIARTI20A", "LEGIARTI20B"]
    assert new["nota"] == "Ces dispositions entrent en vigueur le 28 mai 2022."
    repealed = sidecars["LEGIARTI99"]
    assert repealed["ended_by"]["title"] == "LOI n° 2019-1 du 1er janvier 2019 relative aux tests"

    current = sidecars["LEGIARTI18"]
    assert current["code"] == "consommation"
    assert current["article_number"] == "L221-18"
    assert current["path"] == [
        "Partie législative nouvelle",
        "Livre II : CONTRATS",
        "Section 6 : Droit de rétractation",
    ]
    assert current["section_id"] == "LEGISCTA3"
    assert current["references"] == ["L221-23", "L221-24", "L221-25", "L221-4"]
    assert current["source_url"] == "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI18"
    assert "number" not in current  # reserved for Brazilian law numbers

    # The text is what the article says: heading, one paragraph per line, no version banner.
    text = (code_repository / "corpus" / "consommation_L221-18_LEGIARTI18.txt").read_text(encoding="utf-8")
    assert text.splitlines()[:3] == [
        "Code de la consommation — Article L221-18",
        "",
        "Le consommateur dispose d'un délai de quatorze jours, sauf les coûts prévus aux articles L. 221-23 à L. 221-25.",
    ]
    assert "VIGUEUR" not in text and "Nota" not in text

    stats = result["stats"]
    assert (stats["documents"], stats["articles"], stats["articles_in_force"]) == (4, 3, 2)
    assert stats["versions_by_state"] == {"VIGUEUR": 2, "MODIFIE": 1, "ABROGE": 1}
    assert stats["articles_rewritten"] == 1
    assert stats["amending_texts"] == 3
    assert stats["references_in_force"]["internal_mentions"] == 5


def test_manifest_fingerprints_every_text(code_repository: Path):
    CodeCollector().collect(code="consommation", output_dir=code_repository, commit="HEAD")
    manifest = json.loads((code_repository / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["commit_date"] == "2022-05-28"
    assert len(manifest["documents"]) == 4
    for row in manifest["documents"]:
        text = (code_repository / "corpus" / row["file_name"]).read_text(encoding="utf-8")
        assert row["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_an_earlier_commit_freezes_an_earlier_state(code_repository: Path):
    CodeCollector().collect(code="consommation", output_dir=code_repository, commit="HEAD~2")
    sidecars = _sidecars(code_repository)
    # LEGI metadata is final (L221-20 v1 says MODIFIE), but the later texts
    # are not in the history yet.
    assert set(sidecars) == {"LEGIARTI18", "LEGIARTI20A", "LEGIARTI99"}
    assert sidecars["LEGIARTI20A"]["ended_by"] is None


def test_current_versions_only(code_repository: Path):
    result = CodeCollector().collect(code="consommation", output_dir=code_repository, commit="HEAD", versions="current")
    assert set(_sidecars(code_repository)) == {"LEGIARTI18", "LEGIARTI20B"}
    assert result["stats"]["skipped"]["not_in_force"] == 2


def test_html_to_text_keeps_one_paragraph_per_line_and_table_cells():
    markup = "Premier alinéa ;<br />\n\nSecond<br/>alinéa.\n\n<table><tr><td>A</td><td>B &amp; C</td></tr></table>"
    assert html_to_text(markup) == "Premier alinéa ;\nSecond\nalinéa.\nA | B & C"


def test_parse_article_markdown_splits_body_and_nota():
    parsed = parse_article_markdown(
        _article("R212-1", "LEGIARTI1", "VIGUEUR", "2016-07-01", "2999-01-01", "Texte.", nota="Note.")
    )
    assert parsed.fields["Numéro"] == "R212-1"
    assert parsed.fields["État"] == "VIGUEUR"
    assert (parsed.title, parsed.body, parsed.nota) == ("Article R212-1", "Texte.", "Note.")


def test_commit_message_gives_the_amending_text():
    text = parse_commit_message(
        "abc", "2014-06-14", "LOI n° 2014-344\n\nModification...\nNature: LOI\nIdentifiant: JORF1"
    )
    assert (text.title, text.nature, text.jorf_id) == ("LOI n° 2014-344", "LOI", "JORF1")
    assert parse_commit_message("abc", "1970-01-01", "Création du dépôt git").title is None
    assert parse_commit_message("abc", "2013-11-17", "!!! Texte non trouvé 2013-11-17 !!!").title is None


def test_codes_without_a_pinned_repository_are_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="pas encore collectable"):
        CodeCollector().collect(code="civil", output_dir=tmp_path)
    with pytest.raises(ValueError, match="Code inconnu"):
        CodeCollector().collect(code="inexistant", output_dir=tmp_path)
