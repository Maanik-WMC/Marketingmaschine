from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from typing import Any

from .schemas import LeadRecord


GENERIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "outlook.com",
    "web.de",
    "yahoo.com",
    "gmx.de",
}

INTENT_KEYWORDS = (
    "audit",
    "check",
    "risiko",
    "termin",
    "beratung",
    "angebot",
    "anfrage",
    "modernisierung",
    "ki",
)


def build_lead_intake(payload: dict[str, Any], *, source_verified: bool) -> dict[str, Any]:
    errors = validate_lead_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    consent_given = coerce_bool(payload.get("consent_given"))
    email = normalize(payload.get("email"))
    company = normalize(payload.get("company"))
    message = normalize(payload.get("message"))
    phone = normalize(payload.get("phone"))
    utm = normalize_utm(payload.get("utm", {}))
    warnings = lead_warnings(payload, source_verified=source_verified)
    risk_flags = list(warnings)
    score = score_lead(
        email=email,
        company=company,
        phone=phone,
        message=message,
        consent_given=consent_given,
        source_verified=source_verified,
        utm=utm,
    )
    next_action = decide_next_action(
        qualification_score=score,
        consent_given=consent_given,
        email=email,
        phone=phone,
        source_verified=source_verified,
    )
    routing_allowed = consent_given and bool(email or phone) and next_action in {
        "sales_follow_up",
        "manual_qualification",
    }

    record = LeadRecord(
        id=normalize(payload.get("id")) or f"lead-{uuid.uuid4().hex[:12]}",
        source_content_id=normalize(payload.get("source_content_id")),
        campaign=normalize(payload.get("campaign")),
        offer=normalize(payload.get("offer")),
        persona=normalize(payload.get("persona")),
        utm=utm,
        consent_given=consent_given,
        company=company,
        email=email,
        contact_name=normalize(payload.get("contact_name")),
        phone=phone,
        message=message,
        qualification_score=score,
        next_action=next_action,
        source_verified=source_verified,
        routing_allowed=routing_allowed,
        risk_flags=risk_flags,
    )

    return {
        "lead": record.to_dict(),
        "source_verified": source_verified,
        "routing_allowed": routing_allowed,
        "warnings": warnings,
        "crm_payload": crm_payload(record) if routing_allowed else {},
        "mautic_payload": mautic_payload(record) if consent_given and bool(email) else {},
    }


def validate_lead_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("source_content_id", "campaign", "offer", "persona")
    for key in required:
        if not normalize(payload.get(key)):
            errors.append(f"{key} is required")

    if "consent_given" not in payload:
        errors.append("consent_given is required")
    elif not isinstance(payload.get("consent_given"), bool | str | int):
        errors.append("consent_given must be true or false")

    email = normalize(payload.get("email"))
    if email and not valid_email(email):
        errors.append("email is invalid")

    utm = payload.get("utm", {})
    if not isinstance(utm, dict):
        errors.append("utm must be an object")

    return errors


def lead_warnings(payload: dict[str, Any], *, source_verified: bool) -> list[str]:
    warnings: list[str] = []
    email = normalize(payload.get("email"))
    phone = normalize(payload.get("phone"))
    if not source_verified:
        warnings.append("source_content_id was not found in stored campaign states")
    if not email and not phone:
        warnings.append("lead has no email or phone for follow-up")
    if email and email_domain(email) in GENERIC_EMAIL_DOMAINS:
        warnings.append("email uses a generic domain; qualify manually")
    utm = normalize_utm(payload.get("utm", {}))
    missing_utm = [key for key in ("utm_source", "utm_medium", "utm_campaign") if not utm.get(key)]
    if missing_utm:
        warnings.append(f"missing UTM fields: {', '.join(missing_utm)}")
    if not coerce_bool(payload.get("consent_given")):
        warnings.append("consent missing; do not route to marketing automation")
    return warnings


def score_lead(
    *,
    email: str,
    company: str,
    phone: str,
    message: str,
    consent_given: bool,
    source_verified: bool,
    utm: dict[str, str],
) -> int:
    score = 0
    if source_verified:
        score += 20
    if all(utm.get(key) for key in ("utm_source", "utm_medium", "utm_campaign")):
        score += 15
    if consent_given:
        score += 25
    if company:
        score += 15
    if email:
        score += 8 if email_domain(email) in GENERIC_EMAIL_DOMAINS else 15
    if phone:
        score += 5
    if any(keyword in message.lower() for keyword in INTENT_KEYWORDS):
        score += 5
    return min(score, 100)


def decide_next_action(
    *,
    qualification_score: int,
    consent_given: bool,
    email: str,
    phone: str,
    source_verified: bool,
) -> str:
    if not consent_given:
        return "consent_required"
    if not email and not phone:
        return "contact_missing"
    if not source_verified:
        return "manual_source_review"
    if qualification_score >= 75:
        return "sales_follow_up"
    if qualification_score >= 55:
        return "manual_qualification"
    return "nurture_or_disqualify"


def crm_payload(record: LeadRecord) -> dict[str, Any]:
    return {
        "external_id": record.id,
        "source_content_id": record.source_content_id,
        "campaign": record.campaign,
        "persona": record.persona,
        "offer": record.offer,
        "qualification_score": record.qualification_score,
        "next_action": record.next_action,
        "contact": {
            "name": record.contact_name,
            "company": record.company,
            "email": record.email,
            "phone": record.phone,
        },
        "utm": record.utm,
        "message": record.message,
        "risk_flags": record.risk_flags,
    }


def mautic_payload(record: LeadRecord) -> dict[str, Any]:
    return {
        "email": record.email,
        "firstname": record.contact_name,
        "company": record.company,
        "tags": [
            "wamocon-marketing-machine",
            slug(record.campaign),
            slug(record.persona),
            slug(record.offer),
        ],
        "utm": record.utm,
        "source_content_id": record.source_content_id,
    }


def normalize(value: Any) -> str:
    return str(value or "").strip()


def normalize_utm(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): normalize(item) for key, item in value.items()}


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on"}
    return False


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def email_domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].lower() if "@" in value else ""


def slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean or "unknown"


def make_json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value
