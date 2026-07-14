import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.ai_client import AICompletion
from marketing_machine.campaign_catalog import default_brief_payload, load_campaign_catalog
from marketing_machine.content_generator import (
    K4_GOVERNANCE_DIRECTION_DE,
    ContentGenerator,
    GeneratedContent,
    _campaign_claim_errors,
    _coerce_carousel_slides,
    _coerce_text_list,
    _k4_reel_needs_governance_fill,
    _public_output_contract_errors,
    _public_source_urls,
    candidate_public_output_contract_errors,
    generate_public_copy,
)
from marketing_machine.schemas import ContentBrief


class ContentGeneratorTests(unittest.TestCase):
    K1_APPROVED_CLAIM = (
        "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
        "strukturiert prüfen und priorisieren."
    )

    def approved_k1_evidence(self):
        return [
            {
                "claim": self.K1_APPROVED_CLAIM,
                "approved_for_public_use": True,
            }
        ]

    def test_public_contract_rejects_arbitrary_second_claim_for_all_campaigns(self):
        cases = {
            "k1": (
                "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse strukturiert prüfen und priorisieren.",
                "WAMOCON betreut seit 20 Jahren internationale Konzerne.",
                "IT-Leiter und QA-Verantwortliche",
                "QA-Risikoaudit anfragen",
            ),
            "k2": (
                "Sokrates Private AI positioniert KI-Nutzung für den Mittelstand mit Fokus auf Datenschutz und internes Wissen.",
                "Die Plattform verarbeitet sämtliche Daten ausschließlich auf eigener Infrastruktur.",
                "Geschäftsführer und IT-Leiter",
                "Private-KI-Erstgespräch anfragen",
            ),
            "k3": (
                "LFA ist ein digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder.",
                "Azubis bestehen dadurch ihre Prüfungen deutlich schneller.",
                "Schüler, Azubis und Ausbilder",
                "LFA-Demo anfragen",
            ),
            "k4": (
                "WAMOCON kann Team-, Kultur- und Arbeitsalltagseinblicke für Employer Branding und Vertrauensaufbau nutzen, sofern Personenfreigaben vorliegen.",
                "Unsere Mitarbeitenden lieben die flexiblen Arbeitszeiten.",
                "Bewerber und B2B-Entscheider",
                "Team kennenlernen",
            ),
            "k5": (
                "WAMOCON dokumentiert ein Portfolio von mehr als 50 ausgelieferten Anwendungen in sieben Kategorien.",
                "Jede Anwendung steigert nachweislich den Umsatz ihrer Nutzer.",
                "IT-Leiter und Geschäftsführer",
                "App-Modernisierungscheck anfragen",
            ),
        }
        for campaign_id, (claim, invented, persona, cta) in cases.items():
            with self.subTest(campaign_id=campaign_id):
                brief = self.make_brief(
                    campaign_id=campaign_id,
                    persona=persona,
                    cta=cta,
                )
                audience_question = f"Welche Frage möchten {persona} zuerst prüfen?"
                body = f"{claim} {invented} {audience_question}"
                generated = GeneratedContent(
                    public_copy=f"{body}\n\n{cta}",
                    review_notes=[],
                    channel_copy={
                        "headline": "",
                        "body": body,
                        "caption": "",
                        "cta": cta,
                        "hashtags": [],
                        "carousel_slides": [],
                    },
                    reel={
                        "idea": "",
                        "format": "",
                        "hook": "",
                        "script": [],
                        "shot_list": [],
                        "on_screen_text": [],
                        "caption": "",
                        "cta": "",
                        "editing_notes": "",
                    },
                    citations=[],
                    provenance={},
                )

                errors = _public_output_contract_errors(brief, generated, [claim])

                self.assertTrue(
                    any("unsupported public copy" in error for error in errors),
                    errors,
                )

    def test_reel_production_field_cannot_turn_safe_tokens_into_capability_claim(self):
        claim = "LFA ist ein digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder."
        cta = "LFA-Demo oder Ausbildungsplatz-Info anfragen"
        brief = self.make_brief(
            campaign_id="k3",
            campaign="LFA - Lernzentrum Für Azubis",
            persona="Schüler, Azubis und Ausbilder",
            channel="Instagram",
            format="reel",
            cta=cta,
        )
        reel = {
            "idea": "Typografisches 9:16-Reel mit einer Prüffrage und einer Endkarte.",
            "format": "9:16-Typografie-Reel",
            "hook": "Wie lässt sich ein digitales Lernsystem für Azubis und Ausbilder einordnen?",
            "script": [claim, cta],
            "shot_list": [
                "Typografische Einstiegsfrage",
                "Freigegebene LFA-Aussage als ruhige Texttafel",
                "Klare Endkarte mit nächstem Schritt",
            ],
            "on_screen_text": ["LFA", cta],
            "caption": claim,
            "cta": cta,
            "editing_notes": "Ruhiger Schnitt und klare Typografie.",
        }
        generated = GeneratedContent(
            public_copy=f"{claim}\n\n{cta}",
            review_notes=[],
            channel_copy={
                "headline": "LFA",
                "body": "",
                "caption": claim,
                "cta": cta,
                "hashtags": ["LFA"],
                "carousel_slides": [],
            },
            reel=reel,
            citations=[],
            provenance={},
        )

        for invented in (
            "LFA kann Azubis einordnen.",
            "LFA wird gut.",
            "LFA wird für Azubis ein Lernsystem.",
            "Azubis werden gut.",
            "LFA gut.",
        ):
            with self.subTest(invented=invented):
                generated.reel["script"] = [claim, invented, cta]
                errors = _public_output_contract_errors(brief, generated, [claim])
                self.assertTrue(any(invented.rstrip(".") in error for error in errors), errors)

    def test_k4_governance_gate_requires_one_coherent_production_direction(self):
        scattered = {
            "idea": "Erst nach",
            "format": "Reale Medien",
            "editing_notes": "Einwilligungen dokumentieren",
        }
        word_salad = {
            "editing_notes": "Erst nach reale Medien Einwilligungen dokumentieren"
        }
        coherent = {"editing_notes": K4_GOVERNANCE_DIRECTION_DE}

        self.assertTrue(_k4_reel_needs_governance_fill(scattered))
        self.assertTrue(_k4_reel_needs_governance_fill(word_salad))
        self.assertFalse(_k4_reel_needs_governance_fill(coherent))

    def test_exact_verified_trend_summary_is_the_only_extra_factual_copy_allowed(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        trend_summary = "Zwei aktuelle Fachquellen ordnen risikobasiertes Testen als Priorisierungsthema ein."
        sources = [
            "https://quality.example.com/risk-testing",
            "https://testing.example.org/priorities",
        ]
        brief = self.make_brief(
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            content_mode="current_trend",
            trend_run_id="trend-run-1",
            trend_id="trend-1",
            trend_summary=trend_summary,
            trend_sources=sources,
            trend_verification_status="verified_recent",
        )
        question = "Welche Frage möchten IT-Leiter und QA-Verantwortliche zuerst prüfen?"
        body = f"{claim} {trend_summary} {question}"
        generated = GeneratedContent(
            public_copy=f"{body}\n\n{brief.cta}",
            review_notes=[],
            channel_copy={
                "headline": "",
                "body": body,
                "caption": "",
                "cta": brief.cta,
                "hashtags": ["QA"],
                "carousel_slides": [],
            },
            reel={
                "idea": "",
                "format": "",
                "hook": "",
                "script": [],
                "shot_list": [],
                "on_screen_text": [],
                "caption": "",
                "cta": "",
                "editing_notes": "",
            },
            citations=[{"url": url} for url in sources],
            provenance={},
        )

        self.assertEqual(
            _public_output_contract_errors(brief, generated, [claim]),
            [],
        )
        brief.trend_verification_status = "needs_source_verification"
        self.assertTrue(
            any(
                "unsupported public copy" in error
                for error in _public_output_contract_errors(brief, generated, [claim])
            )
        )

    def test_stored_candidate_adapter_uses_authoritative_contract_values(self):
        claim = (
            "WAMOCON dokumentiert ein Portfolio von mehr als 50 ausgelieferten "
            "Anwendungen in sieben Kategorien."
        )
        safe_body = (
            f"{claim} Welche Frage möchten IT-Leiter und Geschäftsführer zuerst prüfen?"
        )
        candidate = {
            "id": "tampered-k5",
            "campaign_id": "k1",
            "campaign": "Tampered campaign",
            "persona": "Alle",
            "channel": "LinkedIn",
            "format": "portfolio_carousel",
            "language": "de-DE",
            "cta": "Kostenlos kaufen",
            "public_copy": (
                "Portfolio-Nachweis\n\n"
                f"{safe_body} Jede Anwendung garantiert höhere Umsätze.\n\n"
                "App-Modernisierungscheck anfragen"
            ),
            "channel_copy": {
                "headline": "Portfolio-Nachweis",
                "body": safe_body,
                "caption": "",
                "cta": "App-Modernisierungscheck anfragen",
                "hashtags": ["QA"],
                "carousel_slides": [],
            },
            "reel_output": {},
            "citations": [],
        }

        errors = candidate_public_output_contract_errors(
            candidate,
            campaign_id="k5",
            persona="IT-Leiter und Geschäftsführer",
            cta="App-Modernisierungscheck anfragen",
            approved_claims=[claim],
        )

        self.assertTrue(any("exactly re-render" in error for error in errors))

    def test_stored_candidate_adapter_requires_canonical_claim_and_cta_casing(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        cta = "QA-Risikoaudit anfragen"
        question = (
            "Welche Frage ist für IT-Leiter und QA-Verantwortliche zuerst zu prüfen?"
        )
        body = f"{claim} {question}"
        candidate = {
            "id": "canonical-casing-k1",
            "campaign_id": "k1",
            "campaign": "Consulting Test- und Qualitätsmanagement",
            "persona": "IT-Leiter und QA-Verantwortliche",
            "channel": "LinkedIn",
            "format": "expert_post",
            "language": "de-DE",
            "cta": cta,
            "public_copy": f"{body}\n\n{cta}",
            "channel_copy": {
                "headline": "",
                "body": body,
                "caption": "",
                "cta": cta,
                "hashtags": ["QA"],
                "carousel_slides": [],
            },
            "reel_output": {},
            "citations": [],
        }
        self.assertEqual(
            candidate_public_output_contract_errors(
                candidate,
                campaign_id="k1",
                persona="IT-Leiter und QA-Verantwortliche",
                cta=cta,
                approved_claims=[claim],
            ),
            [],
        )

        lower_claim = json.loads(json.dumps(candidate))
        lower_claim["public_copy"] = lower_claim["public_copy"].replace(
            "WAMOCON", "wamocon"
        )
        lower_claim["channel_copy"]["body"] = lower_claim["channel_copy"][
            "body"
        ].replace("WAMOCON", "wamocon")
        claim_errors = candidate_public_output_contract_errors(
            lower_claim,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta=cta,
            approved_claims=[claim],
        )
        self.assertTrue(any("verbatim" in error for error in claim_errors), claim_errors)

        lower_cta = json.loads(json.dumps(candidate))
        lower_cta["public_copy"] = lower_cta["public_copy"].replace(
            cta, cta.casefold()
        )
        lower_cta["channel_copy"]["cta"] = cta.casefold()
        cta_errors = candidate_public_output_contract_errors(
            lower_cta,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta=cta,
            approved_claims=[claim],
        )
        self.assertTrue(any("canonical CTA" in error for error in cta_errors), cta_errors)

        mixed_claim = json.loads(json.dumps(candidate))
        mixed_claim["channel_copy"]["headline"] = claim.casefold()
        mixed_claim_errors = candidate_public_output_contract_errors(
            mixed_claim,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta=cta,
            approved_claims=[claim],
        )
        self.assertTrue(
            any("canonical casing" in error for error in mixed_claim_errors),
            mixed_claim_errors,
        )

        mixed_cta = json.loads(json.dumps(candidate))
        mixed_cta["channel_copy"]["headline"] = cta.casefold()
        mixed_cta_errors = candidate_public_output_contract_errors(
            mixed_cta,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta=cta,
            approved_claims=[claim],
        )
        self.assertTrue(
            any("canonical casing" in error for error in mixed_cta_errors),
            mixed_cta_errors,
        )

    def test_stored_candidate_adapter_rejects_unsupported_hashtag_claim(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        question = "Welche Frage möchten IT-Leiter und QA-Verantwortliche zuerst prüfen?"
        caption = f"{claim} {question}"
        candidate = {
            "id": "tampered-hashtag-k1",
            "campaign_id": "k1",
            "campaign": "Consulting Test- und Qualitätsmanagement",
            "persona": "IT-Leiter und QA-Verantwortliche",
            "channel": "Instagram",
            "format": "expert_post",
            "language": "de-DE",
            "cta": "QA-Risikoaudit anfragen",
            "public_copy": (
                f"{caption}\n\nQA-Risikoaudit anfragen\n\n#GarantierteSicherheit"
            ),
            "channel_copy": {
                "headline": "",
                "body": "",
                "caption": caption,
                "cta": "QA-Risikoaudit anfragen",
                "hashtags": ["GarantierteSicherheit"],
                "carousel_slides": [],
            },
            "reel_output": {},
            "citations": [],
        }

        errors = candidate_public_output_contract_errors(
            candidate,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta="QA-Risikoaudit anfragen",
            approved_claims=[claim],
        )

        self.assertTrue(
            any("unsupported campaign hashtag" in error for error in errors),
            errors,
        )

    def test_stored_candidate_adapter_rejects_repeated_claims_questions_and_labels(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        question = "Welche Frage ist für IT-Leiter und QA-Verantwortliche zuerst zu prüfen?"
        body = f"{claim} {claim} {question} {question}"
        candidate = {
            "id": "repeated-k1",
            "campaign_id": "k1",
            "campaign": "Consulting Test- und Qualitätsmanagement",
            "persona": "IT-Leiter und QA-Verantwortliche",
            "channel": "LinkedIn",
            "format": "expert_post",
            "language": "de-DE",
            "cta": "QA-Risikoaudit anfragen",
            "public_copy": f"QA-Risiko\n\n{body}\n\nQA-Risikoaudit anfragen",
            "channel_copy": {
                "headline": "QA-Risiko",
                "body": body,
                "caption": "",
                "cta": "QA-Risikoaudit anfragen",
                "hashtags": [],
                "carousel_slides": ["QA-Risiko", "QA-Risiko"],
            },
            "reel_output": {},
            "citations": [],
        }

        errors = candidate_public_output_contract_errors(
            candidate,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta="QA-Risikoaudit anfragen",
            approved_claims=[claim],
        )

        self.assertTrue(any("repeats governed copy" in error for error in errors), errors)
        self.assertTrue(any("repeats the same question" in error for error in errors), errors)

    def test_rendered_public_copy_cannot_repeat_claim_across_headline_and_body(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        question = "Welche Frage ist für IT-Leiter und QA-Verantwortliche zuerst zu prüfen?"
        cta = "QA-Risikoaudit anfragen"
        body = f"{claim} {question}"
        candidate = {
            "id": "cross-field-repeat-k1",
            "campaign_id": "k1",
            "campaign": "Consulting Test- und Qualitätsmanagement",
            "persona": "IT-Leiter und QA-Verantwortliche",
            "channel": "LinkedIn",
            "format": "expert_post",
            "language": "de-DE",
            "cta": cta,
            "public_copy": f"{claim}\n\n{body}\n\n{cta}",
            "channel_copy": {
                "headline": claim,
                "body": body,
                "caption": "",
                "cta": cta,
                "hashtags": [],
                "carousel_slides": [],
            },
            "reel_output": {},
            "citations": [],
        }

        errors = candidate_public_output_contract_errors(
            candidate,
            campaign_id="k1",
            persona="IT-Leiter und QA-Verantwortliche",
            cta=cta,
            approved_claims=[claim],
        )

        self.assertTrue(
            any("public_copy repeats governed copy" in error for error in errors),
            errors,
        )

    def test_campaign_boundaries_reject_guarantees_disguised_as_questions(self):
        cases = [
            (
                "k1",
                "Wie stellen Sie sicher, dass Ihre Testabdeckung lückenlos dokumentiert ist?",
            ),
            (
                "k2",
                "Wie bleiben Ihre Unternehmensdaten vollständig geschützt und wird internes Wissen effektiv genutzt?",
            ),
            (
                "k5",
                "Wie kann dieser Nachweis in Ihre aktuelle Infrastruktur integriert werden?",
            ),
        ]
        for campaign_id, text in cases:
            with self.subTest(campaign_id=campaign_id):
                errors = _campaign_claim_errors(
                    self.make_brief(campaign_id=campaign_id),
                    text,
                )
                self.assertTrue(errors, text)

    def test_public_citations_reject_private_and_single_label_hosts(self):
        self.assertEqual(
            _public_source_urls(
                [
                    "http://core-n8n:5678/private",
                    "http://192.168.178.75/private",
                    "http://user:password@example.com/private",
                    "https://news.example.com/public",
                ]
            ),
            ["https://news.example.com/public"],
        )

    def make_brief(self, **overrides):
        payload = {
            "id": "k1-qa-generated",
            "campaign_id": "k1",
            "campaign": "K1 QA Risk Audit",
            "persona": "IT-Leiter Thomas",
            "channel": "LinkedIn",
            "format": "expert_post",
            "objective": "QA-Risikoaudit mit senioriger Testexpertise anbieten.",
            "cta": "QA-Risikoaudit anfragen",
            "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
            "utm": {"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1_qa_audit"},
            "hypothesis": "Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen von IT-Leitern.",
            "test_variable": "offer",
            "hashtags": ["QA"],
        }
        payload.update(overrides)
        return ContentBrief(**payload)

    def valid_ai_payload(self):
        return {
            "channel_copy": {
                "headline": "QA-Risiken strukturiert prüfen",
                "body": (
                    f"{self.K1_APPROVED_CLAIM} "
                    "Welche Frage ist für IT-Leiter Thomas zuerst zu prüfen?"
                ),
                "caption": "",
                "cta": "QA-Risikoaudit anfragen",
                "hashtags": ["QA"],
                "carousel_slides": [],
            },
            "reel": {
                "idea": "",
                "format": "",
                "hook": "",
                "script": [],
                "shot_list": [],
                "on_screen_text": [],
                "caption": "",
                "cta": "",
                "editing_notes": "",
            },
            "citations": [],
            "review_notes": [],
        }

    def test_default_linkedin_copy_is_safe_structured_fallback(self):
        brief = self.make_brief()
        generated = generate_public_copy(brief)

        self.assertIn("QA-Risikoaudit anfragen", generated.public_copy)
        self.assertNotIn("Kampagnen/", generated.public_copy)
        self.assertNotIn(brief.hypothesis, generated.public_copy)
        self.assertEqual(generated.channel_copy["cta"], "QA-Risikoaudit anfragen")
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertTrue(generated.provenance["fallback_used"])
        self.assertTrue(any("Vor Veröffentlichung" in note for note in generated.review_notes))

    def test_legacy_evergreen_state_with_generated_recency_claim_fails_validation(self):
        brief = self.make_brief(
            content_mode="evergreen",
            public_copy="Der aktuelle Trend zeigt diese Woche eine klare Veränderung.",
        )

        self.assertTrue(
            any("unsourced current or trending claim" in error for error in brief.validate())
        )

    def test_english_linkedin_copy_remains_available(self):
        generated = generate_public_copy(
            self.make_brief(
                language="en-US",
                objective="Promote a QA risk audit with proof-led copy.",
                cta="Book a QA Risk Audit",
                hypothesis="Proof-led QA content creates qualified buyer interest.",
            )
        )

        self.assertIn("Book a QA Risk Audit", generated.public_copy)
        self.assertTrue(any("Before publishing, check evidence" in note for note in generated.review_notes))

    def test_instagram_copy_uses_only_canonical_campaign_hashtags(self):
        generated = generate_public_copy(
            self.make_brief(
                channel="Instagram",
                hashtags=["qa", "ki", "b2b", "testing", "automation", "extra"],
            )
        )

        self.assertTrue(
            generated.public_copy.endswith(
                "#QA #Testmanagement #Testabdeckung #Testautomatisierung"
            )
        )

    def test_injected_ai_client_is_used_and_provenance_is_recorded(self):
        payload = self.valid_ai_payload()

        class FakeClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return AICompletion(
                    data=payload,
                    provider=self.provider,
                    model=self.model,
                    latency_ms=37,
                    attempts=1,
                    response_id="completion-1",
                )

        client = FakeClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(),
            evidence_records=self.approved_k1_evidence(),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertEqual(generated.provenance["provider"], "local_qwen")
        self.assertEqual(generated.provenance["model"], "qwen-test")
        self.assertEqual(generated.provenance["latency_ms"], 37)
        self.assertFalse(generated.provenance["fallback_used"])
        self.assertIn("QA-Risiken", generated.public_copy)

    def test_model_output_without_approved_evidence_never_gets_ai_status(self):
        payload = self.valid_ai_payload()

        class NoEvidenceClient:
            provider = "local_qwen"
            model = "qwen-no-evidence"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return payload

        client = NoEvidenceClient()
        generated = ContentGenerator([client]).generate(self.make_brief())

        self.assertEqual(client.calls, 3)
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertTrue(
            all(
                "approved_public_claim is required" in failure["detail"]
                for failure in generated.provenance["failures"]
            )
        )

    def test_ai_prompt_receives_bounded_audience_research_from_canonical_brief(self):
        payload = self.valid_ai_payload()

        class CapturingClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def __init__(self):
                self.system_prompt = ""
                self.user_prompt = ""

            def complete_json(self, **kwargs):
                self.system_prompt = kwargs["system_prompt"]
                self.user_prompt = kwargs["user_prompt"]
                return payload

        root = Path(__file__).resolve().parents[1]
        campaign = load_campaign_catalog(root, today=date(2026, 7, 10))[0]
        brief = ContentBrief(
            **default_brief_payload(campaign, content_id="k1-2026w28-audience-prompt")
        )
        approved_claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        payload["channel_copy"]["body"] = (
            f"{approved_claim} Welche Frage möchten IT-Leiter zuerst prüfen?"
        )
        client = CapturingClient()

        generated = ContentGenerator([client]).generate(
            brief,
            evidence_records=[
                {
                    "claim": approved_claim,
                    "approved_for_public_use": True,
                }
            ],
        )

        prompt = json.loads(client.user_prompt)
        profiles = prompt["audience_profiles"]
        self.assertEqual(len(profiles), 4)
        self.assertIn("IT-Leiter", profiles[0]["role"])
        self.assertEqual(set(profiles[0]), {"role"})
        self.assertNotIn("name", profiles[0])
        self.assertNotIn("age", profiles[0])
        self.assertNotIn("income", profiles[0])
        self.assertNotIn("profile_id", profiles[0])
        output_contract = prompt["output_contract"]
        self.assertEqual(output_contract["must_copy_verbatim"], [approved_claim])
        self.assertEqual(output_contract["audience_anchor_exact"], brief.persona)
        self.assertEqual(
            output_contract["audience_question_exact"],
            f"Welche Frage ist für {brief.persona} zuerst zu prüfen?",
        )
        self.assertEqual(output_contract["cta_exact"], brief.cta)
        self.assertIn("QA-Risiken strukturiert prüfen", output_contract["safe_neutral_labels"])
        self.assertIn("Testmanagement", output_contract["hashtags_allowed"])
        self.assertIn("private role labels only", client.system_prompt)
        self.assertNotIn("Fachkräftemangel", client.user_prompt)
        self.assertNotIn("Datensicherheit", client.user_prompt)
        self.assertNotIn("objective", prompt)
        self.assertNotIn("content_constraints", prompt["campaign_guidance"])
        self.assertIn("output_rules", prompt["campaign_guidance"])
        self.assertEqual(generated.provenance["status"], "ai_generated")

    def test_ai_citations_include_only_urls_the_model_actually_cited(self):
        payload = self.valid_ai_payload()
        cited_url = "https://research-source.com/qa-signal"
        uncited_url = "https://industry-source.net/second-source"
        payload["citations"] = [
            {"url": cited_url, "label": "QA signal", "supports": "The selected claim"},
            {"url": cited_url, "label": "Duplicate", "supports": "Duplicate citation"},
        ]

        class CitationClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        brief = self.make_brief(
            trend_sources=[cited_url, uncited_url],
            citations=[
                {"url": cited_url, "title": "QA research"},
                {"url": uncited_url, "title": "Industry research"},
            ],
        )
        generated = ContentGenerator([CitationClient()]).generate(
            brief,
            evidence_records=self.approved_k1_evidence(),
        )

        self.assertEqual([item["url"] for item in generated.citations], [cited_url])
        self.assertEqual(generated.citations[0]["label"], "QA research")
        self.assertNotEqual(generated.citations[0]["supports"], "The selected claim")

    def test_trend_content_repairs_missing_visible_citations(self):
        payload = self.valid_ai_payload()
        source_one = "https://source-one.com/qa"
        source_two = "https://source-two.net/qa"

        class RepairingCitationClient:
            provider = "local_qwen"
            model = "qwen-citations"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                payload["citations"] = [] if self.calls == 1 else [
                    {"url": source_one, "label": "Quelle eins", "supports": "QA-Signal"},
                    {"url": source_two, "label": "Quelle zwei", "supports": "QA-Signal"},
                ]
                return payload

        client = RepairingCitationClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                trend_id="trend-verified",
                trend_summary="Aktuelles QA-Signal",
                trend_sources=[source_one, source_two],
                citations=[
                    {"url": source_one, "title": "Quelle eins"},
                    {"url": source_two, "title": "Quelle zwei"},
                ],
            ),
            evidence_records=self.approved_k1_evidence(),
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertEqual(len(generated.citations), 2)
        self.assertEqual(
            [item["label"] for item in generated.citations],
            ["Quelle eins", "Quelle zwei"],
        )
        self.assertTrue(
            all(item["supports"] == "Aktuelles QA-Signal" for item in generated.citations)
        )

    def test_unsafe_ai_output_uses_clearly_marked_safe_fallback(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["body"] = "Details: Kampagnen/kampagne_1_consulting_qa.json"

        class UnsafeClient:
            provider = "unsafe-provider"
            model = "unsafe-model"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([UnsafeClient()]).generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(generated.provenance["fallback_reason"], "unsafe_or_invalid_content")
        self.assertNotIn("Kampagnen/", generated.public_copy)

    def test_model_output_with_invisible_or_pathological_text_never_gets_ai_status(self):
        root = Path(__file__).resolve().parents[1]
        campaign = load_campaign_catalog(root, today=date(2026, 7, 10))[0]
        brief = ContentBrief(
            **default_brief_payload(campaign, content_id="k1-display-hygiene")
        )
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        question = "Welche Frage möchten IT-Leiter und QA-Verantwortliche zuerst prüfen?"

        class HygieneClient:
            provider = "local_qwen"
            model = "qwen-display-hygiene"
            route_name = "local_content_draft"

            def __init__(self, payload):
                self.payload = payload
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return self.payload

        cases = [
            ("QA-Risiko\x00", "unsafe invisible/control"),
            ("QA-Risiko\u202e", "unsafe invisible/control"),
            ("QA-Risiko\u034f", "unsafe invisible/control"),
            ("QA-Risiko\u3164", "unsafe invisible/control"),
            ("QA-Risiko\u2800", "unsafe invisible/control"),
            ("QA-Risiko\U000e0100", "unsafe invisible/control"),
            ("QA" + (" " * 4) + "Risiko", "pathological whitespace"),
            ("QA" + (" \n" * 20) + "Risiko", "pathological whitespace"),
            ("QA" + ("\t\n" * 20) + "Risiko", "pathological whitespace"),
            ("QA" + ("\u00a0\n" * 20) + "Risiko", "pathological whitespace"),
            ("QA\u00a0Risiko", "pathological whitespace"),
            ("QA\u2009Risiko", "pathological whitespace"),
            ("QA\u202fRisiko", "pathological whitespace"),
        ]
        for headline, expected in cases:
            with self.subTest(headline=repr(headline)):
                payload = self.valid_ai_payload()
                payload["channel_copy"]["headline"] = headline
                payload["channel_copy"]["body"] = f"{claim} {question}"
                client = HygieneClient(payload)

                generated = ContentGenerator([client]).generate(
                    brief,
                    evidence_records=[
                        {"claim": claim, "approved_for_public_use": True}
                    ],
                )

                self.assertEqual(client.calls, 3)
                self.assertEqual(
                    generated.provenance["status"],
                    "deterministic_fallback",
                )
                self.assertTrue(
                    all(
                        expected in failure.get("detail", "")
                        for failure in generated.provenance["failures"]
                    ),
                    generated.provenance["failures"],
                )

    def test_reel_fallback_has_separate_caption_and_production_fields(self):
        generated = generate_public_copy(
            self.make_brief(channel="Instagram", format="reel", hashtags=["QA", "Testing"])
        )

        self.assertTrue(generated.reel["idea"])
        self.assertTrue(generated.reel["script"])
        self.assertTrue(generated.reel["shot_list"])
        self.assertEqual(
            generated.public_copy,
            generated.reel["caption"]
            + "\n\n#QA #Testmanagement #Testabdeckung #Testautomatisierung",
        )
        self.assertNotIn("Shotlist", generated.public_copy)

    def test_reel_fallback_does_not_publish_creation_instructions(self):
        objective = (
            "LFA erklären, ohne Personen, Produktoberflächen oder Ergebnisse zu erfinden."
        )
        generated = generate_public_copy(
            self.make_brief(
                campaign_id="k3",
                campaign="LFA - Lernzentrum Für Azubis",
                channel="Instagram",
                format="reel",
                objective=objective,
                cta="LFA-Demo anfragen",
                hashtags=["Ausbildung", "FIAE"],
            )
        )

        self.assertNotIn("ohne Personen", generated.public_copy)
        self.assertNotIn(objective, generated.reel["hook"])
        self.assertIn("Fachinformatiker-Ausbildung", generated.public_copy)

    def test_portfolio_fallback_ignores_topic_hashtags_as_factual_claims(self):
        generated = generate_public_copy(
            self.make_brief(
                campaign_id="k5",
                campaign="Maßgeschneiderte App-Entwicklung (50+ Portfolio)",
                format="portfolio_carousel",
                objective="Portfolio-Nachweis sachlich einordnen.",
                cta="App-Modernisierungscheck anfragen",
                hashtags=["MaßgeschneiderteSoftware", "KI-Apps", "Prozessdigitalisierung"],
            )
        )

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(len(generated.channel_copy["carousel_slides"]), 5)

    def test_environment_flag_can_explicitly_disable_ai_generation(self):
        generator = ContentGenerator.from_environment(
            environ={"MARKETING_MACHINE_AI_ENABLED": "false"}
        )

        generated = generator.generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(
            generator.route_diagnostics[0]["configuration_errors"],
            ["ai_generation_disabled"],
        )

    def test_local_model_flat_post_shape_is_normalized_and_keeps_ai_provenance(self):
        body = (
            f"{self.K1_APPROVED_CLAIM} "
            "Welche Frage ist für IT-Leiter Thomas zuerst zu prüfen?"
        )

        class FlatClient:
            provider = "local_qwen"
            model = "qwen-flat"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return {
                    "post_title": "QA-Risiken strukturiert prüfen",
                    "post_body": f"{body}\n\nQA-Risikoaudit anfragen",
                    "hashtags": ["QA"],
                    "reel_idea": "",
                    "reel_format": "",
                    "reel_hook": "",
                    "reel_script": "",
                    "reel_shot_list": "",
                    "reel_on_screen_text": "",
                    "reel_caption": "",
                    "reel_editing_notes": "",
                    "citations": [],
                }

        generated = ContentGenerator([FlatClient()]).generate(
            self.make_brief(),
            evidence_records=self.approved_k1_evidence(),
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertIn(self.K1_APPROVED_CLAIM, generated.public_copy)
        self.assertEqual(generated.public_copy.count("QA-Risikoaudit anfragen"), 1)

    def test_local_model_flat_reel_shape_maps_production_fields(self):
        self.assertEqual(
            _coerce_text_list(
                ["Risiko benennen", "Beleg prüfen", "Nächsten Schritt festlegen"]
            ),
            ["Risiko benennen", "Beleg prüfen", "Nächsten Schritt festlegen"],
        )

    def test_nested_carousel_slide_objects_are_reduced_to_publishable_text(self):
        slides = _coerce_carousel_slides([
            {"headline": "Problem", "body": "Risiko bleibt unsichtbar."},
            {"headline": "Prüfung", "body": "Belege schaffen Klarheit."},
            {"headline": "Schritt", "body": "QA-Risikoaudit anfragen."},
        ])

        self.assertEqual(slides[0], "Problem — Risiko bleibt unsichtbar.")

    def test_nested_reel_production_objects_are_reduced_to_text(self):
        script = _coerce_text_list([
                {"scene": "Einstieg", "voiceover": "Problem benennen"},
                {"scene": "Prüfung", "voiceover": "Beleg prüfen"},
        ])
        shots = _coerce_text_list(
            [{"shot": "Talking Head", "action": "Frage einblenden"}]
        )

        self.assertEqual(script[0], "Einstieg — Problem benennen")
        self.assertEqual(shots[0], "Talking Head — Frage einblenden")

    def test_invalid_model_shape_records_a_safe_diagnostic_reason(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["body"] = {"unexpected": "object"}

        class InvalidClient:
            provider = "local_qwen"
            model = "qwen-invalid"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([InvalidClient()]).generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertIn("body must be text", generated.provenance["failures"][0]["detail"])

    def test_semantic_claim_violation_is_repaired_by_same_model(self):
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"].update(
            {"headline": "Sokrates für den Mittelstand", "hashtags": ["PrivateKI"]}
        )
        unsafe["channel_copy"]["body"] = (
            "Diese Architektur ermöglicht Prozessautomatisierung, ohne auf Datenhoheit zu verzichten."
        )
        unsafe["channel_copy"]["carousel_slides"] = ["Problem", "Architektur", "Ergebnis"]
        repaired = self.valid_ai_payload()
        repaired["channel_copy"].update(
            {"headline": "Sokrates für den Mittelstand", "hashtags": ["PrivateKI"]}
        )
        repaired["channel_copy"]["body"] = (
            "Sokrates Private AI positioniert KI-Nutzung für den Mittelstand mit Fokus auf "
            "Datenschutz und internes Wissen. Welche Anforderung möchten Geschäftsführer "
            "zuerst einordnen?"
        )
        repaired["channel_copy"]["carousel_slides"] = [
            "Private KI im Mittelstand",
            "Datenschutz und internes Wissen im Fokus",
            "Private-KI-Erstgespräch anfragen",
        ]

        class RepairingClient:
            provider = "local_qwen"
            model = "qwen-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return unsafe if len(self.calls) == 1 else repaired

        client = RepairingClient()
        exact_claim = (
            "Sokrates Private AI positioniert KI-Nutzung für den Mittelstand mit Fokus auf "
            "Datenschutz und internes Wissen."
        )
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k2",
                campaign="KI (Sokrates)",
                persona="Geschäftsführer und IT-Leiter",
                format="carousel",
                objective="Sokrates sachlich positionieren.",
                cta="Private-KI-Erstgespräch anfragen",
            ),
            evidence_records=[
                {
                    "claim": exact_claim,
                    "approved_for_public_use": True,
                }
            ],
        )

        self.assertEqual(len(client.calls), 2)
        self.assertIn("validation_feedback", client.calls[1]["user_prompt"])
        repair_contract = json.loads(client.calls[1]["user_prompt"].splitlines()[-1])
        self.assertEqual(repair_contract["must_copy_verbatim"], [exact_claim])
        self.assertIn(
            "do not turn it into a question",
            repair_contract["instruction"],
        )
        self.assertEqual(
            repair_contract["audience_anchor_exact"],
            "Geschäftsführer und IT-Leiter",
        )
        self.assertEqual(
            repair_contract["cta_exact"], "Private-KI-Erstgespräch anfragen"
        )
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertEqual(generated.provenance["validation_failures"], 1)
        self.assertNotIn("Architektur", generated.public_copy)

    def test_missing_evidence_and_audience_anchor_trigger_same_model_repair(self):
        first = self.valid_ai_payload()
        repaired = self.valid_ai_payload()
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        repaired["channel_copy"]["body"] = (
            f"{claim} Welche QA-Frage möchten IT-Leiter zuerst prüfen?"
        )

        class ContractRepairClient:
            provider = "local_qwen"
            model = "qwen-contract-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return first if len(self.calls) == 1 else repaired

        client = ContractRepairClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k1",
                persona="IT-Leiter und QA-Verantwortliche",
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertIn(claim, generated.public_copy)
        self.assertIn("IT-Leiter", generated.public_copy)

    def test_missing_audience_anchor_is_recorded_deterministic_structure_fill(self):
        payload = self.valid_ai_payload()
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        payload["channel_copy"]["body"] = claim

        class AudienceFillClient:
            provider = "local_qwen"
            model = "qwen-audience-fill"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return payload

        client = AudienceFillClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k1",
                persona="IT-Leiter und QA-Verantwortliche",
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertIn("IT-Leiter und QA-Verantwortliche", generated.public_copy)
        self.assertTrue(
            any(
                note.startswith("Zielgruppenansprache")
                for note in generated.review_notes
            )
        )

    def test_audience_fill_cannot_exceed_channel_body_limit(self):
        claim = (
            "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
            "strukturiert prüfen und priorisieren."
        )
        payload = self.valid_ai_payload()
        payload["channel_copy"]["body"] = (
            claim + (" " * (6000 - (2 * len(claim)))) + claim
        )

        class FullBodyClient:
            provider = "local_qwen"
            model = "qwen-full-body"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return payload

        client = FullBodyClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k1",
                persona="IT-Leiter und QA-Verantwortliche",
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(client.calls, 3)
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertTrue(
            all(
                "6000-character limit" in failure["detail"]
                for failure in generated.provenance["failures"]
            )
        )

    def test_evergreen_recency_claim_is_repaired_by_same_model(self):
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"]["body"] = (
            "Der neueste aktuelle Trend dieser Woche zeigt klar: "
            + unsafe["channel_copy"]["body"]
        )
        repaired = self.valid_ai_payload()

        class RepairingRecencyClient:
            provider = "local_qwen"
            model = "qwen-recency-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return unsafe if len(self.calls) == 1 else repaired

        client = RepairingRecencyClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(content_mode="evergreen"),
            evidence_records=self.approved_k1_evidence(),
        )

        self.assertEqual(len(client.calls), 2)
        self.assertIn("validation_feedback", client.calls[1]["user_prompt"])
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertEqual(generated.provenance["validation_failures"], 1)
        self.assertNotIn("neueste", generated.public_copy.casefold())

    def test_raw_stqb_source_typo_is_normalized_and_public_output_is_repaired(self):
        source_one = "https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln"
        source_two = "https://glossary.istqb.org/de_DE/search/testautomatisierung"
        unsafe = self.valid_ai_payload()
        approved_body = unsafe["channel_copy"]["body"]
        unsafe["channel_copy"]["body"] = (
            f"Die STQB-Definition ordnet Testautomatisierung ein. {approved_body}"
        )
        unsafe["citations"] = [
            {"url": source_one, "label": "STQB-Regeln", "supports": "STQB-Definition"},
            {"url": source_two, "label": "ISTQB-Glossar", "supports": "ISTQB-Definition"},
        ]
        repaired = self.valid_ai_payload()
        repaired["channel_copy"]["body"] = approved_body
        repaired["citations"] = list(unsafe["citations"])

        class AcronymRepairClient:
            provider = "local_qwen"
            model = "qwen-acronym-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return unsafe if len(self.calls) == 1 else repaired

        client = AcronymRepairClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                trend_id="trend-istqb",
                trend_summary="Testautomatisierung: 6 Regeln + STQB-Definition",
                trend_sources=[source_one, source_two],
                citations=[
                    {
                        "url": source_one,
                        "title": "Testautomatisierung: 6 Regeln + STQB-Definition",
                        "snippet": "Die STQB-Definition und sechs Regeln.",
                    },
                    {
                        "url": source_two,
                        "title": "ISTQB Glossary",
                        "snippet": "ISTQB definition of test automation.",
                    },
                ],
            ),
            evidence_records=self.approved_k1_evidence(),
        )

        prompt_context = json.loads(client.calls[0]["user_prompt"])
        self.assertIsNone(re.search(r"(?i)\bSTQB\b", json.dumps(prompt_context, ensure_ascii=False)))
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertIsNone(re.search(r"(?i)\bSTQB\b", generated.public_copy))
        self.assertTrue(
            all(
                re.search(r"(?i)\bSTQB\b", json.dumps(citation, ensure_ascii=False)) is None
                for citation in generated.citations
            )
        )

    def test_semantic_repair_is_bounded_to_three_model_calls(self):
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"]["body"] = "Diese Architektur ermöglicht Prozessautomatisierung."
        unsafe["channel_copy"]["carousel_slides"] = ["Problem", "Architektur", "Ergebnis"]

        class AlwaysUnsafeClient:
            provider = "local_qwen"
            model = "qwen-bounded"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return unsafe

        client = AlwaysUnsafeClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k2",
                campaign="KI (Sokrates)",
                format="carousel",
                cta="Private-KI-Erstgespräch anfragen",
            )
        )

        self.assertEqual(client.calls, 3)
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(len(generated.provenance["failures"]), 3)

    def test_safe_carousel_structure_fill_is_explicitly_recorded(self):
        claim = (
            "WAMOCON dokumentiert ein Portfolio von mehr als 50 ausgelieferten "
            "Anwendungen in sieben Kategorien."
        )
        payload = self.valid_ai_payload()
        payload["channel_copy"]["headline"] = "Portfolio-Nachweis"
        payload["channel_copy"]["body"] = (
            f"{claim} Welche Frage ist für IT-Leiter Thomas zuerst zu prüfen?"
        )
        payload["channel_copy"]["hashtags"] = ["Anwendungsportfolio"]
        payload["channel_copy"]["carousel_slides"] = [
            "Portfolio-Nachweis",
            "Mehr als 50 Anwendungen",
            "Sieben Kategorien",
        ]

        class SafePortfolioClient:
            provider = "local_qwen"
            model = "qwen-portfolio"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([SafePortfolioClient()]).generate(
            self.make_brief(
                campaign_id="k5",
                campaign="App-Entwicklung (50+ Portfolio)",
                format="portfolio_carousel",
                cta="App-Modernisierungscheck anfragen",
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertEqual(len(generated.channel_copy["carousel_slides"]), 4)
        self.assertIn(claim, generated.channel_copy["carousel_slides"])
        self.assertEqual(
            generated.channel_copy["carousel_slides"][-1],
            "App-Modernisierungscheck anfragen",
        )
        self.assertTrue(generated.review_notes[0].startswith("Carousel-Struktur"))

    def test_complete_k4_reel_gets_recorded_consent_governance_fill(self):
        claim = (
            "WAMOCON kann Team-, Kultur- und Arbeitsalltagseinblicke für Employer Branding "
            "und Vertrauensaufbau nutzen, sofern Personenfreigaben vorliegen."
        )
        payload = self.valid_ai_payload()
        public_caption = f"{claim} Welche Frage haben Bewerber vor einem Team-Einblick?"
        payload["channel_copy"].update(
            {
                "headline": "",
                "body": "",
                "caption": public_caption,
                "hashtags": ["EmployerBranding"],
            }
        )
        payload["reel"] = {
            "idea": "Ein geplanter Team-Einblick",
            "format": "9:16 Reel-Produktionsplan",
            "hook": "Was sollten Bewerber vor einem Team-Einblick wissen?",
            "script": [claim, "Bewerber stellen eine Frage.", "Team kennenlernen"],
            "shot_list": ["Planungskarte", "Neutrale Karte", "CTA-Endkarte"],
            "on_screen_text": ["Produktionsplan", "Team kennenlernen"],
            "caption": public_caption,
            "cta": "Team kennenlernen",
            "editing_notes": "Erst nach reale Medien Einwilligungen dokumentieren",
        }

        class K4Client:
            provider = "local_qwen"
            model = "qwen-k4"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([K4Client()]).generate(
            self.make_brief(
                campaign_id="k4",
                campaign="Mitarbeiter-Storys / Behind-the-Scenes",
                persona="Bewerber und B2B-Entscheider",
                channel="Instagram",
                format="reel",
                cta="Team kennenlernen",
                hashtags=["EmployerBranding"],
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        production_text = "\n".join(generated.reel["shot_list"])
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertIn("reale Medien", production_text)
        self.assertIn("Einwilligungen vor der Produktion dokumentieren", production_text)
        self.assertIn("Erst nach", production_text)
        self.assertEqual(generated.reel["editing_notes"], K4_GOVERNANCE_DIRECTION_DE)
        self.assertNotIn("Erst nach reale Medien", generated.reel["editing_notes"])

    def test_k4_governance_fill_cannot_exceed_reel_schema_bounds(self):
        claim = (
            "WAMOCON kann Team-, Kultur- und Arbeitsalltagseinblicke für Employer Branding "
            "und Vertrauensaufbau nutzen, sofern Personenfreigaben vorliegen."
        )

        class BoundaryClient:
            provider = "local_qwen"
            model = "qwen-k4-boundary"
            route_name = "local_content_draft"

            def __init__(self, payload):
                self.payload = payload
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return self.payload

        def k4_payload():
            payload = self.valid_ai_payload()
            caption = f"{claim} Welche Frage haben Bewerber vor einem Team-Einblick?"
            payload["channel_copy"].update(
                {
                    "headline": "",
                    "body": "",
                    "caption": caption,
                    "hashtags": ["EmployerBranding"],
                }
            )
            payload["reel"] = {
                "idea": "Ein geplanter Team-Einblick",
                "format": "9:16 Reel-Produktionsplan",
                "hook": "Was sollten Bewerber vor einem Team-Einblick wissen?",
                "script": [claim, "Bewerber stellen eine Frage.", "Team kennenlernen"],
                "shot_list": ["Planungskarte", "Neutrale Karte", "CTA-Endkarte"],
                "on_screen_text": ["Produktionsplan", "Team kennenlernen"],
                "caption": caption,
                "cta": "Team kennenlernen",
                "editing_notes": "Ruhige Schnitte und klare Typografie.",
            }
            return payload

        full_list_payload = k4_payload()
        full_list_payload["reel"]["shot_list"] = ["Planungskarte"] * 12
        client = BoundaryClient(full_list_payload)
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k4",
                campaign="Mitarbeiter-Storys / Behind-the-Scenes",
                persona="Bewerber und B2B-Entscheider",
                channel="Instagram",
                format="reel",
                cta="Team kennenlernen",
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(client.calls, 3)
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertTrue(
            all(
                "12-item limit" in failure["detail"]
                for failure in generated.provenance["failures"]
            )
        )
        self.assertLessEqual(len(generated.reel["shot_list"]), 12)
        self.assertLessEqual(len(generated.reel["editing_notes"]), 1000)

    def test_thin_lfa_reel_gets_safe_production_structure_and_cta(self):
        claim = "LFA ist ein digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder."
        payload = self.valid_ai_payload()
        payload["channel_copy"].update(
            {"headline": "LFA", "body": "", "caption": claim, "hashtags": ["Ausbildung"]}
        )
        payload["reel"] = {
            "idea": "LFA kurz einordnen",
            "format": "9:16 Reel",
            "hook": "LFA",
            "script": [claim],
            "shot_list": ["Textkarte"],
            "on_screen_text": ["LFA"],
            "caption": claim,
            "cta": "",
            "editing_notes": "",
        }

        class ThinReelClient:
            provider = "local_qwen"
            model = "qwen-thin-reel"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([ThinReelClient()]).generate(
            self.make_brief(
                campaign_id="k3",
                campaign="LFA - Lernzentrum Für Azubis",
                channel="Instagram",
                format="reel",
                cta="LFA-Demo anfragen",
                hashtags=["Ausbildung", "FIAE"],
            ),
            evidence_records=[
                {"claim": claim, "approved_for_public_use": True}
            ],
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertIn("LFA-Demo anfragen", generated.reel["script"])
        self.assertIn("LFA-Demo anfragen", generated.reel["on_screen_text"])
        self.assertIn("für Fachinformatiker-Azubis", generated.public_copy)


if __name__ == "__main__":
    unittest.main()
