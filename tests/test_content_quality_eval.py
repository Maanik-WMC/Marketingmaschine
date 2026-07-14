from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from marketing_machine.content_quality import (
    DIMENSION_WEIGHTS,
    MAX_REFINEMENT_ATTEMPTS,
    build_refinement_request,
    evaluate_content_payload,
    evaluate_content_quality,
    failed_check_codes,
    normalize_content_candidate,
)
from marketing_machine.quality import evergreen_recency_claim_markers
from marketing_machine.storage import JsonStore


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "content_quality" / "golden_pass_k1_k5.json"
CLI_PATH = ROOT / "scripts" / "evaluate_content_quality.py"


def _golden_briefs() -> list[dict[str, Any]]:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [copy.deepcopy(item["brief"]) for item in payload["items"]]


_TREND_URLS = [
    "https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln",
    "https://glossary.istqb.org/de_DE/search/testautomatisierung",
]


def _current_trend_candidate() -> dict[str, Any]:
    candidate = _golden_briefs()[0]
    topic = "Aktuell wird Testautomatisierung mit zwei unabhängigen Fachquellen eingeordnet."
    candidate.update(
        {
            "content_mode": "current_trend",
            "trend_run_id": "trusted-test-trend-run-k1",
            "trend_id": "trusted-test-trend-k1",
            "trend_summary": topic,
            "trend_verification_status": "verified_recent",
            "trend_sources": list(_TREND_URLS),
            "citations": [
                {
                    "url": _TREND_URLS[0],
                    "label": "Qytera: Testautomatisierung",
                    "supports": topic,
                },
                {
                    "url": _TREND_URLS[1],
                    "label": "ISTQB Glossar",
                    "supports": topic,
                },
            ],
        }
    )
    return candidate


