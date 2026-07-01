from __future__ import annotations

import re
from typing import Any


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
