from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


_INVISIBLE_CODEPOINT_RANGES: tuple[tuple[int, int], ...] = (
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x115F, 0x1160),  # Hangul fillers
    (0x17B4, 0x17B5),  # Khmer invisible vowels
    (0x180B, 0x180F),  # Mongolian variation/free-format controls
    (0x2060, 0x206F),  # word joiner, bidi isolates, and reserved controls
    (0x2800, 0x2800),  # braille blank
    (0x3164, 0x3164),  # Hangul filler
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFFA0, 0xFFA0),  # halfwidth Hangul filler
    (0xE0000, 0xE007F),  # tags and deprecated language tag
    (0xE0100, 0xE01EF),  # variation selector supplement
)


GERMAN_LANGUAGE_PREFIXES = ("de", "de-", "de_")

ENGLISH_FIELD_MARKERS: dict[str, list[tuple[str, str]]] = {
    "objective": [
        (r"\bpromote\b", "promote"),
        (r"\bproof[- ]led\b", "proof-led"),
        (r"\bwith\b", "with"),
        (r"\bwithout\b", "without"),
        (r"\bsending\b", "sending"),
        (r"\bcompany data\b", "company data"),
        (r"\bpublic ai systems\b", "public AI systems"),
        (r"\bvalidate\b", "validate"),
        (r"\bmock data\b", "mock data"),
        (r"\boutperform\b", "outperform"),
    ],
    "cta": [
        (r"^\s*book\b", "book"),
        (r"\bdiscovery call\b", "discovery call"),
        (r"\brisk audit\b", "risk audit"),
        (r"\breview\b", "review"),
    ],
    "hypothesis": [
        (r"\bcreates?\b", "creates"),
        (r"\bqualified\b", "qualified"),
        (r"\bbuyer\b", "buyer"),
        (r"\binterest\b", "interest"),
        (r"\bclicks?\b", "clicks"),
        (r"\boutperforms?\b", "outperforms"),
        (r"\bgenerates?\b", "generates"),
        (r"\bwill\b", "will"),
    ],
}


_RECENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "trend_language",
        re.compile(
            r"(?ix)(?:"
            r"\#\w*(?:trend|trending)\w*|"
            r"\btrending\b|"
            r"\b(?:latest|newest|recent|current|neueste\w*|aktuell\w*|jüngste\w*)\b"
            r"(?:\W+\w+){0,2}\W+\btrends?\b|"
            r"\btrends?\b(?:\W+\w+){0,2}\W+"
            r"\b(?:latest|newest|recent|current|neueste\w*|aktuell\w*|jüngste\w*)\b"
            r")"
        ),
    ),
    (
        "explicit_recency",
        re.compile(
            r"(?i)(?:#(?:latest|newest|recent|current|aktuell|neueste)\w*|"
            r"\b(?:latest|newest|most\s+recent|recently|currently|today|now|"
            r"nowadays|meanwhile|still|just|this\s+(?:week|month|quarter|year)|at\s+present|"
            r"as\s+we\s+speak|these\s+days|over\s+the\s+past\s+month|"
            r"neueste\w*|aktuell(?:st\w*)?|heute|jetzt|kürzlich|neuerdings|derzeit|momentan|"
            r"zurzeit|zur\s+zeit|gegenwärtig\w*|inzwischen|mittlerweile|heutzutage|"
            r"soeben|gerade|nun|noch\s+immer|in\s+letzter\s+zeit|vor\s+kurzem|neulich|"
            r"dieser\s+tage|zur\s+stunde|diese\w*\s+(?:woche|monat|quartal|jahr))\b|"
            r"\b(?:im|seit|since)\s+(?:january|januar|february|februar|march|märz|maerz|"
            r"april|may|mai|june|juni|july|juli|august|september|october|oktober|"
            r"november|december|dezember)(?:\s+20\d{2})?\b|"
            r"\b(?:as\s+of|stand\s*:?\s*(?:vom\s+)?)\s*(?:today|now|heute|jetzt|"
            r"january|januar|february|februar|march|märz|maerz|april|may|mai|"
            r"june|juni|july|juli|august|september|october|oktober|november|"
            r"december|dezember)(?:\s+20\d{2})?\b|"
            r"\b(?:as\s+of|stand\s*:?\s*(?:vom\s+)?)\s*"
            r"(?:\d{1,2}[./-]\d{1,2}[./-](?:20)?\d{2}|20\d{2})\b)"
        ),
    ),
    (
        "dated_trend_language",
        re.compile(
            r"(?ix)(?:"
            r"\b\w*trends?\w*\b.{0,50}\b(?:20\d{2}|"
            r"(?:in|im|during|for|für|vom)\s+(?:"
            r"january|januar|february|februar|march|märz|maerz|april|may|mai|"
            r"june|juni|july|juli|august|september|october|oktober|november|"
            r"december|dezember))\b|"
            r"\b(?:20\d{2}|(?:"
            r"january|januar|february|februar|march|märz|maerz|april|may|mai|"
            r"june|juni|july|juli|august|september|october|oktober|november|"
            r"december|dezember)(?:\s+20\d{2})?)\b.{0,50}\b\w*trends?\w*\b"
            r")"
        ),
    ),
    (
        "dated_assertion",
        re.compile(
            r"(?ix)(?:"
            r"\b(?:im\s+Jahr|in)\s+20\d{2}\b.{0,80}\b(?:"
            r"ist|sind|war|waren|wird|werden|nutzt|nutzen|verwendet|verwenden|"
            r"steigt|sinkt|wächst|verändert|dominiert|führt|marktführer\w*|"
            r"is|are|was|were|uses?|adopts?|rises?|falls?|grows?|changes?|"
            r"dominates?|leads?|market\s+leaders?"
            r")\b|"
            r"\b20\d{2}\b.{0,80}\b(?:marktführer\w*|market\s+leaders?|"
            r"dominiert|dominates?|führt|leads?)\b"
            r")"
        ),
    ),
    (
        "time_sensitive_subject",
        re.compile(
            r"(?ix)(?:"
            r"\b(?:current|recent)\b(?:\W+\w+){0,3}\W+"
            r"\b(?:news|report|study|data|figures|statistics|market|solution|method|update|development|"
            r"research|state|version|release|topic|insight|finding|survey|results?)\b|"
            r"\b(?:news|report|study|data|figures|statistics|market|solution|method|update|development|"
            r"research|state|version|release|topic|insight|finding|survey|results?)\b"
            r"(?:\W+\w+){0,3}\W+\b(?:current|recent)\b|"
            r"\b(?:aktuell\w*|jüngst\w*)\b(?:\W+\w+){0,3}\W+"
            r"\b(?:trend\w*|nachricht\w*|bericht\w*|studie\w*|daten|zahl\w*|lösung\w*|methode\w*|"
            r"statistik\w*|markt\w*|update\w*|entwicklung\w*|forschung\w*|stand|"
            r"version\w*|release\w*|thema\w*|erkenntnis\w*|umfrage\w*|ergebnis\w*)\b|"
            r"\b(?:trend\w*|nachricht\w*|bericht\w*|studie\w*|daten|zahl\w*|lösung\w*|methode\w*|"
            r"statistik\w*|markt\w*|update\w*|entwicklung\w*|forschung\w*|stand|"
            r"version\w*|release\w*|thema\w*|erkenntnis\w*|umfrage\w*|ergebnis\w*)\b"
            r"(?:\W+\w+){0,3}\W+\b(?:aktuell\w*|jüngst\w*)\b"
            r")"
        ),
    ),
    (
        "current_change_assertion",
        re.compile(
            r"(?ix)(?:"
            r"\baktuell\w*\b.{0,50}\b(?:steigt|sinkt|wächst|verändert|entwickelt|"
            r"zeigt|belegt|nutzt|verwenden|verwendet|dominiert)\w*\b|"
            r"\b(?:steigt|sinkt|wächst|verändert|entwickelt|zeigt|belegt|nutzt|"
            r"verwenden|verwendet|dominiert)\w*\b.{0,50}\baktuell\w*\b"
            r")"
        ),
    ),
)

