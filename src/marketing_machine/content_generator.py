from __future__ import annotations

from dataclasses import dataclass

from .schemas import ContentBrief


@dataclass(frozen=True)
class GeneratedContent:
    public_copy: str
    review_notes: list[str]


def generate_public_copy(brief: ContentBrief) -> GeneratedContent:
    """Create a proof-led draft that is useful even without a live model call.

    This intentionally avoids invented numbers, customer names, or outcomes. A
    local model can polish the copy later, but the system must always have a
    deterministic safe fallback.
    """

    channel = brief.channel.strip().lower()
    german = _is_german(brief)
    if channel == "instagram":
        public_copy = _instagram_copy_de(brief) if german else _instagram_copy_en(brief)
    elif channel in {"email", "newsletter"}:
        public_copy = _email_copy_de(brief) if german else _email_copy_en(brief)
    else:
        public_copy = _linkedin_copy_de(brief) if german else _linkedin_copy_en(brief)

    notes = _review_notes_de(brief) if german else _review_notes_en(brief)
    return GeneratedContent(public_copy=public_copy.strip(), review_notes=notes)


def _is_german(brief: ContentBrief) -> bool:
    language = getattr(brief, "language", "de-DE").strip().lower()
    return language in {"de", "de-de", "de_at", "de-at", "de_ch", "de-ch"} or language.startswith("de")


def _review_notes_de(brief: ContentBrief) -> list[str]:
    return [
        f"Nachweis vor Veröffentlichung prüfen: {', '.join(brief.proof_sources)}",
        f"Nur eine Variable testen: {brief.test_variable}",
        f"Mit UTM-Kampagne tracken: {brief.utm.get('utm_campaign', '')}",
        "Vor Planung prüfen: Nachweis, Zustimmung, Markenfit, Datenschutz und KI-Kennzeichnung.",
    ]


def _review_notes_en(brief: ContentBrief) -> list[str]:
    return [
        f"Proof required before publishing: {', '.join(brief.proof_sources)}",
        f"Test one variable only: {brief.test_variable}",
        f"Track with UTM campaign: {brief.utm.get('utm_campaign', '')}",
        "Human must verify proof, consent, brand fit, privacy, and AI disclosure before scheduling.",
    ]


def _linkedin_copy_de(brief: ContentBrief) -> str:
    persona = brief.persona or "B2B-Entscheider"
    proof = ", ".join(brief.proof_sources)
    return f"""LinkedIn-Entwurf

{_hook_for_de(brief)}

Für {persona} ist die wichtigste Frage nicht, ob das Thema interessant klingt. Entscheidend ist, ob daraus gerade vermeidbares Geschäftsrisiko entsteht.

Worum es geht:
- versteckte Risiken im aktuellen Prozess oder System sichtbar machen
- nur Aussagen nutzen, die durch echte Nachweise belegt sind
- den nächsten sinnvollen Schritt definieren, bevor weiteres Budget gebunden wird

Nachweis zum Anhängen: {proof}

Angebot: {brief.objective}

Nächster Schritt: {brief.cta}

Interne Testhypothese: {brief.hypothesis}
"""


def _instagram_copy_de(brief: ContentBrief) -> str:
    tags = brief.hashtags[:5]
    tag_line = " ".join(f"#{tag.strip().lstrip('#')}" for tag in tags if tag.strip())
    return f"""Instagram-Entwurf

{_hook_for_de(brief)}

Speichern Sie diesen Beitrag, wenn Ihr Team technische Arbeit stärker mit messbarem Geschäftsnutzen verbinden will.

Fokus:
1. klares Problem
2. echter Nachweis
3. ein konkreter nächster Schritt

Nächster Schritt: {brief.cta}

{tag_line}
"""


def _email_copy_de(brief: ContentBrief) -> str:
    return f"""Betreff: {brief.cta}

Guten Tag,

{_hook_for_de(brief)}

Diese Kampagne konzentriert sich auf ein konkretes Angebot:

{brief.objective}

Wichtig ist: Die Kommunikation bleibt nachweisbasiert. Öffentlich genutzt werden nur Aussagen, die durch diese Quellen belegt sind:
{', '.join(brief.proof_sources)}

Wenn das für Sie relevant ist, ist der nächste Schritt:
{brief.cta}

Beste Grüße
WAMOCON
"""


def _hook_for_de(brief: ContentBrief) -> str:
    campaign = brief.campaign.lower()
    if "qa" in campaign or "risk" in campaign or "risiko" in campaign:
        return "Viele QA-Risiken werden erst sichtbar, wenn sie bereits teuer geworden sind."
    if "sokrates" in campaign or "private ai" in campaign or "ki" in campaign:
        return "KI wird für den Mittelstand erst dann wertvoll, wenn internes Wissen auch intern bleibt."
    if "app" in campaign or "modernisierung" in campaign or "modernization" in campaign:
        return "Veraltete interne Apps fallen selten auf einmal aus. Sie bremsen Teams Woche für Woche."
    return brief.objective.rstrip(".") + "."


def _linkedin_copy_en(brief: ContentBrief) -> str:
    persona = brief.persona or "B2B buyer"
    proof = ", ".join(brief.proof_sources)
    return f"""Draft LinkedIn post

{_hook_for_en(brief)}

For {persona}, the practical question is not whether the topic is interesting. The question is whether it creates avoidable business risk right now.

What we check:
- where the current process or system creates hidden risk
- which proof already exists and which claims still need evidence
- what should be fixed first before more budget is spent

Proof to attach: {proof}

Offer: {brief.objective}

CTA: {brief.cta}

Internal hypothesis: {brief.hypothesis}
"""


def _instagram_copy_en(brief: ContentBrief) -> str:
    tags = brief.hashtags[:5]
    tag_line = " ".join(f"#{tag.strip().lstrip('#')}" for tag in tags if tag.strip())
    return f"""Draft Instagram caption

{_hook_for_en(brief)}

Swipe/save this if your team is trying to turn technical work into measurable business progress.

Focus:
1. clear problem
2. real proof
3. one next action

CTA: {brief.cta}

{tag_line}
"""


def _email_copy_en(brief: ContentBrief) -> str:
    return f"""Subject: {brief.cta}

Hi,

{_hook_for_en(brief)}

This campaign is built around one concrete offer:

{brief.objective}

The reason to act is proof-led, not hype-led. We will only use claims that are backed by:
{', '.join(brief.proof_sources)}

If this is relevant, the next step is simple:
{brief.cta}

Best regards
WAMOCON
"""


def _hook_for_en(brief: ContentBrief) -> str:
    campaign = brief.campaign.lower()
    if "qa" in campaign or "risk" in campaign:
        return "Most QA risk is not visible in dashboards until it has already become expensive."
    if "sokrates" in campaign or "private ai" in campaign or "ki" in campaign:
        return "AI only becomes useful for Mittelstand teams when private company knowledge stays private."
    if "app" in campaign or "modernization" in campaign:
        return "Old internal apps rarely fail all at once. They slow teams down every week."
    return brief.objective.rstrip(".") + "."