def _trusted_trend_run(
    candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    published_at = checked_at - timedelta(days=1)
    topic = str(candidate["trend_summary"])
    citations = [
        {
            **dict(item),
            "title": str(item.get("label", "")),
            "snippet": topic,
            "published": published_at.isoformat(),
            "retrieved": checked_at.isoformat(),
        }
        for item in candidate["citations"]
    ]
    return {
        "id": candidate["trend_run_id"],
        "campaigns": [
            {
                "campaign": {"id": candidate["campaign_id"]},
                "trends": [
                    {
                        "id": candidate["trend_id"],
                        "topic": topic,
                        "source_urls": list(candidate["trend_sources"]),
                        "citations": citations,
                        "verification": {
                            "status": "verified_recent",
                            "verified": True,
                            "last_checked_at": checked_at.isoformat(),
                        },
                    }
                ],
            }
        ],
    }


_GOLDEN_TREND_RUN = _trusted_trend_run(_current_trend_candidate())


def _trusted_golden_resolver(run_id: str) -> Mapping[str, Any] | None:
    if run_id != _GOLDEN_TREND_RUN["id"]:
        return None
    return copy.deepcopy(_GOLDEN_TREND_RUN)


def _report(candidate: dict[str, Any]) -> dict[str, Any]:
    return evaluate_content_quality(
        candidate,
        repo_root=ROOT,
        trend_run_resolver=_trusted_golden_resolver,
    )


def test_golden_ai_outputs_for_all_five_campaigns_are_release_ready() -> None:
    report = evaluate_content_payload(
        {"items": _golden_briefs()},
        repo_root=ROOT,
    )

    assert report["release_ready"] is True
    assert report["summary"] == {"total": 5, "passed": 5, "failed": 0}
    assert sum(DIMENSION_WEIGHTS.values()) == 100.0
    assert [item["campaign_id"] for item in report["results"]] == [
        "k1",
        "k2",
        "k3",
        "k4",
        "k5",
    ]
    for item in report["results"]:
        assert item["overall_score"] == 100.0
        assert item["hard_blockers"] == []
        assert item["critique"] == []
        assert item["refinement"]["external_ai_called"] is False
        assert sum(
            float(dimension["weight"])
            for dimension in item["dimensions"].values()
        ) == 100.0


def test_committed_golden_corpus_is_clock_independent_evergreen() -> None:
    for candidate in _golden_briefs():
        assert candidate.get("content_mode", "evergreen") == "evergreen"
        assert not candidate.get("trend_run_id")
        assert not candidate.get("trend_id")
        assert not candidate.get("trend_summary")
        assert not candidate.get("trend_sources")
        assert not candidate.get("trend_verification_status")
        assert not candidate.get("citations")


def test_fallback_and_missing_ai_provenance_are_hard_failures() -> None:
    candidate = _golden_briefs()[1]
    candidate["generation"].update(
        {
            "status": "deterministic_fallback",
            "provider": "deterministic_rules",
            "model": "wamocon-safe-copy-v1",
            "fallback_used": True,
            "fallback_reason": "generation_failed",
            "error": "generation_failed",
            "structured_output_mode": "deterministic",
        }
    )

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "ai_provenance.ai_generated_status" in failures
    assert "ai_provenance.no_fallback" in failures
    assert "ai_provenance.provider_and_model" in failures
    assert "ai_provenance.no_generation_error" in failures
    assert report["refinement"]["required"] is True


def test_campaign_audience_offer_and_cross_campaign_mix_fail_closed() -> None:
    candidate = _golden_briefs()[0]
    candidate["persona"] = "Bewerber und B2B-Entscheider"
    candidate["cta"] = "Team kennenlernen"
    candidate["public_copy"] += "\n\nSokrates Private AI"

    failures = failed_check_codes(_report(candidate))

    assert "campaign_audience_offer_fit.canonical_persona" in failures
    assert "campaign_audience_offer_fit.canonical_offer" in failures
    assert "campaign_audience_offer_fit.no_cross_campaign_mix" in failures


def test_raw_technical_terms_and_incomplete_reel_fail() -> None:
    candidate = _golden_briefs()[2]
    candidate["reel_output"]["idea"] += " API JSON Payload"
    candidate["reel_output"]["script"] = candidate["reel_output"]["script"][:1]
    candidate["reel_output"]["shot_list"] = []

    failures = failed_check_codes(_report(candidate))

    assert "german_business_clarity.no_raw_technical_terms" in failures
    assert "format_completeness.reel_script" in failures
    assert "format_completeness.shot_list" in failures


@pytest.mark.parametrize(
    ("campaign_index", "field", "value"),
    [
        (0, "channel_copy.body", "Prüfhinweis. " * 500),
        (2, "reel_output.script", ["Produktionsschritt"] * 20),
        (3, "reel_output.shot_list", ["Geplante Einstellung"] * 20),
    ],
)
def test_stored_content_cannot_bypass_generator_schema_bounds(
    campaign_index: int,
    field: str,
    value: Any,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    container, key = field.split(".", maxsplit=1)
    candidate[container][key] = value

    failures = failed_check_codes(_report(candidate))

    assert "format_completeness.schema_bounds" in failures


def test_invented_citation_and_unsupported_number_fail_grounding() -> None:
    candidate = _current_trend_candidate()
    candidate["citations"][0]["url"] = "https://invented-source.com/unsupported-claim"
    candidate["public_copy"] += "\n\n97 Prozent bessere Ergebnisse."
    candidate["channel_copy"]["body"] += " 97 Prozent bessere Ergebnisse."

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.citation_allowlist" in failures
    assert "source_grounding.no_unsupported_quantities" in failures


@pytest.mark.parametrize(
    ("campaign_index", "unsupported_claim"),
    [
        (0, "Das Audit verhindert Freigabefehler."),
        (1, "Sokrates verhindert Datenlecks und schützt Geschäftsgeheimnisse."),
        (2, "LFA verbessert die Ausbildung jeden Tag."),
        (3, "Das Team arbeitet immer vollständig remote."),
        (4, "Das Portfolio lässt sich nahtlos an Ihre Systeme anbinden."),
    ],
)
def test_direct_quality_tampering_cannot_add_an_unapproved_factual_claim(
    campaign_index: int,
    unsupported_claim: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    reel = candidate["reel_output"]
    if reel.get("caption"):
        original = str(reel["caption"])
        replacement = f"{original} {unsupported_claim}"
        reel["caption"] = replacement
        candidate["channel_copy"]["caption"] = replacement
    else:
        original = str(candidate["channel_copy"]["body"])
        replacement = f"{original} {unsupported_claim}"
        candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = str(candidate["public_copy"]).replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.exact_public_claim_contract" in failures


def test_public_copy_only_tampering_fails_the_exact_render_contract() -> None:
    candidate = _golden_briefs()[0]
    candidate["public_copy"] += "\n\nDas Audit verhindert Freigabefehler."

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize(
    "claim",
    [
        "Der aktuelle Trend zeigt eine klare Veränderung.",
        "Diese Woche steigt die Nachfrage.",
        "Heute nutzen Unternehmen diese Methode.",
        "Derzeit verändert KI den Markt.",
        "Die neuesten Zahlen belegen das.",
        "The latest trend shows a clear change.",
        "Recent data proves it.",
        "Currently the market is changing.",
        "Unternehmen sparen jetzt Zeit.",
        "Kürzlich hat sich der Markt verändert.",
        "As of 2026, this is the preferred method.",
        "Entdecken Sie den neuesten Trend: Unternehmen sparen heute Zeit.",
        "Wussten Sie, dass der aktuelle Trend den Markt verändert?",
        "Der aktuelle Trend verändert den Markt – sind Sie bereit?",
        "Wie LFA heute Ausbildung verbessert",
        "How LFA improves training today",
        "Wie LFA aktuell die Ausbildung verbessert",
        "How LFA currently improves training",
        "Die Ausbildungstrends 2026 verändern den Markt",
        "Training trends 2026 change the market",
        "Die Ausbildungstrends im Juli verändern den Markt",
        "Training trends in July change the market",
        "Juli: Ausbildungstrends verändern den Markt",
        "July training trends change the market",
        "2026 training trends change the market",
        "März 2026: Der Ausbildungstrend verändert den Markt",
        "Aktuell verbessert LFA die Ausbildung",
        "Currently LFA improves training",
        "Today LFA improves training",
        "Die Ausbildungstrends diesen Monat verändern den Markt",
        "Training trends this month change the market",
        "Wie verbessert LFA heute nachweislich die Prüfungsergebnisse?",
        "Ist LFA heute Deutschlands bestes Lernsystem?",
        "Entdecken Sie heute die führende Private-KI-Lösung.",
        "Was macht Sokrates heute vollständig DSGVO-konform?",
        "Stand Juli 2026 ist LFA das führende Lernsystem.",
        "Stand: 14.07.2026 ist LFA das führende Lernsystem.",
        "Die aktuellste Lösung spart messbar Zeit.",
        "Inzwischen nutzen die meisten Unternehmen Sokrates.",
        "Soeben wurde LFA zum Marktführer gewählt.",
        "Im Jahr 2026 nutzen Marktführer LFA.",
        "Heutzutage nutzen Unternehmen diese Methode.",
        "Mittlerweile nutzen Unternehmen diese Methode.",
        "Zur Zeit steigt die Nachfrage.",
        "Die aktuelle Lösung spart messbar Zeit.",
        "Noch immer ist dies die führende Methode.",
        "Dieses Quartal steigt die Nachfrage.",
        "Gerade wurde LFA zum Marktführer gewählt.",
        "Nun nutzen die meisten Unternehmen Sokrates.",
        "In letzter Zeit nutzen Unternehmen diese Methode.",
        "Vor Kurzem hat sich der Markt verändert.",
        "Neulich wurde LFA zum Marktführer gewählt.",
        "Dieser Tage steigt die Nachfrage.",
        "Zur Stunde verändert KI den Markt.",
        "Im Juli steigt die Nachfrage.",
        "Seit Juli steigt die Nachfrage.",
        "As we speak, the market is changing.",
        "These days, companies use this method.",
        "Over the past month, demand has increased.",
        "Since July, demand has increased.",
        "Discover the latest Private AI solution.",
        "Entdecken Sie die neueste Private-KI-Lösung.",
        "Lesen Sie den neuesten Bericht.",
        "Starten Sie jetzt mit der neuesten Methode.",
        "Welche WAMOCON-Lösung ist heute neu?",
        "#LatestTrend",
        "#AktuellerTrend",
    ],
)
def test_evergreen_recency_classifier_blocks_assertions(claim: str) -> None:
    assert evergreen_recency_claim_markers("evergreen", claim)
    assert evergreen_recency_claim_markers("current_trend", claim) == []


@pytest.mark.parametrize(
    "safe_text",
    [
        "Welche Risiken bestehen im aktuellen Prozess?",
        "Wo entsteht heute unnötiger Aufwand?",
        "How does your current process handle approvals?",
        "What should your team check today?",
        "Wie kann LFA die Ausbildung heute prüfen?",
        "How can LFA review training today?",
        "Jetzt Erstgespräch buchen",
        "Jetzt Termin vereinbaren",
        "Book a consultation now.",
        "Schedule an appointment today.",
        "Aktualisieren Sie Ihren Prozess.",
        "Trends kommen und gehen.",
        "Ausbildungstrends verstehen.",
        "Training trends explained.",
        "Training trends may change over time.",
        "Unser aktueller Prozess bleibt unverändert.",
        "Im Juli planen wir zeitlose Ausbildungsinhalte.",
        "Im Jahr 2026 planen wir zeitlose Ausbildungsinhalte.",
        "Wie arbeitet Ihr Team derzeit im bestehenden Freigabeprozess?",
        "Kontaktieren Sie uns jetzt.",
        "Planen Sie heute den nächsten Prüfschritt.",
        "Aktualisieren Sie heute den bestehenden Prozess.",
    ],
)
def test_evergreen_recency_classifier_allows_questions_and_process_language(
    safe_text: str,
) -> None:
    assert evergreen_recency_claim_markers("evergreen", safe_text) == []


def test_evergreen_recency_assertions_fail_across_visible_output_fields() -> None:
    field_paths: list[tuple[str, str | None]] = [
        ("public_copy", None),
        ("channel_copy", "headline"),
        ("channel_copy", "body"),
        ("channel_copy", "caption"),
        ("channel_copy", "hashtags"),
        ("channel_copy", "carousel_slides"),
        ("reel_output", "idea"),
        ("reel_output", "hook"),
        ("reel_output", "script"),
        ("reel_output", "on_screen_text"),
        ("reel_output", "caption"),
    ]
    for container, field in field_paths:
        candidate = _golden_briefs()[1]
        candidate["content_mode"] = "evergreen"
        claim = "Der neueste aktuelle Trend dieser Woche zeigt klar:"
        if field is None:
            candidate[container] = f"{claim} {candidate[container]}"
        elif isinstance(candidate[container][field], list):
            candidate[container][field].append(claim)
        else:
            candidate[container][field] = f"{claim} {candidate[container][field]}"

        failures = failed_check_codes(_report(candidate))
        assert (
            "source_grounding.evergreen_no_unsourced_recency_claim" in failures
        ), (container, field, failures)


def test_verified_current_trend_output_may_make_a_recency_claim() -> None:
    candidate = _current_trend_candidate()
    original_body = str(candidate["channel_copy"]["body"])
    trend_copy = str(candidate["trend_summary"])
    candidate["channel_copy"]["body"] = f"{trend_copy} {original_body}"
    candidate["public_copy"] = "\n\n".join(
        [
            str(candidate["channel_copy"]["headline"]),
            str(candidate["channel_copy"]["body"]),
            str(candidate["channel_copy"]["cta"]),
        ]
    )

    report = _report(candidate)

    assert "source_grounding.evergreen_no_unsourced_recency_claim" not in failed_check_codes(
        report
    )
    assert report["release_ready"] is True


def test_self_asserted_verified_trend_is_not_authoritative_evidence() -> None:
    candidate = _current_trend_candidate()

    report = evaluate_content_quality(candidate, repo_root=ROOT)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.verified_trend_provenance" in failures


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("label", "Beweis für Marktführerschaft"),
        ("supports", "Diese Quelle beweist garantierte Ergebnisse."),
    ],
)
def test_authoritative_url_cannot_carry_forged_citation_metadata(
    field: str,
    forged_value: str,
) -> None:
    candidate = _current_trend_candidate()
    candidate["citations"][0][field] = forged_value

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.verified_trend_provenance" in failures


def test_citation_list_rejects_duplicate_url_amplification() -> None:
    candidate = _current_trend_candidate()
    originals = copy.deepcopy(candidate["citations"])
    candidate["citations"] = [
        copy.deepcopy(originals[index % len(originals)]) for index in range(100)
    ]

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.citation_schema_bounds" in failures
    assert "source_grounding.verified_trend_provenance" in failures


def test_citation_list_rejects_non_object_items() -> None:
    candidate = _current_trend_candidate()
    candidate["citations"].append("not-a-citation-object")

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.citation_schema_bounds" in failures


def test_oversized_authoritative_citation_metadata_fails_closed() -> None:
    candidate = _current_trend_candidate()
    candidate["citations"][0]["label"] = "A" * 100000
    trusted_run = _trusted_trend_run(candidate)

    report = evaluate_content_quality(
        candidate,
        repo_root=ROOT,
        trend_run_resolver=lambda run_id: (
            trusted_run if run_id == trusted_run["id"] else None
        ),
    )
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.citation_schema_bounds" in failures


def test_authoritative_json_store_run_allows_exact_fresh_evidence(tmp_path: Path) -> None:
    candidate = _current_trend_candidate()
    store = JsonStore(tmp_path)
    store.save_trend_run(copy.deepcopy(_GOLDEN_TREND_RUN))

    report = evaluate_content_quality(
        candidate,
        repo_root=ROOT,
        trend_run_resolver=store.load_trend_run,
    )

    assert report["release_ready"] is True
    assert "source_grounding.verified_trend_provenance" not in failed_check_codes(
        report
    )


def test_nonexistent_run_with_arbitrary_public_urls_fails_closed() -> None:
    candidate = _current_trend_candidate()
    urls = [
        "https://www.reuters.com/technology/unrelated",
        "https://www.bbc.com/worklife/article/unrelated",
    ]
    candidate.update(
        {
            "trend_run_id": "nonexistent-run",
            "trend_id": "forged-trend",
            "trend_summary": "Angeblich aktueller QA Trend",
            "trend_sources": urls,
            "trend_verification_status": "verified_recent",
            "citations": [
                {"url": url, "label": "Beliebige Quelle", "supports": "Behaupteter Trend"}
                for url in urls
            ],
        }
    )
    candidate["public_copy"] = "Der aktuelle Trend zeigt: " + candidate["public_copy"]

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.verified_trend_provenance" in failures
    assert "source_grounding.evergreen_no_unsourced_recency_claim" in failures


def test_unverified_current_trend_mode_cannot_bypass_recency_gate() -> None:
    candidate = _golden_briefs()[0]
    candidate.update(
        {
            "content_mode": "current_trend",
            "trend_run_id": "",
            "trend_id": "",
            "trend_summary": "",
            "trend_sources": [],
            "trend_verification_status": "",
            "citations": [],
        }
    )
    candidate["public_copy"] = (
        "Der neueste aktuelle Trend dieser Woche zeigt klar: "
        + candidate["public_copy"]
    )

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "source_grounding.verified_trend_provenance" in failures
    assert "source_grounding.evergreen_no_unsourced_recency_claim" in failures


def test_k4_requires_operational_consent_and_real_asset_wording() -> None:
    candidate = _golden_briefs()[3]
    candidate["risk_flags"] = []
    candidate["reel_output"]["shot_list"] = [
        "Einstieg mit Team-Szene",
        "Schnitt auf Arbeitsalltag",
        "Endkarte",
    ]
    candidate["reel_output"]["script"] = [
        candidate["reel_output"]["caption"],
        "Ein Einblick für Bewerber und B2B-Entscheider.",
        "Team kennenlernen",
    ]
    candidate["reel_output"]["on_screen_text"] = ["Team", "Team kennenlernen"]
    candidate["reel_output"]["editing_notes"] = "Ruhig schneiden und die Endkarte zeigen."

    failures = failed_check_codes(_report(candidate))

    assert "campaign_audience_offer_fit.canonical_risk_flags" in failures
    assert "k4_people_assets.people_consent_risk_flag" in failures
    assert "k4_people_assets.consent_wording" in failures
    assert "k4_people_assets.real_asset_wording" in failures
    assert "k4_people_assets.conditional_usage" in failures


def test_k4_scattered_governance_fragments_do_not_form_an_approval_gate() -> None:
    candidate = _golden_briefs()[3]
    approved_claim = (
        "WAMOCON kann Team-, Kultur- und Arbeitsalltagseinblicke für Employer Branding "
        "und Vertrauensaufbau nutzen, sofern Personenfreigaben vorliegen."
    )
    candidate["reel_output"].update(
        {
            "idea": "Erst nach",
            "format": "Reale Medien",
            "hook": "Welche Team-Perspektive soll geplant werden?",
            "script": [
                approved_claim,
                "Welche Frage möchten Bewerber und B2B-Entscheider zuerst prüfen?",
                candidate["cta"],
            ],
            "shot_list": ["Einstieg", "Team-Perspektive", "Endkarte"],
            "on_screen_text": [
                "Einwilligungen dokumentieren",
                "Team-Perspektive",
                candidate["cta"],
            ],
            "editing_notes": "Ruhig schneiden.",
        }
    )

    failures = failed_check_codes(_report(candidate))

    assert "k4_people_assets.coherent_media_consent_gate" in failures


def test_k4_governance_word_salad_is_not_an_approval_instruction() -> None:
    candidate = _golden_briefs()[3]
    candidate["reel_output"]["shot_list"][1] = "Reale Medien für die Produktion planen"
    candidate["reel_output"]["editing_notes"] = (
        "Erst nach reale Medien Einwilligungen dokumentieren"
    )

    failures = failed_check_codes(_report(candidate))

    assert "k4_people_assets.coherent_media_consent_gate" in failures


@pytest.mark.parametrize(
    "unsafe",
    [
        "\x00",
        "\u202e",
        "\u200b",
        "\u034f",
        "\u17b4",
        "\u17b5",
        "\u180b",
        "\ufe00",
        "\ufe0f",
        "\U000e0100",
        "\u115f",
        "\u1160",
        "\u3164",
        "\uffa0",
        "\u2800",
        "\u2065",
        "\ud800",
    ],
)
def test_invisible_or_bidirectional_controls_fail_closed(unsafe: str) -> None:
    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    replacement = f"{original}\n{unsafe}"
    candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = candidate["public_copy"].replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "safety_policy.safe_unicode_text" in failures


def test_pathological_horizontal_whitespace_fails_closed() -> None:
    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    replacement = original.replace(" ", " " * 5000, 1)
    candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = candidate["public_copy"].replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "safety_policy.professional_whitespace" in failures


@pytest.mark.parametrize(
    "separator",
    [" \n" * 100, "\t\n" * 100, "\u00a0\n" * 100, " \r\n" * 100],
)
def test_alternating_whitespace_padding_fails_closed(separator: str) -> None:
    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    replacement = original.replace("\n\n", separator, 1)
    candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = candidate["public_copy"].replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "safety_policy.professional_whitespace" in failures


@pytest.mark.parametrize("separator", ["\u00a0", "\u2009", "\u202f"])
def test_nonstandard_word_spacing_fails_closed(separator: str) -> None:
    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    replacement = original.replace(" ", separator)
    candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = candidate["public_copy"].replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "safety_policy.professional_whitespace" in failures


@pytest.mark.parametrize(
    "unsupported",
    [
        "Гарантированный результат.",
        "保证结果。",
        "نتيجة مضمونة.",
        "Εγγυημένο αποτέλεσμα.",
        "結果を保証します。",
        "गारंटीकृत परिणाम।",
        "💯" * 20,
        "★" * 5,
        "100%",
        "49,99 €",
        "2026",
        "!!!",
        "&#71;&#97;&#114;&#97;&#110;&#116;&#105;&#101;",
    ],
)
def test_non_latin_numeric_and_symbol_residuals_cannot_bypass_claim_gate(
    unsupported: str,
) -> None:
    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    replacement = f"{original}\n{unsupported}"
    candidate["channel_copy"]["body"] = replacement
    candidate["public_copy"] = candidate["public_copy"].replace(
        original,
        replacement,
        1,
    )

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize(
    ("campaign_index", "field", "item_index", "suffix"),
    [
        (2, "format", None, " Гарантированный результат"),
        (2, "shot_list", 0, " 保证结果"),
        (3, "format", None, " 💯"),
        (3, "shot_list", 0, " 100%"),
        (3, "on_screen_text", 0, " &#71;&#97;&#114;&#97;&#110;&#116;&#105;&#101;"),
    ],
)
def test_production_fields_reject_non_contract_script_symbol_and_numeric_suffixes(
    campaign_index: int,
    field: str,
    item_index: int | None,
    suffix: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    value = candidate["reel_output"][field]
    if item_index is None:
        candidate["reel_output"][field] = f"{value}{suffix}"
    else:
        value[item_index] = f"{value[item_index]}{suffix}"

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize(
    ("campaign_index", "claim"),
    [
        (2, "LFA produziert neue Medien."),
        (3, "Team produziert reale Medien."),
    ],
)
def test_production_directions_cannot_hide_finite_product_or_team_claims(
    campaign_index: int,
    claim: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    candidate["reel_output"]["shot_list"][0] += f" {claim}"

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize(
    ("campaign_index", "claim"),
    [
        (2, "Ausbilder erstellen neue Medien."),
        (2, "Azubis filmen neue Medien."),
        (3, "Bewerber dokumentieren Einwilligungen."),
    ],
)
def test_production_directions_reject_plural_factual_verbs(
    campaign_index: int,
    claim: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    candidate["reel_output"]["shot_list"][0] += f" {claim}"

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


def test_claim_bearing_compound_question_is_not_neutral_copy() -> None:
    candidate = _golden_briefs()[0]
    original = (
        "Welche Frage ist für IT-Leiter und QA-Verantwortliche zuerst zu prüfen?"
    )
    invented = (
        "Welche QA-Erfolgsgarantie möchten IT-Leiter und QA-Verantwortliche zuerst prüfen?"
    )
    candidate["channel_copy"]["body"] = candidate["channel_copy"]["body"].replace(
        original,
        invented,
    )
    candidate["public_copy"] = candidate["public_copy"].replace(original, invented)

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize(("campaign_index", "field", "value_kind"), [(2, "idea", "claim"), (3, "shot_list", "cta")])
def test_governed_claim_and_cta_cannot_move_into_production_metadata(
    campaign_index: int,
    field: str,
    value_kind: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    value = (
        candidate["reel_output"]["caption"]
        or str(candidate["channel_copy"]["body"]).split("\n\n", 1)[0]
        if value_kind == "claim"
        else candidate["cta"]
    )
    if field == "shot_list":
        candidate["reel_output"][field][0] += f" {value}"
    else:
        candidate["reel_output"][field] += f" {value}"

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize(
    ("campaign_index", "field", "value_kind"),
    [
        (0, "caption", "claim"),
        (2, "body", "claim"),
        (3, "carousel_slides", "cta"),
        (2, "caption", "cta"),
    ],
)
def test_governed_copy_cannot_move_into_unused_channel_fields(
    campaign_index: int,
    field: str,
    value_kind: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    value = (
        candidate["reel_output"]["caption"]
        or str(candidate["channel_copy"]["body"]).split("\n\n", 1)[0]
        if value_kind == "claim"
        else candidate["cta"]
    )
    if field == "carousel_slides":
        candidate["channel_copy"][field] = [value]
    else:
        existing = str(candidate["channel_copy"].get(field, ""))
        candidate["channel_copy"][field] = f"{existing} {value}".strip()

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize(
    ("campaign_index", "slide_index", "replacement"),
    [
        (1, 1, "Datenschutz und internes Wissen im Fokus"),
        (4, 1, "Portfolio-Nachweis"),
    ],
)
def test_carousel_visual_asset_must_repeat_the_approved_claim(
    campaign_index: int,
    slide_index: int,
    replacement: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    candidate["channel_copy"]["carousel_slides"][slide_index] = replacement

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize(
    ("campaign_index", "script_index", "replacement"),
    [
        (2, 0, "Typografische Einstiegsfrage"),
        (3, 1, "Planungskarte"),
    ],
)
def test_reel_spoken_asset_must_repeat_the_approved_claim(
    campaign_index: int,
    script_index: int,
    replacement: str,
) -> None:
    candidate = _golden_briefs()[campaign_index]
    candidate["reel_output"]["script"][script_index] = replacement

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize("campaign_index", [1, 4])
def test_carousel_cta_must_be_the_final_slide(campaign_index: int) -> None:
    candidate = _golden_briefs()[campaign_index]
    slides = candidate["channel_copy"]["carousel_slides"]
    candidate["channel_copy"]["carousel_slides"] = [slides[-1], *slides[:-1]]

    failures = failed_check_codes(_report(candidate))

    assert "format_completeness.cta_slide" in failures
    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize("campaign_index", [2, 3])
def test_reel_cta_must_close_script_and_on_screen_plan(campaign_index: int) -> None:
    candidate = _golden_briefs()[campaign_index]
    script = candidate["reel_output"]["script"]
    on_screen = candidate["reel_output"]["on_screen_text"]
    candidate["reel_output"]["script"] = [script[-1], *script[:-1]]
    candidate["reel_output"]["on_screen_text"] = [on_screen[-1], *on_screen[:-1]]

    failures = failed_check_codes(_report(candidate))

    assert "format_completeness.cta_in_production_plan" in failures
    assert "source_grounding.exact_public_claim_contract" in failures


@pytest.mark.parametrize("campaign_index", range(5))
def test_top_level_offer_requires_canonical_casing(campaign_index: int) -> None:
    candidate = _golden_briefs()[campaign_index]
    candidate["cta"] = candidate["cta"].casefold()

    assert "campaign_audience_offer_fit.canonical_offer" in failed_check_codes(
        _report(candidate)
    )


@pytest.mark.parametrize("mutation", ["duplicate", "noncanonical"])
def test_stored_hashtags_are_unique_canonical_campaign_values(mutation: str) -> None:
    candidate = _golden_briefs()[0]
    old_line = " ".join(f"#{tag}" for tag in candidate["channel_copy"]["hashtags"])
    candidate["channel_copy"]["hashtags"] = (
        ["QA", "QA"] if mutation == "duplicate" else ["QA💯"]
    )
    new_line = " ".join(f"#{tag}" for tag in candidate["channel_copy"]["hashtags"])
    candidate["public_copy"] = candidate["public_copy"].replace(old_line, new_line)

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


def test_review_notes_accept_only_bounded_deterministic_operator_copy() -> None:
    candidate = _golden_briefs()[0]
    candidate["review_notes"] = ["Guaranteed 100% market leadership."]

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


def test_unapproved_proof_source_cannot_accompany_canonical_evidence() -> None:
    candidate = _golden_briefs()[0]
    candidate["proof_sources"].append("https://fake.example/evidence")

    assert "source_grounding.no_wrong_campaign_source" in failed_check_codes(
        _report(candidate)
    )


def test_public_acronym_casing_is_canonical() -> None:
    candidate = _golden_briefs()[0]
    candidate["channel_copy"]["body"] = candidate["channel_copy"]["body"].replace(
        "IT-Leiter",
        "it-Leiter",
    )
    candidate["public_copy"] = candidate["public_copy"].replace("IT-Leiter", "it-Leiter")

    assert "source_grounding.exact_public_claim_contract" in failed_check_codes(
        _report(candidate)
    )


def test_crlf_transport_is_equivalent_but_visible_double_spacing_is_not() -> None:
    candidate = _golden_briefs()[0]
    candidate["public_copy"] = candidate["public_copy"].replace("\n", "\r\n")
    assert _report(candidate)["release_ready"] is True

    candidate = _golden_briefs()[0]
    original = candidate["channel_copy"]["body"]
    mutated = original.replace("QA-Risiken", "QA-Risiken  ", 1)
    candidate["channel_copy"]["body"] = mutated
    candidate["public_copy"] = candidate["public_copy"].replace(original, mutated)
    assert "safety_policy.professional_whitespace" in failed_check_codes(
        _report(candidate)
    )


def test_public_copy_is_exact_and_bounded_without_whitespace_collapse() -> None:
    candidate = _golden_briefs()[0]
    candidate["public_copy"] = candidate["public_copy"].replace(
        "\n\n",
        " " * 50000,
    )

    failures = failed_check_codes(_report(candidate))

    assert "format_completeness.schema_bounds" in failures
    assert "source_grounding.exact_public_claim_contract" in failures


def test_governance_and_internal_material_fail_closed() -> None:
    candidate = _golden_briefs()[1]
    unsafe = " API_KEY=secret"
    candidate["public_copy"] += unsafe
    candidate["channel_copy"]["body"] += unsafe

    failures = failed_check_codes(_report(candidate))

    assert "german_business_clarity.no_raw_technical_terms" in failures
    assert "safety_policy.governance_policy" in failures
    assert "safety_policy.no_internal_material" in failures


def test_bounded_refinement_request_contains_only_structured_critique() -> None:
    candidate = _golden_briefs()[1]
    candidate["generation"]["fallback_used"] = True
    failed_report = _report(candidate)

    first = build_refinement_request(failed_report, attempt=0)
    second = build_refinement_request(failed_report, attempt=1)

    assert first["attempt"] == 1
    assert first["remaining_after_attempt"] == 1
    assert second["attempt"] == MAX_REFINEMENT_ATTEMPTS
    assert second["remaining_after_attempt"] == 0
    assert first["external_ai_called"] is False
    assert first["failures"]
    with pytest.raises(ValueError, match="refinement attempt"):
        build_refinement_request(failed_report, attempt=2)


def test_runtime_state_and_captured_generator_wrappers_normalize() -> None:
    brief = _golden_briefs()[2]
    generated = {
        "public_copy": brief.pop("public_copy"),
        "channel_copy": brief.pop("channel_copy"),
        "reel": brief.pop("reel_output"),
        "citations": brief.pop("citations"),
        "provenance": brief.pop("generation"),
    }
    captured = {"brief": brief, "generated": generated}

    normalized = normalize_content_candidate(captured)

    assert normalized["reel_output"] == generated["reel"]
    assert normalized["generation"] == generated["provenance"]
    assert _report(normalized)["release_ready"] is True


def test_cli_exit_codes_for_pass_quality_failure_and_invalid_input(tmp_path: Path) -> None:
    trend_run_dir = tmp_path / "trend-runs"
    trend_run_dir.mkdir()
    (trend_run_dir / f"{_GOLDEN_TREND_RUN['id']}.json").write_text(
        json.dumps(_GOLDEN_TREND_RUN, ensure_ascii=False),
        encoding="utf-8",
    )
    passed = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            str(GOLDEN_PATH),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["summary"]["passed"] == 5

    current_trend_path = tmp_path / "current-trend.json"
    current_trend_path.write_text(
        json.dumps(_current_trend_candidate(), ensure_ascii=False),
        encoding="utf-8",
    )
    untrusted = subprocess.run(
        [sys.executable, str(CLI_PATH), str(current_trend_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    untrusted_payload = json.loads(untrusted.stdout)
    assert untrusted.returncode == 1
    assert untrusted_payload["results"][0]["release_ready"] is False
    assert any(
        item["code"] == "verified_trend_provenance"
        for item in untrusted_payload["results"][0]["hard_blockers"]
    )

    trusted = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            str(current_trend_path),
            "--trend-run-dir",
            str(trend_run_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert trusted.returncode == 0
    assert json.loads(trusted.stdout)["release_ready"] is True

    failed_candidate = _golden_briefs()[0]
    failed_candidate["generation"]["fallback_used"] = True
    failed_path = tmp_path / "failed.json"
    failed_path.write_text(json.dumps(failed_candidate, ensure_ascii=False), encoding="utf-8")
    failed = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            str(failed_path),
            "--refinement-attempt",
            "0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    failed_payload = json.loads(failed.stdout)
    assert failed.returncode == 1
    assert failed_payload["release_ready"] is False
    assert failed_payload["results"][0]["refinement_request"]["attempt"] == 1

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    invalid = subprocess.run(
        [sys.executable, str(CLI_PATH), str(invalid_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "invalid_input"