_QUESTION_OPENING = re.compile(
    r"(?i)^\s*(?:welche\w*|was|wie|wo|wann|warum|wer|wessen|möchten|sollten|"
    r"können|kann|ist|sind|hat|haben|what|which|how|where|when|why|who|"
    r"should|could|can|does|do|is|are|has|have)\b"
)
_INSTRUCTION_OPENING = re.compile(
    r"(?i)^\s*(?:prüfen|prüfe|lesen|lies|starten|starte|buchen|buche|fragen|frage|"
    r"aktualisieren|aktualisiere|entdecken|entdecke|vereinbaren|vereinbare|"
    r"kontaktieren|kontaktiere|planen|plane|"
    r"check|review|read|start|book|schedule|ask|update|discover|contact|plan)\b"
)
_RECENCY_PREFIXED_CTA = re.compile(
    r"(?ix)^\s*(?:"
    r"jetzt\s+(?:(?:kostenlos|unverbindlich)\w*\s+)?"
    r"(?:erstgespräch|termin|beratungsgespräch|beratung|gespräch|demo)"
    r"\s+(?:buchen|vereinbaren)|"
    r"now\s+(?:book|schedule)\b(?:\W+\w+){0,4}"
    r")[.!]?\s*$"
)
_SCHEDULED_CONTENT = re.compile(
    r"(?ix)^\s*(?:im|in)\s+(?:january|januar|february|februar|march|märz|maerz|"
    r"april|may|mai|june|juni|july|juli|august|september|october|oktober|"
    r"november|december|dezember)(?:\s+20\d{2})?\b.{0,80}\b"
    r"(?:planen|plane|planning|plan|schedule|scheduled)\b"
)
_QUESTION_ENDING = re.compile(
    r"\?[\"'”’)\]]*\s*$"
)
_ASSERTIVE_RECENCY_PRESUPPOSITION = re.compile(
    r"(?ix)\b(?:"
    r"nachweislich|beweis\w*|führend\w*|marktführer\w*|best(?:e|er|es|en|em)|größte\w*|"
    r"latest|newest|neu(?:e|er|es|en|em)?|neueste\w*|aktuellste\w*|"
    r"vollständig|dsgvo[- ]?konform\w*|garantier\w*|verbesser\w*|spar\w*|"
    r"mehrheit|meisten|erfolgreich\w*|effektiv\w*|"
    r"proven|leading|market\s+leader|best|largest|fully|compliant|guarantee\w*|"
    r"improv\w*|sav(?:e|es|ed|ing)|majority|most|successful\w*|effective\w*"
    r")\b"
)


def _flatten_visible_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_visible_text(item))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result = []
        for item in value:
            result.extend(_flatten_visible_text(item))
        return result
    return []


def _is_unsafe_display_character(character: str) -> bool:
    codepoint = ord(character)
    category = unicodedata.category(character)
    if character in {"\t", "\n", "\r"}:
        return False
    if category in {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}:
        return True
    return any(start <= codepoint <= end for start, end in _INVISIBLE_CODEPOINT_RANGES)


def unsafe_display_codepoints(*values: Any) -> list[str]:
    """Return unsafe or invisible code points from arbitrary content payloads."""

    found: set[str] = set()
    for value in values:
        for text in _flatten_visible_text(value):
            for character in text:
                if not _is_unsafe_display_character(character):
                    continue
                codepoint = f"U+{ord(character):04X}"
                name = unicodedata.name(character, "UNNAMED OR UNASSIGNED")
                found.add(f"{codepoint} {name}")
    return sorted(found)


