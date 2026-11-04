"""Lightweight fr / pt / en language detection: function words and diacritics.

No model and no dependency. Each language gets one point per function word
of the question found in its list and a point per diacritic or letter group
only that language uses. Words shared by French and Portuguese (de, que, a...)
are left out of both lists, so they never tip the balance. English is
detected from its function words only (the EU corpus has English versions).
"""

from __future__ import annotations

import re

from raglab.routing.schemas import LanguageDecision

# Frequent French function words, interrogatives and elided forms.
_FR_WORDS = frozenset(
    """
    le la les des du un une et est sont été être avoir ont ai au aux ce cet cette ces
    il ils elle elles je tu nous vous on leur leurs mon ma mes ton ta tes son sa ses notre votre
    qui quoi quel quelle quels quelles lequel laquelle comment pourquoi combien où quand
    dans sur sous avec sans pour par vers chez depuis pendant avant après
    pas ne plus très aussi donc car si oui non bien peut fait faire était
    est-ce qu c d l j n s t m y en
    """.split()
)

# Frequent Portuguese function words, interrogatives and contractions.
_PT_WORDS = frozenset(
    """
    o os as um uma uns umas é são foi foram ser estar está estão tem têm ter
    da do das dos na no nas nos ao aos pelo pela pelos pelas num numa dum duma
    em com sem por para sobre até desde após
    eu você vocês ele ela eles elas nós meu minha seu sua nosso nossa isso isto esse essa este esta
    qual quais quem quando onde como porque quanto quanta quantos quantas
    não sim muito também mas então lhe bem
    """.split()
)

_EN_WORDS = frozenset(
    """
    the of and is are was were what which who whom how why when where does did
    to in for with this that these those it you your my can could would should
    """.split()
)

# Letters / groups that only one of the two languages writes.
_FR_PATTERNS = [re.compile(p) for p in (r"[èëîïûùœ]", r"eau")]
_PT_PATTERNS = [re.compile(p) for p in (r"[ãõáíóú]", r"ção\b", r"ções\b", r"\w+nh[aeo]", r"\w+lh[aeo]")]

_TOKEN = re.compile(r"[a-zà-öø-ÿœ]+(?:-[a-zà-öø-ÿœ]+)*'?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        # "d'accord" -> "d", "accord": elisions count as French markers.
        if "'" in raw[:-1]:
            head, _, tail = raw.partition("'")
            tokens.extend([head, tail])
        else:
            tokens.append(raw.rstrip("'"))
    return [token for token in tokens if token]


def lexical_scores(text: str) -> dict[str, float]:
    tokens = tokenize(text)
    lowered = text.lower()
    fr = sum(token in _FR_WORDS for token in tokens) + sum(len(p.findall(lowered)) for p in _FR_PATTERNS)
    pt = sum(token in _PT_WORDS for token in tokens) + sum(len(p.findall(lowered)) for p in _PT_PATTERNS)
    en = sum(token in _EN_WORDS for token in tokens)
    return {"fr": float(fr), "pt": float(pt), "en": float(en)}


def detect_language(text: str, *, fallback: dict[str, float] | None = None) -> LanguageDecision:
    """Pick fr, pt, en, or other when the text has no marker and no fallback.

    `fallback` maps language -> similarity to its nearest labelled example; it
    decides when the text has no marker at all (a single word like "Beleza").
    """
    scores = lexical_scores(text)
    best = max(scores, key=lambda lang: scores[lang])
    ordered = sorted(scores.values(), reverse=True)
    if ordered[0] > 0 and ordered[0] > ordered[1]:
        return LanguageDecision(language=best, scores=scores, method="lexical")
    if fallback:
        rounded = {lang: round(value, 4) for lang, value in fallback.items()}
        return LanguageDecision(
            language=max(rounded, key=lambda lang: rounded[lang]), scores=rounded, method="embedding"
        )
    return LanguageDecision(language="other", scores=scores, method="lexical")
