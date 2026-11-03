"""French codes known to raglab: names used in citations, and the ones that
can be collected (`raglab legifrance fetch --code ...`).

A question or an article names a code in many ways ("code de la
consommation", "C. consom.", "code civil"): every alias maps to one slug,
which is what documents carry in their `code` metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TRICOTEUSES_CODES_URL = "https://git.tricoteuses.fr/codes"


@dataclass(slots=True, frozen=True)
class CodeSpec:
    slug: str
    title: str
    aliases: tuple[str, ...]
    #: LEGI identifier of the code (LEGITEXT...), for collectable codes.
    legitext: str | None = None
    #: Commit of the tricoteuses repository the frozen corpus was built from.
    pinned_commit: str | None = None

    @property
    def repository_url(self) -> str:
        name = re.sub(r"[^a-z0-9]+", "_", fold(self.title).lower()).strip("_")
        return f"{TRICOTEUSES_CODES_URL}/{name}.git"


CODES: dict[str, CodeSpec] = {
    spec.slug: spec
    for spec in (
        CodeSpec(
            "consommation",
            "Code de la consommation",
            ("code de la consommation", "c. consom.", "c. conso."),
            legitext="LEGITEXT000006069565",
            # State of the code on 2026-10-10 (last amending text: décret
            # n° 2026-935 du 7 octobre 2026).
            pinned_commit="77f038165bef484ad327af7b0f27258e0d8b1d15",
        ),
        CodeSpec("civil", "Code civil", ("code civil", "c. civ.")),
        CodeSpec("commerce", "Code de commerce", ("code de commerce", "c. com.")),
        CodeSpec("travail", "Code du travail", ("code du travail", "c. trav.")),
        CodeSpec("monetaire_financier", "Code monétaire et financier", ("code monétaire et financier", "c. mon. fin.")),
        CodeSpec("assurances", "Code des assurances", ("code des assurances", "c. assur.")),
        CodeSpec("penal", "Code pénal", ("code pénal", "c. pén.")),
        CodeSpec("procedure_civile", "Code de procédure civile", ("code de procédure civile",)),
        CodeSpec("procedure_penale", "Code de procédure pénale", ("code de procédure pénale",)),
        CodeSpec("sante_publique", "Code de la santé publique", ("code de la santé publique",)),
        CodeSpec("securite_sociale", "Code de la sécurité sociale", ("code de la sécurité sociale",)),
        CodeSpec(
            "construction_habitation",
            "Code de la construction et de l'habitation",
            ("code de la construction et de l'habitation",),
        ),
        CodeSpec("urbanisme", "Code de l'urbanisme", ("code de l'urbanisme",)),
        CodeSpec("environnement", "Code de l'environnement", ("code de l'environnement",)),
        CodeSpec("impots", "Code général des impôts", ("code général des impôts",)),
        CodeSpec(
            "propriete_intellectuelle", "Code de la propriété intellectuelle", ("code de la propriété intellectuelle",)
        ),
        CodeSpec(
            "postes_communications",
            "Code des postes et des communications électroniques",
            ("code des postes et des communications électroniques",),
        ),
        CodeSpec("route", "Code de la route", ("code de la route",)),
        CodeSpec("rural", "Code rural et de la pêche maritime", ("code rural et de la pêche maritime", "code rural")),
        CodeSpec("tourisme", "Code du tourisme", ("code du tourisme",)),
        CodeSpec("transports", "Code des transports", ("code des transports",)),
        CodeSpec("mutualite", "Code de la mutualité", ("code de la mutualité",)),
        CodeSpec(
            "action_sociale", "Code de l'action sociale et des familles", ("code de l'action sociale et des familles",)
        ),
        CodeSpec(
            "collectivites",
            "Code général des collectivités territoriales",
            ("code général des collectivités territoriales",),
        ),
        CodeSpec("education", "Code de l'éducation", ("code de l'éducation",)),
        CodeSpec("energie", "Code de l'énergie", ("code de l'énergie",)),
        CodeSpec("commande_publique", "Code de la commande publique", ("code de la commande publique",)),
        CodeSpec(
            "organisation_judiciaire", "Code de l'organisation judiciaire", ("code de l'organisation judiciaire",)
        ),
        CodeSpec("justice_administrative", "Code de justice administrative", ("code de justice administrative",)),
        CodeSpec(
            "relations_public_administration",
            "Code des relations entre le public et l'administration",
            ("code des relations entre le public et l'administration",),
        ),
    )
}

# Accents and typographic apostrophes folded one character for one, so a
# match position in the folded text is a position in the original.
_FOLD = str.maketrans("àâäáéèêëíîïóôöúùûüçÀÂÄÁÉÈÊËÍÎÏÓÔÖÚÙÛÜÇ’ʼ", "aaaaeeeeiiiooouuuucAAAAEEEEIIIOOOUUUUC''")


def fold(text: str) -> str:
    return text.translate(_FOLD)


def _alias_pattern(alias: str) -> str:
    words = [re.escape(word) for word in fold(alias).lower().split()]
    return r"\s+".join(words)


_ALIASES = sorted(
    ((alias, spec.slug) for spec in CODES.values() for alias in spec.aliases),
    key=lambda item: len(item[0]),
    reverse=True,  # "code rural et de la pêche maritime" before "code rural"
)
_CODE_RE = re.compile(
    "|".join(rf"(?P<c{index}>(?<!\w){_alias_pattern(alias)}(?!\w))" for index, (alias, _) in enumerate(_ALIASES)),
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class CodeMention:
    slug: str
    start: int
    end: int


def find_code_mentions(text: str) -> list[CodeMention]:
    """Every code named in `text`, in order."""
    mentions: list[CodeMention] = []
    for match in _CODE_RE.finditer(fold(text)):
        index = int(next(name for name, value in match.groupdict().items() if value is not None)[1:])
        mentions.append(CodeMention(_ALIASES[index][1], match.start(), match.end()))
    return mentions


def get_code(slug: str) -> CodeSpec:
    try:
        return CODES[slug]
    except KeyError as exc:
        raise ValueError(f"Code inconnu: {slug}. Codes connus: {', '.join(sorted(CODES))}") from exc
