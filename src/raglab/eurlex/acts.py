"""EU compliance acts collected from EUR-Lex (CELLAR) and how they are named.

The corpus holds four base acts and a bounded set of the acts that complete
or amend them (15 in all), chosen from the CELLAR "based on" and "amends"
links (SPARQL, see docs/corpus-eurlex.md):

* GDPR, AI Act, DORA, NIS 2: the base acts;
* DORA level 2: the regulatory technical standards (RTS) on the ICT risk
  management framework, incident classification, ICT third-party policy,
  incident reporting, threat-led penetration testing, subcontracting, and
  the criticality criteria for ICT third-party providers;
* NIS 2: the implementing regulation on cybersecurity risk-management
  measures (the only one adopted);
* AI Act: the implementing regulation on the scientific panel, and the
  "Digital Omnibus on AI" (Regulation (EU) 2026/1744) that amended it, which
  is what gives the AI Act a second consolidated version;
* GDPR: the standard contractual clauses for international transfers
  (Implementing Decision (EU) 2021/914), the text compliance teams cite most.

Left out on purpose: forms and templates (DORA ITS 2024/2956, 2025/302: a few
articles around hundreds of pages of tables), adequacy decisions (one per
country, long and repetitive), procedural acts (oversight fees, joint
examination teams, AI Act proceedings). They can be added to `ACTS` later;
the collector and the rules do not depend on the list.

Consolidated versions are pinned: CELLAR publishes a new one when an act
changes, and the benchmark must keep measuring the same texts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LANGUAGES = ("fr", "en", "pt")
# CELLAR expression languages (ISO 639-2/B, as in the Accept-Language header).
CELLAR_LANGUAGES = {"fr": "fra", "en": "eng", "pt": "por"}

# Act kinds as written in a citation, per language (lowercase), and the
# CELEX sector-3 letter of each.
KIND_LETTERS = {"regulation": "R", "directive": "L", "decision": "D", "recommendation": "H"}
KIND_NAMES = {
    "fr": {
        "regulation": "règlement",
        "directive": "directive",
        "decision": "décision",
        "recommendation": "recommandation",
    },
    "en": {
        "regulation": "Regulation",
        "directive": "Directive",
        "decision": "Decision",
        "recommendation": "Recommendation",
    },
    "pt": {
        "regulation": "Regulamento",
        "directive": "Diretiva",
        "decision": "Decisão",
        "recommendation": "Recomendação",
    },
}
# Words for the units of an act, per language.
UNIT_NAMES = {
    "fr": {"article": "Article", "recital": "Considérant", "annex": "Annexe"},
    "en": {"article": "Article", "recital": "Recital", "annex": "Annex"},
    "pt": {"article": "Artigo", "recital": "Considerando", "annex": "Anexo"},
}


@dataclass(slots=True, frozen=True)
class ActSpec:
    key: str
    celex: str
    #: "regulation", "directive" or "decision"
    kind: str
    #: "base", "delegated", "implementing" or "amending"
    role: str
    #: Short names per language; the first one is used in document titles.
    names: dict[str, tuple[str, ...]]
    #: CELEX of the base act this one supplements, implements or amends.
    base: str | None = None
    #: Pinned consolidated versions ("02024R1689-20260727"), oldest first.
    consolidations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def year(self) -> int:
        return int(self.celex[1:5])

    @property
    def number(self) -> int:
        return int(self.celex[6:])

    def official_number(self, language: str = "en") -> str:
        """ "Regulation (EU) 2016/679", "directive (UE) 2022/2555"."""
        org = "EU" if language == "en" else "UE"
        return f"{KIND_NAMES[language][self.kind]} ({org}) {self.year}/{self.number}"

    def short_name(self, language: str) -> str:
        return self.names[language][0]

    def label(self, language: str) -> str:
        """Title prefix of every document of the act: "Règlement (UE)
        2016/679 (RGPD)"; the number alone when the act has no short name."""
        number = self.official_number(language)
        number = number[:1].upper() + number[1:]
        short = self.short_name(language)
        return number if short == number else f"{number} ({short})"


def _same(*names: str) -> dict[str, tuple[str, ...]]:
    return {language: tuple(names) for language in LANGUAGES}


def _numbered(kind: str, celex: str, *, delegated: bool = False, implementing: bool = False):
    """Names of an act known by its number only."""
    year, number = int(celex[1:5]), int(celex[6:])
    words = {
        "fr": {"regulation": "Règlement", "decision": "Décision"}[kind]
        + (" délégué" if delegated else " d'exécution" if implementing else "")
        + " (UE)",
        "en": ("Delegated " if delegated else "Implementing " if implementing else "")
        + {"regulation": "Regulation", "decision": "Decision"}[kind]
        + " (EU)",
        "pt": {"regulation": "Regulamento", "decision": "Decisão"}[kind]
        + (" Delegado" if delegated else " de Execução" if implementing else "")
        + " (UE)",
    }
    return {language: (f"{word} {year}/{number}",) for language, word in words.items()}


