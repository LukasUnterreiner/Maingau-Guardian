"""Readable names for the eligibility rule codes (German, English).

The codes stay in every structured field (exclusion_reasons, restriction_codes, the decision log). Texts that an
employee reads, such as copilot answers, warnings and the facts sent to the AI, use these labels instead.
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

_CODE = re.compile(r"\b[A-Z]+(?:_[A-Z]+)+\b")


def label(code: str, lang: str) -> str:
    de, en = LABELS.get(code, (code.replace("_", " ").lower(),) * 2)
    return de if lang == "de" else en


def labels(codes: list[str], lang: str) -> str:
    """Comma list of readable names, duplicates removed (two codes can share one name)."""
    return ", ".join(dict.fromkeys(label(c, lang) for c in codes))


def humanize(text: str, lang: str) -> str:
    """Replace known rule codes inside a text; anything else that looks like a code (e.g. NO_CONTACT) is kept."""
    return _CODE.sub(lambda m: label(m.group(0), lang) if m.group(0) in LABELS else m.group(0), text)
