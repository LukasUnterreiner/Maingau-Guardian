"""Readable names for internal codes (German, English): eligibility rules, channels, churn drivers, statuses.

The codes stay in every structured field (exclusion_reasons, restriction_codes, channel, the decision log). Texts that
an employee reads, such as the engine's explanation, copilot answers, warnings and the facts sent to the AI, use these
names instead.
"""
from __future__ import annotations

import re

LABELS: dict[str, tuple[str, str]] = {
    "CONSENT_WITHDRAWN": ("Einwilligung widerrufen", "consent withdrawn"),
    "CONSENT_NOT_GIVEN": ("keine Einwilligung für den Kanal", "no channel consent"),
    "CONSENT_UNKNOWN": ("Einwilligung unbekannt", "consent unknown"),
    "CONSENT_DOI_MISSING": ("Double-Opt-in fehlt", "no double opt-in"),
    "PROFILING_CONSENT_WITHDRAWN": ("Profiling-Einwilligung widerrufen", "profiling consent withdrawn"),
    "PROFILING_CONSENT_NOT_GIVEN": ("keine Profiling-Einwilligung", "no profiling consent"),
    "PROFILING_CONSENT_UNKNOWN": ("Profiling-Einwilligung unbekannt", "profiling consent unknown"),
    "PROFILING_CONSENT_MISSING": ("keine Profiling-Einwilligung", "no profiling consent"),
    "OPEN_COMPLAINT_BLOCKS_MARKETING": ("offene Beschwerde", "open complaint"),
    "DUNNING_BLOCKS_MARKETING": ("offene Mahnung", "open dunning"),
    "CANCELLATION_PENDING_BLOCKS_MARKETING": ("Kündigung liegt vor", "cancellation received"),
    "CONTACT_FREQUENCY_LIMIT": ("Kontaktlimit erreicht", "contact limit reached"),
    "CONTACT_MIN_GAP": ("letzter Kontakt zu kurz her", "contacted too recently"),
    "PRODUCT_ALREADY_HELD": ("bereits vorhanden", "already held"),
    "PREREQUISITE_MISSING": ("Voraussetzung fehlt", "prerequisite missing"),
    "CHANNEL_NOT_AVAILABLE": ("Kanal nicht verfügbar", "channel not available"),
    "ACTION_DISABLED_BY_SETTINGS": ("in den Einstellungen deaktiviert", "disabled in settings"),
    "NO_SERVICE_ISSUE": ("kein Service-Anliegen", "no service issue"),
    "NO_CUSTOMER_REQUEST": ("keine Kundenanfrage", "no customer request"),
}

# lower-case codes that show up in texts: channels, churn drivers, approval status, decision process
NAMES: dict[str, tuple[str, str]] = {
    "newsletter_email": ("Newsletter-E-Mail", "newsletter e-mail"),
    "portal_popup": ("Portal-Pop-up", "portal pop-up"),
    "app_push": ("App-Push", "app push"),
    "sms": ("SMS", "SMS"),
    "outbound_call": ("Anruf", "outbound call"),
    "service_email": ("Service-E-Mail", "service e-mail"),
    "service_call": ("Service-Anruf", "service call"),
    "price_guarantee_ends_90d": ("Preisgarantie endet in 90 Tagen", "price guarantee ends within 90 days"),
    "open_complaint": ("offene Beschwerde", "open complaint"),
    "tickets_12m_ge2": ("zwei oder mehr Tickets in 12 Monaten", "two or more tickets in 12 months"),
    "csat_le2": ("letzte Bewertung 1 oder 2", "last CSAT rating 1 or 2"),
    "dunning_ge2": ("Mahnstufe 2 oder höher", "dunning level 2 or higher"),
    "failed_charges_30d_ge3": ("drei oder mehr fehlgeschlagene Ladevorgänge in 30 Tagen",
                               "three or more failed charging sessions in 30 days"),
    "hems_user": ("HEMS-Nutzer", "HEMS user"),
    "pending_approval": ("wartet auf Freigabe", "pending approval"),
    "not_required": ("keine Freigabe nötig", "no approval needed"),
    "customer_inquiry_reply": ("Antwort auf eine Kundenanfrage", "reply to a customer inquiry"),
}

_CODE = re.compile(r"\b[A-Z]+(?:_[A-Z]+)+\b")
_NAME = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def label(code: str, lang: str) -> str:
    de, en = LABELS.get(code, (code.replace("_", " ").lower(),) * 2)
    return de if lang == "de" else en


def labels(codes: list[str], lang: str) -> str:
    """Comma list of readable names, duplicates removed (two codes can share one name)."""
    return ", ".join(dict.fromkeys(label(c, lang) for c in codes))


def name(code: str | None, lang: str = "en") -> str:
    """Channel, churn driver or status in words; unknown codes come back unchanged."""
    if code not in NAMES:
        return code or ""
    de, en = NAMES[code]
    return de if lang == "de" else en


def humanize(text: str, lang: str) -> str:
    """Replace known codes inside a text; anything else that looks like a code (e.g. NO_CONTACT) is kept."""
    text = _CODE.sub(lambda m: label(m.group(0), lang) if m.group(0) in LABELS else m.group(0), text)
    return _NAME.sub(lambda m: name(m.group(0), lang), text)