ACTS: tuple[ActSpec, ...] = (
    ActSpec(
        key="gdpr",
        celex="32016R0679",
        kind="regulation",
        role="base",
        names={
            "fr": ("RGPD", "règlement général sur la protection des données"),
            "en": ("GDPR", "General Data Protection Regulation"),
            "pt": ("RGPD", "Regulamento Geral sobre a Proteção de Dados"),
        },
        consolidations=("02016R0679-20160504",),
    ),
    ActSpec(
        key="ai_act",
        celex="32024R1689",
        kind="regulation",
        role="base",
        names={
            "fr": ("règlement sur l'IA", "règlement sur l'intelligence artificielle", "AI Act", "RIA"),
            "en": ("AI Act", "Artificial Intelligence Act"),
            "pt": ("Regulamento IA", "Regulamento da Inteligência Artificial", "AI Act"),
        },
        # 02024R1689-20240712 is the OJ text itself (and has no English
        # expression in CELLAR): only the amended version is collected.
        consolidations=("02024R1689-20260727",),
    ),
    ActSpec(
        key="dora",
        celex="32022R2554",
        kind="regulation",
        role="base",
        names={
            "fr": ("DORA", "règlement sur la résilience opérationnelle numérique"),
            "en": ("DORA", "Digital Operational Resilience Act"),
            "pt": ("DORA", "Regulamento Resiliência Operacional Digital"),
        },
        consolidations=("02022R2554-20221227",),
    ),
    ActSpec(
        key="nis2",
        celex="32022L2555",
        kind="directive",
        role="base",
        names={
            "fr": ("NIS 2", "directive NIS 2", "NIS2"),
            "en": ("NIS 2", "NIS 2 Directive", "NIS2"),
            "pt": ("NIS 2", "Diretiva NIS 2", "NIS2"),
        },
        consolidations=("02022L2555-20221227",),
    ),
    ActSpec(
        key="dora_rts_ict_risk",
        celex="32024R1774",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32024R1774", delegated=True),
        base="32022R2554",
        consolidations=("02024R1774-20240625",),
    ),
    ActSpec(
        key="dora_rts_incident_classification",
        celex="32024R1772",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32024R1772", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="dora_rts_ict_services_policy",
        celex="32024R1773",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32024R1773", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="dora_rts_incident_reporting",
        celex="32025R0301",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32025R0301", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="dora_rts_tlpt",
        celex="32025R1190",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32025R1190", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="dora_rts_subcontracting",
        celex="32025R0532",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32025R0532", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="dora_ctpp_criteria",
        celex="32024R1502",
        kind="regulation",
        role="delegated",
        names=_numbered("regulation", "32024R1502", delegated=True),
        base="32022R2554",
    ),
    ActSpec(
        key="nis2_risk_measures",
        celex="32024R2690",
        kind="regulation",
        role="implementing",
        names=_numbered("regulation", "32024R2690", implementing=True),
        base="32022L2555",
    ),
    ActSpec(
        key="ai_act_scientific_panel",
        celex="32025R0454",
        kind="regulation",
        role="implementing",
        names=_numbered("regulation", "32025R0454", implementing=True),
        base="32024R1689",
    ),
    ActSpec(
        key="ai_omnibus",
        celex="32026R1744",
        kind="regulation",
        role="amending",
        names={
            "fr": ("Règlement (UE) 2026/1744", "omnibus numérique sur l'IA"),
            "en": ("Regulation (EU) 2026/1744", "Digital Omnibus on AI"),
            "pt": ("Regulamento (UE) 2026/1744", "Omnibus Digital sobre IA"),
        },
        base="32024R1689",
    ),
    ActSpec(
        key="gdpr_scc",
        celex="32021D0914",
        kind="decision",
        role="implementing",
        names={
            "fr": ("Décision d'exécution (UE) 2021/914", "clauses contractuelles types"),
            "en": ("Implementing Decision (EU) 2021/914", "standard contractual clauses"),
            "pt": ("Decisão de Execução (UE) 2021/914", "cláusulas contratuais-tipo"),
        },
        base="32016R0679",
    ),
)

BY_KEY = {act.key: act for act in ACTS}
BY_CELEX = {act.celex: act for act in ACTS}
DEFAULT_ACTS = tuple(act.key for act in ACTS)


def get_act(key: str) -> ActSpec:
    try:
        return BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Acte inconnu: {key} (connus: {', '.join(BY_KEY)})") from exc


def celex_for(kind: str, year: int, number: int) -> str:
    """CELEX of a secondary-law act: ("regulation", 2016, 679) -> 32016R0679."""
    return f"3{year:04d}{KIND_LETTERS[kind]}{number:04d}"


def celex_label(celex: str, language: str = "en") -> str:
    """ "Regulation (EU) 2016/679" for any sector-3 CELEX, in the corpus or not."""
    act = BY_CELEX.get(celex)
    if act is not None:
        return act.official_number(language)
    letter = celex[5:6]
    kind = next((name for name, value in KIND_LETTERS.items() if value == letter), None)
    if kind is None or not celex[1:5].isdigit() or not celex[6:].isdigit():
        return celex
    year, number = int(celex[1:5]), int(celex[6:])
    union = year >= 2010
    org = ("EU" if union else "EC") if language == "en" else ("UE" if union else "CE")
    word = KIND_NAMES[language][kind]
    if year >= 2015:
        return f"{word} ({org}) {year}/{number}"
    # Before 2015 a regulation is "No 1093/2010", a directive "2013/36/EU".
    if kind == "regulation":
        no = {"en": "No", "fr": "no", "pt": "n.º"}[language]
        return f"{word} ({org}) {no} {number}/{year}"
    # Directives before 1999 carry a two-digit year: "Directive 95/46/EC".
    return f"{word} {year % 100 if year < 1999 else year:02d}/{number}/{org}"