def has_pathological_whitespace(*values: Any) -> bool:
    """Detect display-breaking spacing, blank-line abuse, and whitespace padding."""

    for value in values:
        for text in _flatten_visible_text(value):
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            if (
                any(
                    character.isspace()
                    and character not in {" ", "\n", "\r"}
                    for character in text
                )
                or "\t" in text
                or re.search(r"[^\S\n]{2,}", normalized)
                or re.search(r"\n{3,}", normalized)
                or re.search(r"[^\S\n]+(?=\n)", normalized)
                or re.search(r"(?:^|\n)[^\S\n]+", normalized)
            ):
                return True
            if normalized.count("\n") > 20:
                return True
            if len(text) >= 40:
                whitespace = sum(character.isspace() for character in text)
                if whitespace / len(text) > 0.4:
                    return True
    return False


def _recency_segments(value: Any) -> list[str]:
    segments: list[str] = []
    for text in _flatten_visible_text(value):
        segments.extend(
            item.strip()
            for item in re.split(r"(?:\r?\n)+|(?<=[.!?])\s+", text)
            if item.strip()
        )
    return segments


def _is_non_assertive_recency_use(segment: str, marker_codes: Sequence[str]) -> bool:
    """Allow only simple recency in a clear question or instruction.

    A question-style opening without a question mark remains a declarative
    headline. A question mark alone is also not enough: rhetorical questions
    can still make a factual assertion, so strong trend or change markers always
    block. Only a narrow set of recency-prefixed booking CTAs is exempted.
    """

    if not set(marker_codes).issubset({"explicit_recency"}):
        return False

    stripped = segment.strip()
    if _ASSERTIVE_RECENCY_PRESUPPOSITION.search(stripped):
        return False
    if _QUESTION_OPENING.search(stripped):
        return bool(_QUESTION_ENDING.search(stripped))
    return bool(
        _INSTRUCTION_OPENING.search(stripped)
        or _RECENCY_PREFIXED_CTA.search(stripped)
        or _SCHEDULED_CONTENT.search(stripped)
    )


def evergreen_recency_claim_markers(content_mode: str | None, *values: Any) -> list[str]:
    """Identify unsourced recency assertions in evergreen buyer-facing text.

    Questions and clear calls to action are not factual recency claims. Generic
    process wording such as ``aktueller Prozess`` is also intentionally allowed;
    a qualifier must name a time-sensitive subject or make a change assertion.
    """

    if str(content_mode or "").strip().casefold() != "evergreen":
        return []

    markers: list[str] = []
    for value in values:
        for segment in _recency_segments(value):
            segment_markers = [
                code for code, pattern in _RECENCY_PATTERNS if pattern.search(segment)
            ]
            if _is_non_assertive_recency_use(segment, segment_markers):
                continue
            for code in segment_markers:
                if code not in markers:
                    markers.append(code)
    return markers


def evergreen_recency_claim_errors(content_mode: str | None, *values: Any) -> list[str]:
    """Return deterministic blocking errors for evergreen recency assertions."""

    return [
        "evergreen content must not make an unsourced current or trending claim "
        f"({marker})"
        for marker in evergreen_recency_claim_markers(content_mode, *values)
    ]


def is_german_language(language: str | None) -> bool:
    value = (language or "de-DE").strip().lower()
    return value == "de" or value.startswith(GERMAN_LANGUAGE_PREFIXES)


def german_market_language_errors(brief: Any) -> list[str]:
    """Return blocking errors when a German-market brief contains English copy.

    Product names such as LinkedIn, Private AI, QA, App, and WAMOCON are allowed.
    The guard focuses on phrase-level English marketing language in buyer-facing
    fields, where mixed language makes the final German output feel unfinished.
    """

    if not is_german_language(getattr(brief, "language", "de-DE")):
        return []

    errors: list[str] = []
    for field_name, markers in ENGLISH_FIELD_MARKERS.items():
        value = str(getattr(brief, field_name, "") or "")
        for pattern, label in markers:
            if re.search(pattern, value, re.IGNORECASE):
                errors.append(f"German brief contains English wording in {field_name}: {label}")
                break
    return errors
