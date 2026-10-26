"""Lighty: optional LLM integration for explanations and German customer drafts.

Safeguards
----------
* All numbers come from Python. The model receives a minimal fact sheet (no
  name, address, birth year, contract ids) and is told to use only those facts.
* Output is validated. Explanations may only contain numbers that appear in
  the fact sheet; customer drafts may contain no numbers, prices, percentages
  or urgency phrases and must match the Du/Sie tonality. Failing output is
  discarded and the deterministic fallback is used.
* The model never decides anything: it only phrases a decision that the
  deterministic engine already made. Every draft is stored as pending approval.
* The API key is held as a SecretStr and never logged or returned.

Protocol
--------
The wire format lives in ``llm_client.LLMClient`` and has not been verified
against hessian.AI documentation. See that module before enabling.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config.settings import AppSettings
from app.services.llm_client import ChatModel, LLMClient, LLMUnavailable

log = logging.getLogger("lighty.ai")

URGENCY_PATTERNS = [r"nur heute", r"nur noch", r"letzte chance", r"sofort", r"jetzt zugreifen", r"begrenzt",
                    r"läuft ab", r"schnell sein", r"bis morgen", r"exklusiv für sie", r"exklusiv für dich",
                    r"rabatt", r"sonderpreis", r"angebot endet"]
INFORMAL_RE = re.compile(r"\b(du|dir|dich|dein\w*|euch|euer|eure\w*)\b", re.IGNORECASE)
FORMAL_RE = re.compile(r"\b(Sie|Ihnen|Ihr|Ihre[nmrs]?)\b")
CHANNEL_MAX_CHARS = {"sms": 320, "app_push": 240, "portal_popup": 400, "newsletter_email": 1200,
                     "service_email": 1200, "outbound_call": 1500, "service_call": 1500}

PRODUCT_DESC_DE = {
    "P-EN-01": ("StromAktiv", "unseren flexiblen Stromtarif"),
    "P-EN-02": ("StromGarant", "unseren Stromtarif mit 24 Monaten Preisgarantie"),
    "P-EN-03": ("StromWärme", "unseren Stromtarif für Wärmepumpen"),
    "P-EN-04": ("GasAktiv", "unseren flexiblen Gastarif"),
    "P-EN-05": ("Dynamischer Stromtarif", "unseren dynamischen Stromtarif für Haushalte mit Smart Meter"),
    "P-MO-01": ("MAINGAU Mobilfunk", "unsere Mobilfunktarife"),
    "P-MO-02": ("Mobil Upgrade", "ein Upgrade auf den nächsten Datentarif"),
    "P-MO-03": ("Zusatz-SIM", "eine zusätzliche SIM-Karte für Ihren Haushalt"),
    "P-IN-01": ("MAINGAU Internet", "unsere Internetanschlüsse (DSL/Glasfaser)"),
    "P-SL-01": ("HEMS Starter-Set", "unser Home-Energy-Management mit App"),
    "P-SL-02": ("HEMS Speicher-Optimierung", "die Speicher-Optimierung für Ihr HEMS"),
    "P-SL-03": ("Wallbox-Integration", "das intelligente Laden über Ihr HEMS"),
    "P-SH-01": ("Balkonkraftwerk 800 W", "unser Balkonkraftwerk"),
    "P-SH-02": ("Wallbox 11 kW", "unsere Wallbox für das Laden zu Hause"),
    "P-SH-03": ("Smarte Thermostate", "unsere smarten Heizkörperthermostate"),
    "P-SH-04": ("Smart Plug 4er-Set", "unsere smarten Steckdosen mit Verbrauchsmessung"),
    "P-AS-01": ("MAINGAU Autostrom", "unsere Ladekarte und App für unterwegs"),
}


@dataclass
class AIResult:
    text: str
    subject: str | None
    source: str  # "llm" | "template_fallback"
    validation: dict[str, Any]
    fallback_reason: str | None = None


class AIService:
    def __init__(self, settings: AppSettings, llm: ChatModel | None = None):
        self.settings = settings
        self.llm = llm or LLMClient(settings)

    @property
    def enabled(self) -> bool:
        return bool(self.llm.enabled)

    def status(self) -> dict[str, Any]:
        if isinstance(self.llm, LLMClient):
            return self.llm.status()
        return {"configured": True, "protocol": "custom", "enabled": self.enabled, "protocol_verified": False,
                "model": None}

    # ------------------------------------------------------------- LLM call
    def _call(self, system: str, user: str, max_tokens: int = 400) -> str:
        try:
            return self.llm.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                     max_tokens=max_tokens)
        except LLMUnavailable as exc:
            raise RuntimeError(str(exc)) from None

    # ---------------------------------------------------------- explanation
    @staticmethod
    def fact_sheet(resp: dict[str, Any]) -> dict[str, Any]:
        """Minimal, non-identifying context for the model."""
        alts = [a for a in resp["alternatives"] if a["product_id"] != "NO_CONTACT"][:2]
        return {
            "recommended_action": resp["recommended_action_name"],
            "action_type": resp["action_type"],
            "channel": resp["channel"],
            "expected_dclv_eur": resp["expected_dclv_eur"],
            "current_clv_eur": resp["current_clv_eur"],
            "acceptance_probability_pct": None if resp["acceptance_probability"] is None
            else round(resp["acceptance_probability"] * 100, 1),
            "required_service_workflow": resp["required_service_workflow"],
            "alternatives": [{"action": a["product_name"], "expected_dclv_eur": a["expected_dclv_eur"]} for a in alts],
            "blocked_reasons": sorted({r for b in resp["blocked_actions"] for r in b["exclusion_reasons"]}),
            "engine_reason": resp["reason"],
        }

    @staticmethod
    def _numbers(text: str) -> set[str]:
        return {n.replace(",", ".").rstrip(".").lstrip("+-") for n in re.findall(r"[+-]?\d+(?:[.,]\d+)?", text)}

    def validate_explanation(self, text: str, facts: dict[str, Any]) -> dict[str, Any]:
        allowed = self._numbers(str(facts))
        allowed |= {str(int(float(n))) for n in allowed if re.fullmatch(r"\d+(\.\d+)?", n)}
        used = self._numbers(text)
        unknown = sorted(n for n in used if n not in allowed)
        ok = bool(text) and not unknown and len(text) <= 1200
        return {"passed": ok, "unknown_numbers": unknown, "length": len(text)}

    def explain(self, resp: dict[str, Any]) -> AIResult:
        facts = self.fact_sheet(resp)
        fallback = resp["reason"]
        if not self.enabled:
            return AIResult(fallback, None, "template_fallback", {"passed": True}, "AI not configured")
        system = ("You are Lighty, an internal assistant that explains decisions of MAINGAU's customer-value "
                  "engine to staff. Use ONLY the facts given. "
                  "Do not add numbers, probabilities, customer facts or recommendations that are not in the facts. "
                  "Two to three sentences, plain English.")
        try:
            text = self._call(system, f"Facts: {facts}")
        except RuntimeError as exc:
            return AIResult(fallback, None, "template_fallback", {"passed": True}, str(exc))
        val = self.validate_explanation(text, facts)
        if not val["passed"]:
            return AIResult(fallback, None, "template_fallback", val, "LLM output failed validation")
        return AIResult(text, None, "llm", val)

    # -------------------------------------------------------- customer draft
    def template(self, resp: dict[str, Any], issue: str | None) -> tuple[str | None, str]:
        """Approved German templates. Explicit Sie and Du versions, no prices, no urgency."""
        du = resp["tonality"] == "du"
        channel = resp["channel"]
        if resp["action_type"] == "service":
            issues = {
                "charging": ("bei Ihren letzten Ladevorgängen Probleme aufgetreten sind",
                             "bei deinen letzten Ladevorgängen Probleme aufgetreten sind"),
                "billing": ("es zu Ihrer Rechnung oder Zahlung noch Klärungsbedarf gibt",
                            "es zu deiner Rechnung oder Zahlung noch Klärungsbedarf gibt"),
                "complaint": ("Ihr Anliegen bei uns noch nicht abschließend geklärt ist",
                              "dein Anliegen bei uns noch nicht abschließend geklärt ist"),
            }
            issue_txt = issues.get(issue or "", ("Ihr Anliegen bei uns noch offen ist",
                                                  "dein Anliegen bei uns noch offen ist"))[int(du)]
            if channel == "service_call":
                return None, ("Gesprächsleitfaden (Service, keine Werbung, Anrede: "
                              f"{'Du' if du else 'Sie'}):\n- Begrüßung und Bezug auf das offene Anliegen.\n"
                              f"- Ansprechen, dass {issue_txt}, und um Entschuldigung bitten.\n"
                              "- Lösung anbieten und nächste Schritte verbindlich vereinbaren.\n"
                              "- Keine Produktangebote in diesem Gespräch.")
            if du:
                return ("Wir kümmern uns um dein Anliegen",
                        f"Hallo,\n\nwir haben gesehen, dass {issue_txt}. Das möchten wir für dich lösen. Unser "
                        "Kundenservice kümmert sich persönlich darum und meldet sich bei dir, um alles Weitere zu "
                        "klären. Diese Nachricht enthält keine Werbung.\n\nDein MAINGAU Energie Kundenservice")
            return ("Wir kümmern uns um Ihr Anliegen",
                    f"Guten Tag,\n\nwir haben gesehen, dass {issue_txt}. Das möchten wir für Sie lösen. Unser "
                    "Kundenservice kümmert sich persönlich darum und meldet sich bei Ihnen, um alles Weitere zu "
                    "klären. Diese Nachricht enthält keine Werbung.\n\nIhr MAINGAU Energie Kundenservice")

        name, desc = PRODUCT_DESC_DE.get(resp["product_id"], (resp["recommended_action_name"], "ein passendes Produkt"))
        if du:
            desc = desc.replace("Ihren", "deinen").replace("Ihr ", "dein ")
        if resp.get("process") == "customer_inquiry_reply":
            if channel == "service_call":
                return None, ("Gesprächsleitfaden (Antwort auf die Tarifanfrage des Kunden, Anrede: "
                              f"{'Du' if du else 'Sie'}):\n- Für die Anfrage bedanken und Bezug nehmen.\n"
                              f"- {name} vorstellen: {desc}.\n- Konditionen schriftlich ins Kundenportal stellen.\n"
                              "- Keine individuellen Preise, kein Zeitdruck. Entscheidung liegt beim Kunden.")
            if du:
                return ("Deine Tarifanfrage",
                        f"Hallo,\n\nvielen Dank für deine Anfrage zu deinem Stromtarif. Gerne stellen wir dir {desc} "
                        "vor. Die Konditionen findest du in deinem Kundenportal.\n\nDein MAINGAU Energie Kundenservice")
            return ("Ihre Tarifanfrage",
                    f"Guten Tag,\n\nvielen Dank für Ihre Anfrage zu Ihrem Stromtarif. Gerne stellen wir Ihnen {desc} "
                    "vor. Die Konditionen finden Sie in Ihrem Kundenportal.\n\nIhr MAINGAU Energie Kundenservice")
        if channel == "outbound_call":
            return None, ("Gesprächsleitfaden (Marketing, Einwilligung liegt vor, Anrede: "
                          f"{'Du' if du else 'Sie'}):\n- Begrüßung, Anlass nennen.\n"
                          f"- {name} kurz vorstellen: {desc}.\n- Keine individuellen Preise, kein Zeitdruck.\n"
                          "- Auf Wunsch Unterlagen ins Kundenportal stellen. Auf das Widerspruchsrecht hinweisen.")
        if channel in ("sms", "app_push"):
            return None, (f"MAINGAU: Passend zu deinem Vertrag stellen wir dir {desc} vor. Details im Kundenportal. "
                          "Abmeldung jederzeit im Portal möglich." if du else
                          f"MAINGAU: Passend zu Ihrem Vertrag stellen wir Ihnen {desc} vor. Details im Kundenportal. "
                          "Abmeldung jederzeit im Portal möglich.")
        if channel == "portal_popup":
            return name, (f"Passend zu deinem Vertrag: {desc}. Details und Konditionen findest du hier im Portal."
                          if du else
                          f"Passend zu Ihrem Vertrag: {desc}. Details und Konditionen finden Sie hier im Portal.")
        if du:
            return (f"{name} – passend zu deinem MAINGAU-Vertrag",
                    f"Hallo,\n\nals MAINGAU-Kundin oder -Kunde möchten wir dir {desc} vorstellen. Alle Details und "
                    "Konditionen findest du in deinem Kundenportal. Wenn du keine Informationen dieser Art mehr "
                    "erhalten möchtest, kannst du deine Einwilligung jederzeit im Kundenportal widerrufen."
                    "\n\nDein MAINGAU Energie Team")
        return (f"{name} – passend zu Ihrem MAINGAU-Vertrag",
                f"Guten Tag,\n\nals MAINGAU-Kundin oder -Kunde möchten wir Ihnen {desc} vorstellen. Alle Details und "
                "Konditionen finden Sie in Ihrem Kundenportal. Wenn Sie keine Informationen dieser Art mehr "
                "erhalten möchten, können Sie Ihre Einwilligung jederzeit im Kundenportal widerrufen."
                "\n\nIhr MAINGAU Energie Team")

    def validate_message(self, text: str, tone: str, channel: str) -> dict[str, Any]:
        lower = text.lower()
        problems = []
        if re.search(r"\d", text.replace("800 W", "").replace("11 kW", "").replace("24 Monaten", "")
                     .replace("4er-Set", "")):
            problems.append("contains_numbers_or_prices")
        if "€" in text or "eur" in re.findall(r"\beur\b", lower):
            problems.append("contains_price")
        if "%" in text:
            problems.append("contains_percentage")
        hits = [p for p in URGENCY_PATTERNS if re.search(p, lower)]
        if hits:
            problems.append("artificial_urgency:" + ",".join(hits))
        if tone == "sie" and INFORMAL_RE.search(text):
            problems.append("tonality_mismatch_informal_in_sie")
        if tone == "du" and FORMAL_RE.search(text):
            problems.append("tonality_mismatch_formal_in_du")
        if len(text) > CHANNEL_MAX_CHARS.get(channel, 1200):
            problems.append("too_long_for_channel")
        return {"passed": not problems, "problems": problems, "length": len(text)}

    def generate_message(self, resp: dict[str, Any], issue: str | None) -> AIResult:
        subject, body = self.template(resp, issue)
        base_val = self.validate_message(body, resp["tonality"], resp["channel"])
        if not self.enabled:
            return AIResult(body, subject, "template_fallback", base_val, "AI not configured")
        system = ("Du formulierst einen genehmigten deutschen Textbaustein sprachlich leicht um. Regeln: Inhalt und "
                  "Aussagen exakt beibehalten, keine Zahlen, Preise, Prozente, Rabatte oder Zeitdruck hinzufügen, "
                  f"Anrede strikt in der '{resp['tonality']}'-Form, keine neuen Fakten. Gib nur den Text zurück.")
        try:
            text = self._call(system, body, max_tokens=500)
        except RuntimeError as exc:
            return AIResult(body, subject, "template_fallback", base_val, str(exc))
        val = self.validate_message(text, resp["tonality"], resp["channel"])
        if not val["passed"]:
            return AIResult(body, subject, "template_fallback", val, "LLM output failed validation")
        return AIResult(text, subject, "llm", val)
