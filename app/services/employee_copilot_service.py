"""Lighty employee copilot: grounded guidance for service and sales staff.

Workflow for every request
--------------------------
1. Authenticate the employee and check the role (routes + ``Employee.require``).
2. Check the customer exists, and for a follow-up that the conversation belongs to
   this employee and this customer.
3. Build the customer context from the database (``CustomerContextService``),
   including the Lighty engine decision. Role and consent filters apply here.
4. Detect what the question is about and select only the relevant facts.
5. Compose a deterministic, rule-based answer from those facts. This is always
   available and is the fallback.
6. If an LLM is configured, ask it to phrase the answer from the minimised,
   grounded prompt (``AIPromptService``), then validate the output. Invalid or
   unavailable output falls back to step 5 with a warning.
7. Store the turn and return a structured result that separates verified facts,
   engine results, generated text and assumptions.

The copilot never contacts a customer, never sends anything, never changes the
engine decision and never promises discounts, credits or compensation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.services.access_control import Employee, Forbidden
from app.services.ai_prompt_service import AIPromptService, parse_json_object
from app.services.churn_model import SERVICE_DRIVERS
from app.services.conversation_service import ConversationStore
from app.services.customer_context_service import CustomerContext, CustomerContextService, Fact
from app.services.llm_client import LLMUnavailable
from app.services.recommendation_engine import NO_CONTACT
from app.services.rule_labels import humanize, labels

if TYPE_CHECKING:
    from app.services.lighty import Lighty

INTENT_PATTERNS: list[tuple[str, str]] = [
    ("briefing", r"briefing|zusammenfass|überblick|ueberblick|overview|summary|summari|vorbereit|prepare|wer ist"),
    ("opening", r"einstieg|eröffn|opening|begrüß|begruess|wie fange|wie beginne|how (do|should) i (start|open|begin)|"
                r"erste[nrs]? satz|first sentence|start the (call|conversation)"),
    ("approach", r"wie (soll|sollte|kann|muss) ich|how (should|can|do) i|approach|vorgehen|herangehen|umgehen mit|"
                 r"gespräch führen|handle|tipps?\b|advice|rat\b"),
    ("service", r"beschwerde|complaint|problem|störung|stoerung|ticket|offen|unresolved|ungelöst|fehler|fehlgeschlagen|"
                r"laden|ladevorg|charging|charge|rechnung|bill|mahn|dunning|abschlag|zahlung|payment|csat|zufrieden|"
                r"frustr|ärger|aerger|verärger|upset|angry|wütend|support|service"),
    ("retention", r"kündig|kuendig|cancel|churn|abwander|wechsel|halten|retain|retention|preisgarantie|price guarantee|"
                  r"unzufrieden|verlieren|lose|leave"),
    ("compensation", r"rabatt|discount|gutschrift|credit|kulanz|goodwill|entschädig|compensat|erstatt|refund|"
                     r"kostenlos|gratis|for free|preisnachlass|bonus|entgegenkommen"),
    ("offer", r"angebot|anbieten|offer|cross.?sell|upsell|verkauf|\bsell|produkt|product|empfehl|recommend|next best|"
              r"\bnba\b|was kann ich|what can i"),
    ("consent", r"einwilligung|consent|darf ich|may i|allowed|erlaubt|dsgvo|gdpr|werbung|kontaktier|opt.?in|opt.?out|"
                r"profiling"),
    ("why", r"warum|wieso|weshalb|\bwhy\b|begründ|reason|explain|erklär"),
    ("value", r"\bclv\b|kundenwert|customer value|\bwert\b|\bvalue\b|marge|margin|umsatz|revenue|profit|lohnt"),
    ("avoid", r"vermeid|avoid|nicht (sagen|tun|ansprechen|machen)|don't|do not|vorsicht|careful|aufpassen|no.?go"),
    ("draft", r"entwurf|draft|nachricht|message|e-?mail|formulier|schreib|write|text für|text for|\bsms\b|antwort"),
    ("history", r"historie|history|früher|frueher|bisher|previous|vorher|letzte[nrs]? (kontakt|angebot)|past"),
]
INTENT_RES = [(name, re.compile(p, re.IGNORECASE)) for name, p in INTENT_PATTERNS]

PRODUCT_PATTERNS: list[tuple[str, list[str]]] = [
    (r"autostrom|ladekarte|charge card|e-?auto|elektroauto|electric (car|vehicle)|\bev\b|unterwegs laden",
     ["P-AS-01"]),
    (r"wallbox", ["P-AS-01", "P-SH-02", "P-SL-03"]),
    (r"ladekabel|charging cable", ["P-AS-01"]),
    (r"zusatz-?sim|extra sim|second sim|weitere sim", ["P-MO-03"]),
    (r"upgrade|datenvolumen|data volume|mehr daten", ["P-MO-02"]),
    (r"mobilfunk|mobile (plan|contract|tariff)|handy|\bsim\b|smartphone", ["P-MO-01", "P-MO-02", "P-MO-03"]),
    (r"internet|\bdsl\b|glasfaser|fib(er|re)|broadband", ["P-IN-01"]),
    (r"\bhems\b|energiemanagement|energy management", ["P-SL-01", "P-SL-02", "P-SL-03"]),
    (r"speicher|batterie|battery", ["P-SL-02"]),
    (r"balkonkraftwerk|balkon-?kraftwerk|balcony|plug-?in solar", ["P-SH-01"]),
    (r"thermostat", ["P-SH-03"]),
    (r"smart ?plug|steckdose", ["P-SH-04"]),
    (r"stromgarant|preisgarantie|price guarantee", ["P-EN-02"]),
    (r"wärmepumpe|waermepumpe|heat pump|stromwärme", ["P-EN-03"]),
    (r"\bgas\b|gasaktiv|gastarif", ["P-EN-04"]),
    (r"dynamisch|dynamic tariff", ["P-EN-05"]),
    (r"stromtarif|electricity tariff|stromaktiv", ["P-EN-01", "P-EN-02", "P-EN-05"]),
]
PRODUCT_RES = [(re.compile(p, re.IGNORECASE), pids) for p, pids in PRODUCT_PATTERNS]

MISSING_INFO: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(name|namen|vorname|nachname|heißt|heisst|called)\b", re.I),
     "Der Name des Kunden ist im Datensatz nicht enthalten (pseudonymisierte Kundennummer).",
     "The customer's name is not in the dataset (pseudonymised customer id)."),
    (re.compile(r"adresse|anschrift|address|straße|strasse|wohnort", re.I),
     "Die Adresse ist nicht im Datensatz; Lighty verwendet Wohnort und PLZ bewusst nicht.",
     "The address is not in the dataset; Lighty deliberately does not use city or postcode."),
    (re.compile(r"telefonnummer|handynummer|phone number|e-?mail-?adresse|email address|kontaktdaten|contact details",
                re.I),
     "Kontaktdaten (Telefonnummer, E-Mail-Adresse) sind im Datensatz nicht enthalten.",
     "Contact details (phone number, email address) are not in the dataset."),
    (re.compile(r"geburtstag|geburtsdatum|birthday|wie alt|how old|\balter\b|\bage\b", re.I),
     "Alter bzw. Geburtsjahr verwendet Lighty bewusst nicht für die Beratung.",
     "Lighty deliberately does not use age or birth year for advice."),
    (re.compile(r"heizung|heating", re.I),
     "Die Heizungsart ist im Datensatz nicht erfasst (nur Gasvertrag bzw. Wärmepumpen-Signal).",
     "The heating system is not recorded in the data (only a gas contract or heat pump signal)."),
    (re.compile(r"einkommen|income|bonität|bonitaet|credit ?score|schufa|zahlungsart|payment method|\biban\b", re.I),
     "Zahlungs- und Bonitätsdaten nutzt Lighty bewusst nicht (payment_method wird beim Laden verworfen).",
     "Lighty deliberately uses no payment or credit data (payment_method is dropped at load time)."),
    (re.compile(r"wettbewerb|competitor|konkurrenz|anderen? anbieter|other provider|check24|verivox", re.I),
     "Angebote von Wettbewerbern sind im Datensatz nicht enthalten.",
     "Competitor offers are not in the dataset."),
]
PRICE_RE = re.compile(r"preis|price|kost|cost|wie viel|how much|günstiger|guenstiger|cheaper|konditionen|terms|tarif", re.I)

TOPICS_BY_INTENT: dict[str, set[str]] = {
    "briefing": {"profile", "communication", "service", "complaint", "charging", "billing", "churn", "recommendation",
                 "restrictions", "value", "consent"},
    "approach": {"service", "complaint", "charging", "billing", "restrictions", "recommendation", "communication",
                 "churn", "history"},
    "opening": {"communication", "service", "complaint", "charging", "billing"},
    "service": {"service", "complaint", "charging", "billing", "transcript", "history"},
    "retention": {"churn", "retention", "value", "history", "product:P-EN-02"},
    "compensation": {"compensation", "service", "complaint"},
    "offer": {"recommendation", "restrictions", "consent", "interests", "contact_policy"},
    "product": {"restrictions", "consent", "orders"},
    "consent": {"consent", "restrictions", "contact_policy"},
    "why": {"why", "recommendation", "restrictions", "churn", "value"},
    "value": {"value", "churn", "recommendation"},
    "avoid": {"restrictions", "service", "complaint", "consent", "history"},
    "draft": {"communication", "recommendation", "restrictions"},
    "history": {"history", "marketing", "service"},
    "general": {"service", "recommendation", "restrictions", "communication", "churn"},
}

ISSUE_DE = {"complaint": "Beschwerde", "billing": "Rechnung/Zahlung", "tariff": "Tarif", "moving": "Umzug",
            "autostrom": "Autostrom/Laden", "meter": "Zähler", "mobile": "Mobilfunk", "hems": "Energiemanagement",
            "meter_deregistration": "Zählerabmeldung"}


def L(language: str, de: str, en: str) -> str:
    return de if language == "de" else en


@dataclass
class Point:
    text: str
    fact_ids: list[str]


@dataclass
class Composed:
    points: list[Point]
    opening: dict[str, Any] | None
    draft: dict[str, Any] | None
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def fact_ids(self) -> list[str]:
        out: list[str] = []
        for p in self.points:
            for f in p.fact_ids:
                if f not in out:
                    out.append(f)
        return out

    def text(self) -> str:
        return "\n".join(f"- {p.text}" for p in self.points)


class CopilotUnavailable(Exception):
    """The caller required the LLM and it was not available."""


class EmployeeCopilotService:
    def __init__(self, lighty: "Lighty", store: ConversationStore, prompts: AIPromptService):
        self.lighty = lighty
        self.store = store
        self.prompts = prompts
        self.contexts = CustomerContextService(lighty)

    # ================================================================ helpers
    def _context(self, employee: Employee, customer_id: str) -> CustomerContext:
        employee.require("customer_context")
        self.lighty._require(customer_id)
        return self.contexts.build(customer_id, employee)

    @staticmethod
    def _ids(ctx: CustomerContext, *keys: str) -> list[str]:
        out: list[str] = []
        for k in keys:
            out += [f.fact_id for f in ctx.by_key(k)]
        return out

    @staticmethod
    def detect(message: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
        intents = [name for name, rx in INTENT_RES if rx.search(message)]
        pids: list[str] = []
        for rx, ids in PRODUCT_RES:
            if rx.search(message):
                pids += [p for p in ids if p not in pids]
        if pids and "product" not in intents:
            intents.append("product")
        if "compensation" in intents and "offer" in intents and not pids:
            intents.remove("offer")  # "einen Rabatt anbieten" is about compensation, not a product offer
        gaps = [(de, en) for rx, de, en in MISSING_INFO if rx.search(message)]
        return intents, pids, gaps

    @staticmethod
    def _topics(intents: list[str], pids: list[str]) -> set[str]:
        topics: set[str] = set()
        for i in intents:
            topics |= TOPICS_BY_INTENT.get(i, set())
        topics |= {f"product:{p}" for p in pids}
        return topics

    # ========================================================= situation text
    def _issues(self, ctx: CustomerContext, lang: str) -> tuple[list[str], list[str]]:
        sit, out, ids = ctx.situation, [], []
        if sit.failed_charges_30d:
            out.append(L(lang, f"{sit.failed_charges_30d} fehlgeschlagene Ladevorgänge in den letzten 30 Tagen",
                         f"{sit.failed_charges_30d} failed charging sessions in the last 30 days"))
            ids += self._ids(ctx, "charging_30d")
        if sit.open_complaint:
            out.append(L(lang, "eine offene Beschwerde", "an open complaint"))
        other = [c for c in sit.open_ticket_categories if c != "complaint"]
        for c in other:
            out.append(L(lang, f"ein offenes Ticket zum Thema {ISSUE_DE.get(c, c)}", f"an open {c} ticket"))
        if sit.open_ticket_categories:
            ids += self._ids(ctx, "open_ticket")
        if sit.callback_requested:
            out.append(L(lang, "der Kunde wünscht einen Rückruf", "the customer asked for a call back"))
            ids += self._ids(ctx, "callback_requested")
        if (sit.dunning_level or 0) >= 1:
            out.append(L(lang, f"Mahnstufe {sit.dunning_level}", f"dunning level {sit.dunning_level}"))
            ids += [f.fact_id for f in ctx.by_key("contract") if (f.value or {}).get("dunning_level")]
        if sit.cancellation_pending:
            out.append(L(lang, "eine Kündigung ist eingegangen", "a cancellation has been received"))
            ids += [f.fact_id for f in ctx.by_key("contract") if (f.value or {}).get("status") == "cancellation_pending"]
        if ctx.by_key("hems_offline"):
            out.append(L(lang, "ein HEMS-Gerät ist offline", "a HEMS device is offline"))
            ids += self._ids(ctx, "hems_offline")
        if not out:
            churn = ctx.by_key("churn")[0]
            labels = [d["label"] for d in (churn.value or {}).get("drivers", []) if d["code"] in SERVICE_DRIVERS]
            if labels:
                out.append(L(lang, "kein offener Fall, aber Service-Treiber im Abwanderungsmodell: " + ", ".join(labels),
                             "no open case, but service drivers in the churn model: " + ", ".join(labels)))
                ids.append(churn.fact_id)
        return out, ids

    def opening(self, ctx: CustomerContext) -> dict[str, Any]:
        """Suggested spoken opening in German, matching Du/Sie. Read out by the employee, never sent."""
        sit = ctx.situation
        du = sit.tonality == "du"
        if sit.failed_charges_30d:
            text = ("Ich sehe, dass es zuletzt Probleme mit deinen Ladevorgängen gab. Das tut mir leid. Lass uns das "
                    "zuerst gemeinsam klären." if du else
                    "Ich sehe, dass es zuletzt Probleme mit Ihren Ladevorgängen gab. Das tut mir leid. Lassen Sie uns "
                    "das zuerst gemeinsam klären.")
            ids = self._ids(ctx, "charging_30d", "communication")
        elif sit.open_complaint:
            cb = (" und du um einen Rückruf gebeten hast" if du else " und Sie um einen Rückruf gebeten haben") \
                if sit.callback_requested else ""
            text = (f"Ich sehe, dass dein Anliegen bei uns noch nicht abschließend geklärt ist{cb}. Das tut mir leid. "
                    "Ich kümmere mich jetzt persönlich darum." if du else
                    f"Ich sehe, dass Ihr Anliegen bei uns noch nicht abschließend geklärt ist{cb}. Das tut mir leid. "
                    "Ich kümmere mich jetzt persönlich darum.")
            ids = self._ids(ctx, "open_ticket", "callback_requested", "communication")
        elif (sit.dunning_level or 0) >= 1:
            text = ("Ich sehe, dass zu deinem Kundenkonto noch etwas offen ist. Lass uns das in Ruhe gemeinsam "
                    "anschauen." if du else
                    "Ich sehe, dass zu Ihrem Kundenkonto noch etwas offen ist. Lassen Sie uns das in Ruhe gemeinsam "
                    "anschauen.")
            ids = [f.fact_id for f in ctx.by_key("contract") if (f.value or {}).get("dunning_level")] + \
                self._ids(ctx, "communication")
        elif sit.cancellation_pending:
            text = ("Ich sehe, dass deine Kündigung bei uns eingegangen ist. Darf ich fragen, was der Anlass war? "
                    "Deine Rückmeldung hilft uns, besser zu werden." if du else
                    "Ich sehe, dass Ihre Kündigung bei uns eingegangen ist. Darf ich fragen, was der Anlass war? "
                    "Ihre Rückmeldung hilft uns, besser zu werden.")
            ids = [f.fact_id for f in ctx.by_key("contract") if (f.value or {}).get("status") == "cancellation_pending"]
            ids += self._ids(ctx, "communication")
        elif sit.tariff_inquiry:
            text = ("Danke für deine Anfrage zu deinem Stromtarif. Ich schaue mir gern mit dir an, welche Möglichkeiten "
                    "es für dich gibt." if du else
                    "Vielen Dank für Ihre Anfrage zu Ihrem Stromtarif. Ich schaue mir gern mit Ihnen an, welche "
                    "Möglichkeiten es für Sie gibt.")
            ids = self._ids(ctx, "open_ticket", "communication")
        elif ctx.by_key("hems_offline"):
            text = ("Ich sehe, dass eines deiner Geräte im Energiemanagement gerade keine Verbindung hat. Sollen wir "
                    "uns das zuerst ansehen?" if du else
                    "Ich sehe, dass eines Ihrer Geräte im Energiemanagement gerade keine Verbindung hat. Sollen wir "
                    "uns das zuerst ansehen?")
            ids = self._ids(ctx, "hems_offline", "communication")
        elif sit.open_ticket_categories:
            topic = ISSUE_DE.get(sit.open_ticket_categories[0], sit.open_ticket_categories[0])
            text = (f"Ich sehe, dass dein Anliegen zum Thema {topic} noch offen ist. Lass uns das zuerst klären." if du
                    else f"Ich sehe, dass Ihr Anliegen zum Thema {topic} noch offen ist. Lassen Sie uns das zuerst "
                         "klären.")
            ids = self._ids(ctx, "open_ticket", "communication")
        else:
            text = ("Hallo, schön, dass du dich meldest. Wie kann ich dir heute helfen?" if du else
                    "Guten Tag, schön, dass Sie sich melden. Wie kann ich Ihnen heute helfen?")
            ids = self._ids(ctx, "communication")
        return {"kind": "call_opening", "text": text, "subject": None, "channel": "conversation",
                "tonality": sit.tonality, "language": "de", "source": "template", "fact_ids": ids,
                "requires_human_approval": True, "auto_send": False,
                "validation": self.lighty.ai.validate_message(text, sit.tonality, "service_call")}

    def written_draft(self, ctx: CustomerContext) -> dict[str, Any] | None:
        """Approved template for the engine's recommended action (outbound, needs approval)."""
        rec = ctx.recommendation
        if rec["recommended_action"] == NO_CONTACT:
            return None
        sit = ctx.situation
        issue = {"charging": "charging", "billing": "billing", "complaint": "complaint"}.get(sit.issue or "")
        subject, body = self.lighty.ai.template(rec, issue if rec["action_type"] == "service" else None)
        return {"kind": "written_draft", "text": body, "subject": subject, "channel": rec["channel"],
                "tonality": rec["tonality"], "language": "de", "source": "template",
                "fact_ids": self._ids(ctx, "nba", "communication"), "requires_human_approval": True,
                "auto_send": False, "decision_id": rec["decision_id"],
                "validation": self.lighty.ai.validate_message(body, rec["tonality"], rec["channel"])}

    # ========================================================= answer pieces
    def _nba_point(self, ctx: CustomerContext, lang: str) -> Point:
        sit, rec = ctx.situation, ctx.recommendation
        ids = self._ids(ctx, "nba", "restrictions")
        if rec["recommended_action"] == NO_CONTACT:
            return Point(L(lang, "Lighty empfiehlt kein aktives Angebot: keine zulässige Aktion schlägt Nichtstun. "
                                 "Konzentrieren Sie sich auf das Anliegen des Kunden.",
                           "Lighty recommends no proactive offer: no permitted action beats doing nothing. Focus on "
                           "the customer's request."), ids)
        name, ch, val = sit.recommended_name, sit.recommended_channel, f"{rec['expected_dclv_eur']:+.2f} EUR"
        if sit.process == "service":
            req = L(lang, " Pflicht wegen offener Beschwerde.", " Required because of the open complaint.") \
                if sit.required_service_workflow else ""
            return Point(L(lang, f"Lighty empfiehlt den Service-Prozess ({rec['recommended_action']}, ohne Angebot) über "
                                 f"{ch}, erwarteter dCLV {val}.{req} Erst lösen; Angebote bewertet Lighty danach neu.",
                           f"Lighty recommends the service process ({rec['recommended_action']}, no offer) via {ch}, "
                           f"expected dCLV {val}.{req} Resolve first; Lighty re-evaluates offers afterwards."), ids)
        if sit.process == "customer_inquiry_reply":
            return Point(L(lang, f"Lighty empfiehlt, die Tarifanfrage mit {name} zu beantworten ({ch}, Antwort auf "
                                 f"Kundenanfrage, kein Werbekontakt), erwarteter dCLV {val}.",
                           f"Lighty recommends answering the tariff inquiry with {name} ({ch}, reply to the customer's "
                           f"request, not marketing), expected dCLV {val}."), ids)
        return Point(L(lang, f"Lighty empfiehlt {name} ({rec['recommended_action']}) über {ch}, erwarteter dCLV {val}. "
                             "Nur ansprechen, wenn das Anliegen des Kunden erledigt ist und er offen dafür ist; ein "
                             "Angebot braucht Freigabe.",
                       f"Lighty recommends {name} ({rec['recommended_action']}) via {ch}, expected dCLV {val}. Only "
                       "raise it once the customer's request is handled and they are open to it; any offer needs "
                       "approval."), ids)

    def _avoid_items(self, ctx: CustomerContext, lang: str) -> list[Point]:
        sit = ctx.situation
        items: list[Point] = []
        if sit.service_first:
            codes = f" ({labels(sit.service_block_codes, lang)})" if sit.service_block_codes else ""
            items.append(Point(L(lang, f"Keine Produkt- oder Tarifangebote, solange der Service-Fall offen ist{codes}.",
                                 f"No product or tariff offers while the service case is open{codes}."),
                               self._ids(ctx, "restrictions") + self._issues(ctx, lang)[1]))
        elif sit.marketing_block_codes and not ctx.decision.ranked:
            items.append(Point(L(lang, "Keine personalisierten Angebote: " + labels(sit.marketing_block_codes, lang) + ".",
                                 "No personalised offers: " + labels(sit.marketing_block_codes, lang) + "."),
                               self._ids(ctx, "restrictions")))
        items.append(Point(L(lang, "Keine Rabatte, Gutschriften, Kulanz oder Konditionen zusagen, die nicht freigegeben "
                                   "sind, und keine Ergebnisse garantieren.",
                             "Do not promise discounts, credits, goodwill or terms that are not approved, and do not "
                             "guarantee outcomes."), []))
        upset = [f for f in ctx.by_key("agent_feedback")
                 if (f.value or {}).get("dismiss_reason") == "customer_upset"
                 or (f.value or {}).get("customer_reaction") == "annoyed"]
        if upset:
            items.append(Point(L(lang, "Vorsicht mit Angeboten: Frühere Vorschläge stießen auf Verärgerung.",
                                 "Be careful with offers: earlier suggestions met with annoyance."),
                               [f.fact_id for f in upset]))
        if ctx.by_key("prior_problems"):
            items.append(Point(L(lang, "Den Kunden nicht alles erneut schildern lassen; die Vorgeschichte ist bekannt.",
                                 "Do not make the customer repeat everything; the history is known."),
                               self._ids(ctx, "prior_problems")))
        cf = ctx.by_key("contact_frequency")
        if "CONTACT_FREQUENCY_LIMIT" in sit.marketing_block_codes or "CONTACT_MIN_GAP" in sit.marketing_block_codes:
            items.append(Point(L(lang, "Keine zusätzliche Marketingansprache: Kontaktgrenze bzw. Mindestabstand greift.",
                                 "No additional marketing contact: the contact limit or minimum gap applies."),
                               [f.fact_id for f in cf]))
        items.append(Point(L(lang, f"Anrede konsequent in der {'Du' if sit.tonality == 'du' else 'Sie'}-Form halten.",
                             f"Keep to the {'Du' if sit.tonality == 'du' else 'Sie'} form of address."),
                           self._ids(ctx, "communication")))
        return items

    def _product_points(self, ctx: CustomerContext, pids: list[str], lang: str) -> list[Point]:
        sit = ctx.situation
        points: list[Point] = []
        if "P-AS-01" in pids:
            ev_orders = [f for f in ctx.by_key("order") if "product:P-AS-01" in f.topics]
            as_facts = ctx.by_key("autostrom")
            if ev_orders:
                o = ev_orders[0].value
                has_as = any(f.key != "autostrom:none" for f in as_facts)
                points.append(Point(L(lang, f"Der Kunde hat {o['product_name']} gekauft ({o['order_created_at']}, "
                                            f"Status {o['order_status']}). MAINGAU Autostrom: "
                                            f"{'bereits aktiv' if has_as else 'kein aktiver Vertrag'}.",
                                      f"The customer bought {o['product_name']} ({o['order_created_at']}, status "
                                      f"{o['order_status']}). MAINGAU Autostrom: "
                                      f"{'already active' if has_as else 'no active contract'}."),
                                    [ev_orders[0].fact_id] + [f.fact_id for f in as_facts]))
            elif as_facts:
                points.append(Point(as_facts[0].text(lang), [f.fact_id for f in as_facts]))
        for pid in pids:
            f = next(iter(ctx.by_key(f"product_status:{pid}")), None)
            if f is None:
                continue
            status = f.value["status"]
            text = f.text(lang)
            if status == "permitted":
                if pid == sit.recommended_product:
                    text += L(lang, " Das ist die aktuelle Next Best Action.", " This is the current Next Best Action.")
                elif sit.service_first:
                    text += L(lang, " Jetzt trotzdem nicht anbieten: erst das offene Service-Anliegen lösen.",
                              " Do not offer it now: resolve the open service issue first.")
                else:
                    text += L(lang, " Nicht die Next Best Action; nur erwähnen, wenn der Kunde Interesse zeigt.",
                              " Not the Next Best Action; mention only if the customer shows interest.")
            elif status == "blocked":
                text += L(lang, " Nicht aktiv anbieten. Fragt der Kunde selbst danach, allgemein informieren und auf "
                                "das Kundenportal verweisen.",
                          " Do not offer it proactively. If the customer asks, give general information and point to "
                          "the customer portal.")
            points.append(Point(text, [f.fact_id]))
        return points

    # =============================================================== compose
    def compose(self, ctx: CustomerContext, intents: list[str], pids: list[str], gaps: list[tuple[str, str]],
                message: str, lang: str) -> Composed:
        sit = ctx.situation
        points: list[Point] = []
        notes: list[str] = []
        issues, issue_ids = self._issues(ctx, lang)
        for de, en in gaps:
            points.append(Point(L(lang, de, en), []))
        if gaps and intents == ["general"]:
            intents = []  # only the missing-information answer
        want_opening = bool({"approach", "opening", "service", "briefing", "general"} & set(intents))
        want_draft = "draft" in intents

        if "compensation" in intents:
            if issues:
                points.append(Point(L(lang, "Zuerst das eigentliche Anliegen klären: " + "; ".join(issues) + ".",
                                      "First resolve the underlying issue: " + "; ".join(issues) + "."), issue_ids))
            points.append(Point(L(lang, "Lighty kann keine Rabatte, Gutschriften, Erstattungen oder Kulanz zusagen; im "
                                        "Datensatz sind dafür keine freigegebenen Konditionen hinterlegt. Bei "
                                        "berechtigtem Anliegen den internen Kulanzprozess nutzen und vor der Freigabe "
                                        "nichts zusagen.",
                                  "Lighty cannot promise discounts, credits, refunds or goodwill; the data contains no "
                                  "approved terms for this. If the request is justified, use the internal goodwill "
                                  "process and commit to nothing before it is approved."), []))
            for f in ctx.by_key("goodwill_history"):
                points.append(Point(f.text(lang), [f.fact_id]))
        if {"approach", "service", "general", "briefing"} & set(intents):
            if issues:
                points.append(Point(L(lang, "Aktuelle Situation: " + "; ".join(issues) + ".",
                                      "Current situation: " + "; ".join(issues) + "."), issue_ids))
            elif "service" in intents:
                points.append(Point(L(lang, "Kein offener Service-Fall: keine offenen Tickets, keine Mahnung, keine "
                                            "fehlgeschlagenen Ladevorgänge in 30 Tagen.",
                                      "No open service case: no open tickets, no dunning, no failed charging in 30 "
                                      "days."), self._ids(ctx, "ticket_history_12m", "restrictions")))
            if "service" in intents:
                for key in ("csat", "prior_problems", "ticket_history_12m", "customer_texts"):
                    for f in ctx.by_key(key):
                        points.append(Point(f.text(lang), [f.fact_id]))
        if "briefing" in intents:
            for key in ("profile", "value", "churn"):
                f = ctx.by_key(key)[0]
                points.append(Point(f.text(lang), [f.fact_id]))
        if {"approach", "general", "offer", "why", "briefing", "draft"} & set(intents) or \
                ({"service", "retention"} & set(intents) and sit.has_service_issue):
            points.append(self._nba_point(ctx, lang))
        if sit.service_first and ({"approach", "offer", "product", "general", "retention"} & set(intents)):
            codes = f" ({labels(sit.service_block_codes, lang)})" if sit.service_block_codes else ""
            points.append(Point(L(lang, f"Keine Verkaufsangebote während des offenen Service-Falls{codes}. Erst das "
                                        "Problem lösen.",
                                  f"No sales offers during the open service case{codes}. Solve the problem first."),
                                self._ids(ctx, "restrictions") + issue_ids))
        if "product" in intents:
            points += self._product_points(ctx, pids, lang)
            if PRICE_RE.search(message):
                notes.append(L(lang, "Lighty nennt keine Preise oder Konditionen für Angebote; diese stehen in den "
                                     "freigegebenen Unterlagen bzw. im Kundenportal.",
                               "Lighty does not quote prices or terms for offers; use the approved documents or the "
                               "customer portal."))
        if "offer" in intents and "product" not in intents:
            for f in ctx.by_key("nba_alternatives"):
                points.append(Point(f.text(lang), [f.fact_id]))
            if not sit.sales_restricted and sit.marketing_block_codes:
                points.append(Point(ctx.by_key("restrictions")[0].text(lang), self._ids(ctx, "restrictions")))
            for f in ctx.by_key("interests") + ctx.by_key("newsletter_engagement") + ctx.by_key("portal_interest"):
                points.append(Point(f.text(lang), [f.fact_id]))
        if "retention" in intents:
            churn = ctx.by_key("churn")[0]
            points.append(Point(churn.text(lang), [churn.fact_id]))
            if sit.cancellation_pending:
                points.append(Point(L(lang, "Kündigung liegt vor: Anlass erfragen und offene Service-Themen lösen. "
                                            "Lighty sperrt Marketing während einer laufenden Kündigung; keine "
                                            "Konditionen zusagen, die nicht intern freigegeben sind.",
                                      "Cancellation received: ask for the reason and resolve open service topics. "
                                      "Lighty blocks marketing while a cancellation is pending; do not commit to "
                                      "terms that are not approved internally."),
                                    self._ids(ctx, "restrictions") + [f.fact_id for f in ctx.by_key("contract")
                                                                      if "churn" in f.topics]))
            if sit.price_guarantee_until:
                pg = next(iter(ctx.by_key("product_status:P-EN-02")), None)
                points.append(Point(L(lang, f"Die Preisgarantie endet am {sit.price_guarantee_until}.",
                                      f"The price guarantee ends on {sit.price_guarantee_until}.")
                                    + (" " + pg.text(lang) if pg else ""),
                                    [f.fact_id for f in ctx.by_key("contract") if "retention" in f.topics]
                                    + ([pg.fact_id] if pg else [])))
            service_drivers = [d for d in (churn.value or {}).get("drivers", []) if d["code"] in SERVICE_DRIVERS]
            if service_drivers:
                points.append(Point(L(lang, "Ansatzpunkt: Diese Treiber lassen sich durch Service lösen: "
                                      + ", ".join(d["label"] for d in service_drivers) + ".",
                                      "Lever: these drivers can be removed by service: "
                                      + ", ".join(d["label"] for d in service_drivers) + "."), [churn.fact_id]))
            if not sit.retention_relevant:
                points.append(Point(L(lang, "Kein erhöhtes Abwanderungssignal laut Lighty; kein Retention-Angebot nötig.",
                                      "No elevated churn signal per Lighty; no retention offer needed."), [churn.fact_id]))
        if "consent" in intents:
            for f in ctx.by_key("consent") + ctx.by_key("contact_frequency"):
                points.append(Point(f.text(lang), [f.fact_id]))
            points.append(Point(ctx.by_key("restrictions")[0].text(lang), self._ids(ctx, "restrictions")))
        if "why" in intents:
            f = ctx.by_key("engine_reason")[0]
            points.append(Point(f.text(lang), [f.fact_id]))
        if "value" in intents:
            for key in ("value", "churn"):
                f = ctx.by_key(key)[0]
                points.append(Point(f.text(lang), [f.fact_id]))
        if "history" in intents:
            hist = ctx.by_key("previous_offer") + ctx.by_key("agent_feedback") + ctx.by_key("ticket_history_12m")
            for f in hist:
                points.append(Point(f.text(lang), [f.fact_id]))
            if not hist:
                points.append(Point(L(lang, "Keine früheren Angebote oder Service-Kontakte im Betrachtungszeitraum.",
                                      "No earlier offers or service contacts in the period covered."), []))
        if "avoid" in intents:
            points += self._avoid_items(ctx, lang)
        if "approach" in intents and "avoid" not in intents:
            points.append(Point(L(lang, f"Anrede: {'Du' if sit.tonality == 'du' else 'Sie'}. Zuhören, das Anliegen "
                                        "zusammenfassen, nächste Schritte verbindlich, aber ohne Zusagen zu "
                                        "Ergebnissen vereinbaren.",
                                  f"Form of address: {'Du' if sit.tonality == 'du' else 'Sie'}. Listen, summarise the "
                                  "request, agree next steps without promising outcomes."),
                                self._ids(ctx, "communication")))
        if not points:
            points.append(Point(L(lang, "Dazu liegen mir keine passenden Daten vor. Ich kann zu Service-Situation, "
                                        "Next Best Action, Einwilligungen, Abwanderungsrisiko, Produkten und "
                                        "Gesprächseinstieg helfen.",
                                  "I have no matching data for that. I can help with the service situation, the Next "
                                  "Best Action, consents, churn risk, products and how to open the conversation."),
                                []))
        seen: set[str] = set()
        unique = []
        for p in points:
            if p.text not in seen:
                seen.add(p.text)
                unique.append(p)
        return Composed(unique, self.opening(ctx) if want_opening else None,
                        self.written_draft(ctx) if want_draft else None,
                        [L(lang, de, en) for de, en in gaps], notes)

    # ============================================================ uncertainty
    def _uncertainty(self, ctx: CustomerContext, facts: list[Fact], composed: Composed, intents: list[str],
                     lang: str) -> dict[str, Any]:
        reasons, assumptions = [], []
        gaps = [f.text(lang) for f in facts if f.kind == "data_gap"] + composed.gaps
        r = ctx.decision.recommended
        if r is not None and r.acceptance.deliveries < 30 and r.valuation.action_type != "service":
            reasons.append(L(lang, f"Die Annahmewahrscheinlichkeit beruht auf wenigen Beobachtungen "
                                   f"({r.acceptance.deliveries}).",
                             f"The acceptance probability rests on few observations ({r.acceptance.deliveries})."))
        if ctx.situation.tonality_source == "default_formal":
            assumptions.append(L(lang, "Anrede Sie ist ein Standard, nicht aus Kundentexten abgeleitet.",
                                 "The Sie form is a default, not derived from customer texts."))
        assumptions.append(L(lang, "Geldwerte und Wahrscheinlichkeiten sind Modellschätzungen (CLV-Methode, beobachtete "
                                   "Quoten), keine garantierten Ergebnisse und kein Kausalnachweis.",
                             "Monetary values and probabilities are model estimates (CLV method, observed rates), not "
                             "guaranteed results and not proof of causal effect."))
        if intents == ["general"]:
            reasons.append(L(lang, "Die Frage war nicht eindeutig zuzuordnen; allgemeine Einschätzung.",
                             "The question could not be mapped clearly; general assessment."))
        for w in ctx.withheld:
            reasons.append(w["reason"])
        level = "high"
        if gaps or reasons:
            level = "medium"
        if composed.gaps or intents == ["general"]:
            level = "low" if composed.gaps else "medium"
        return {"level": level, "reasons": reasons, "data_gaps": gaps, "assumptions": assumptions}

    # ===================================================================== AI
    def _try_llm_chat(self, ctx: CustomerContext, facts: list[Fact], message: str, intents: list[str],
                      composed: Composed, history: list[dict[str, Any]], lang: str
                      ) -> tuple[dict[str, Any] | None, list[dict[str, str]], str | None]:
        warnings: list[dict[str, str]] = []
        ai = self.lighty.ai
        if not ai.enabled:
            return None, warnings, "AI not configured"
        msgs, excluded = self.prompts.chat_messages(ctx, facts, message, intents, composed.text(), history, lang,
                                                    composed.gaps)
        if excluded:
            warnings.append({"code": "untrusted_text_excluded",
                             "message": f"Customer text {', '.join(excluded)} contains instruction-like content and "
                                        "was not sent to the AI model."})
        try:
            raw = ai.llm.complete(msgs, max_tokens=self.lighty.cfg.ai_max_tokens)
        except LLMUnavailable as exc:
            warnings.append({"code": "llm_unavailable", "message": f"{exc}. Deterministic answer used."})
            return None, warnings, str(exc)
        obj = parse_json_object(raw)
        if obj is None or not isinstance(obj.get("answer"), str):
            warnings.append({"code": "llm_output_rejected", "message": "AI output was not valid JSON. Deterministic "
                                                                      "answer used."})
            return None, warnings, "LLM output not parseable"
        ids, problems = self.prompts.validate_fact_ids(obj.get("fact_ids"), facts, self._text_ids(ctx))
        problems += self.prompts.validate_text(obj["answer"], facts, ctx.customer_id)
        msg = obj.get("suggested_customer_message")
        msg_problems: list[str] = []
        if isinstance(msg, str) and msg.strip():
            msg_problems = self.prompts.validate_customer_message(msg.strip(), ctx, self._allowed_products(ctx))
        else:
            msg = None
        if problems:
            warnings.append({"code": "llm_output_rejected",
                             "message": "AI output failed validation (" + "; ".join(problems) + "). Deterministic "
                                        "answer used."})
            return None, warnings, "LLM output failed validation"
        if msg_problems:
            warnings.append({"code": "llm_message_rejected",
                             "message": "AI customer wording failed validation (" + "; ".join(msg_problems)
                                        + "). Template wording used."})
            msg = None
        unc = obj.get("uncertainty") if isinstance(obj.get("uncertainty"), str) else None
        if unc and self.prompts.validate_text(unc, facts, ctx.customer_id):
            unc = None
        return {"answer": obj["answer"].strip(), "message": msg.strip() if msg else None, "fact_ids": ids,
                "uncertainty": unc}, warnings, None

    @staticmethod
    def _text_ids(ctx: CustomerContext) -> set[str]:
        return {u.text_id for u in ctx.untrusted if not u.flagged}

    @staticmethod
    def _service_warning(ctx: CustomerContext, language: str) -> dict[str, str]:
        codes = ctx.situation.service_block_codes
        return {"code": "sales_restricted",
                "message": L(language, "Offener Servicefall: keine Verkaufsangebote", "Open service case: no sales offers")
                + (f" ({labels(codes, language)})." if codes else ".")}

    def _allowed_products(self, ctx: CustomerContext) -> set[str]:
        sit = ctx.situation
        if sit.service_first or sit.recommended_type in ("service", "no_contact"):
            return set()
        return {sit.recommended_product}

    # ================================================================== output
    def _recommended_action(self, ctx: CustomerContext) -> dict[str, Any]:
        rec, sit = ctx.recommendation, ctx.situation
        return {"decision_id": rec["decision_id"], "product_id": rec["recommended_action"],
                "product_name": rec["recommended_action_name"], "action_type": rec["action_type"],
                "channel": rec["channel"], "process": rec["process"], "expected_dclv_eur": rec["expected_dclv_eur"],
                "current_clv_eur": rec["current_clv_eur"], "acceptance_probability": rec["acceptance_probability"],
                "required_service_workflow": rec["required_service_workflow"],
                "requires_human_approval": rec["requires_human_approval"], "approval_status": rec["approval_status"],
                "sales_restricted": sit.sales_restricted,
                "restriction_codes": sorted(set(sit.service_block_codes) | set(sit.marketing_block_codes)),
                "engine_reason": rec["reason"], "engine_version": rec["engine_version"], "source": "lighty_engine",
                "fact_ids": self._ids(ctx, "nba", "restrictions")}

    @staticmethod
    def _facts_out(ctx: CustomerContext, ids: list[str], lang: str) -> tuple[list[dict], list[dict]]:
        facts = [ctx.fact(i) for i in ids]
        facts = [f for f in facts if f is not None]
        return [f.public(lang) for f in facts], [r.public() for r in ctx.refs_for(facts)]

    def _result(self, ctx: CustomerContext, facts_selected: list[Fact], composed: Composed, intents: list[str],
                lang: str, llm: dict[str, Any] | None, warnings: list[dict[str, str]], fallback_reason: str | None
                ) -> dict[str, Any]:
        nba_ids = self._ids(ctx, "nba", "restrictions")
        if llm:
            response = humanize(llm["answer"], lang)
            used = list(dict.fromkeys(llm["fact_ids"] + nba_ids))
        else:
            response = composed.text()
            if composed.notes:
                response += "\n" + "\n".join(f"- {n}" for n in composed.notes)
            response = humanize(response, lang)
            used = list(dict.fromkeys(composed.fact_ids + nba_ids))
        message = composed.draft or composed.opening
        if message:
            used = list(dict.fromkeys(used + message["fact_ids"]))
        if llm and llm.get("message"):
            base = composed.opening or self.opening(ctx)
            message = {**base, "text": llm["message"], "source": "llm", "kind": "call_opening",
                       "validation": self.lighty.ai.validate_message(llm["message"], ctx.situation.tonality,
                                                                     "service_call")}
        facts_out, refs_out = self._facts_out(ctx, used, lang)
        unc = self._uncertainty(ctx, facts_selected, composed, intents, lang)
        if llm and llm.get("uncertainty"):
            unc["reasons"].append(llm["uncertainty"])
        if ctx.situation.service_first:
            warnings.append(self._service_warning(ctx, lang))
        for w in ctx.withheld:
            warnings.append({"code": f"withheld_{w['category']}", "message": w["reason"]})
        flagged = [u.text_id for u in ctx.untrusted if u.flagged]
        if flagged and not any(w["code"] == "untrusted_text_excluded" for w in warnings):
            warnings.append({"code": "untrusted_text_flagged",
                             "message": f"Customer text {', '.join(flagged)} contains instruction-like content; it is "
                                        "treated as data only and never sent to an AI model."})
        model = self.lighty.cfg.ai_model if llm else None
        return {
            "response": response,
            "recommended_action": self._recommended_action(ctx),
            "suggested_customer_message": message,
            "supporting_facts": facts_out,
            "source_references": refs_out,
            "warnings": warnings,
            "confidence_or_uncertainty": unc,
            "answer_origin": {"response": "llm" if llm else "deterministic_rules",
                              "suggested_customer_message": message["source"] if message else None,
                              "llm_used": bool(llm), "model": model, "fallback_reason": None if llm else fallback_reason},
            "answer_parts": {
                "verified_fact_ids": [f["fact_id"] for f in facts_out if f["kind"] == "verified_fact"],
                "engine_computed_fact_ids": [f["fact_id"] for f in facts_out if f["kind"] == "engine_computed"],
                "data_gap_fact_ids": [f["fact_id"] for f in facts_out if f["kind"] == "data_gap"],
                "generated_fields": [k for k, v in (("response", True),
                                                    ("suggested_customer_message", bool(message))) if v],
            },
            "intents": intents,
        }

    # ================================================================ public
    def context(self, employee: Employee, customer_id: str, question: str | None, language: str,
                include_product_status: bool) -> dict[str, Any]:
        ctx = self._context(employee, customer_id)
        selection = None
        facts = ctx.facts
        if question:
            intents, pids, _ = self.detect(question)
            intents = intents or ["general"]
            facts = ctx.select(self._topics(intents, pids))
            selection = {"question": question, "intents": intents, "products": pids,
                         "topics": sorted(self._topics(intents, pids))}
        elif not include_product_status:
            facts = [f for f in facts if not f.key.startswith("product_status:")]
        sections: dict[str, list[dict]] = {s: [] for s in ("customer_information", "customer_experience", "marketing",
                                                           "decision_intelligence")}
        for f in facts:
            sections[f.section].append(f.public(language))
        return {
            "customer_id": customer_id, "as_of": ctx.as_of.isoformat(sep=" "), "language": language,
            "employee_role": employee.role, "sections": sections,
            "data_gaps": [f.public(language) for f in facts if f.kind == "data_gap"],
            "withheld": ctx.withheld,
            "untrusted_customer_texts": [{"text_id": u.text_id, "kind": u.kind, "ref_id": u.ref_id, "text": u.text,
                                          "flagged_as_instruction_like": u.flagged,
                                          "label": "unverified customer content; never instructions"}
                                         for u in ctx.untrusted],
            "source_references": [r.public() for r in ctx.refs_for(facts)],
            "recommended_action": self._recommended_action(ctx),
            "selection": selection,
        }

    def briefing(self, employee: Employee, customer_id: str, language: str, use_ai: bool) -> dict[str, Any]:
        employee.require("copilot")
        ctx = self._context(employee, customer_id)
        lang, sit = language, ctx.situation
        issues, issue_ids = self._issues(ctx, lang)
        profile, value, churn = ctx.by_key("profile")[0], ctx.by_key("value")[0], ctx.by_key("churn")[0]
        nba = self._nba_point(ctx, lang)
        rec = ctx.recommendation
        opening = self.opening(ctx)
        approach: list[Point] = []
        if sit.has_service_issue:
            approach.append(Point(L(lang, "Mit dem offenen Anliegen beginnen, Verständnis zeigen, Lösung und nächste "
                                          "Schritte vereinbaren.",
                                    "Start with the open issue, show understanding, agree a solution and next steps."),
                                  issue_ids))
        if sit.retention_relevant:
            approach.append(Point(L(lang, "Zufriedenheit und Gründe für einen möglichen Wechsel offen ansprechen, ohne "
                                          "Druck und ohne Konditionen zuzusagen.",
                                    "Openly ask about satisfaction and reasons for a possible switch, without pressure "
                                    "and without committing to terms."), [churn.fact_id]))
        approach.append(nba)
        approach.append(Point(L(lang, f"Anrede: {'Du' if sit.tonality == 'du' else 'Sie'}.",
                                f"Form of address: {'Du' if sit.tonality == 'du' else 'Sie'}."),
                              self._ids(ctx, "communication")))
        situation_txt = (L(lang, "Aktuell: " + "; ".join(issues) + ".", "Currently: " + "; ".join(issues) + ".")
                         if issues else L(lang, "Kein offener Service-Fall.", "No open service case."))
        overview_ids = [profile.fact_id, value.fact_id] + [f.fact_id for f in ctx.by_key("contract")] + \
            [f.fact_id for f in ctx.by_key("autostrom") + ctx.by_key("hems_devices")]
        avoid = self._avoid_items(ctx, lang)
        econ_ids = self._ids(ctx, "nba", "value", "churn")
        econ = L(lang,
                 f"Aktueller CLV {rec['current_clv_eur']:.2f} EUR; erwarteter dCLV der Empfehlung "
                 f"{rec['expected_dclv_eur']:+.2f} EUR gegenüber keinem Kontakt; Abwanderungswahrscheinlichkeit "
                 f"{sit.churn_now * 100:.1f} %. Modellschätzungen, keine garantierten Werte.",
                 f"Current CLV {rec['current_clv_eur']:.2f} EUR; expected dCLV of the recommendation "
                 f"{rec['expected_dclv_eur']:+.2f} EUR versus no contact; churn probability {sit.churn_now * 100:.1f} %. "
                 "Model estimates, not guaranteed values.")
        sections = {
            "customer_overview": {"title": L(lang, "Kundenüberblick", "Customer overview"),
                                  "text": " ".join([profile.text(lang), value.text(lang)]), "items": [],
                                  "fact_ids": overview_ids},
            "current_situation": {"title": L(lang, "Aktuelle Situation", "Current situation"), "text": situation_txt,
                                  "items": [], "fact_ids": issue_ids or self._ids(ctx, "restrictions")},
            "recommended_approach": {"title": L(lang, "Empfohlenes Vorgehen", "Recommended approach"),
                                     "text": " ".join(p.text for p in approach), "items": [p.text for p in approach],
                                     "fact_ids": list(dict.fromkeys(i for p in approach for i in p.fact_ids))},
            "suggested_opening": {"title": L(lang, "Vorgeschlagener Einstieg (Deutsch)", "Suggested opening (German)"),
                                  "text": opening["text"], "items": [], "fact_ids": opening["fact_ids"]},
            "what_to_avoid": {"title": L(lang, "Was vermeiden", "What to avoid"),
                              "text": " ".join(p.text for p in avoid), "items": [p.text for p in avoid],
                              "fact_ids": list(dict.fromkeys(i for p in avoid for i in p.fact_ids))},
            "next_best_action": {"title": "Next Best Action", "text": nba.text, "items": [], "fact_ids": nba.fact_ids},
            "economic_rationale": {"title": L(lang, "Wirtschaftliche Begründung", "Economic rationale"), "text": econ,
                                   "items": [], "fact_ids": econ_ids},
        }
        warnings: list[dict[str, str]] = []
        origin = {"response": "deterministic_rules", "suggested_customer_message": "template", "llm_used": False,
                  "model": None, "fallback_reason": None if use_ai else "AI not requested"}
        selected = ctx.select(TOPICS_BY_INTENT["briefing"])
        if use_ai and self.lighty.ai.enabled:
            out, warn, reason = self._try_llm_briefing(ctx, selected, sections, lang)
            warnings += warn
            if out:
                sections["current_situation"]["text"] = out["current_situation"]
                sections["recommended_approach"]["text"] = out["recommended_approach"]
                origin.update({"response": "llm", "llm_used": True, "model": self.lighty.cfg.ai_model})
            else:
                origin["fallback_reason"] = reason
        elif use_ai:
            origin["fallback_reason"] = "AI not configured"
        all_ids = list(dict.fromkeys(i for s in sections.values() for i in s["fact_ids"]))
        facts_out, refs_out = self._facts_out(ctx, all_ids, lang)
        composed = Composed([], opening, None)
        if sit.service_first:
            warnings.append(self._service_warning(ctx, lang))
        for w in ctx.withheld:
            warnings.append({"code": f"withheld_{w['category']}", "message": w["reason"]})
        return {
            "customer_id": customer_id, "as_of": ctx.as_of.isoformat(sep=" "), "language": lang,
            "tonality": sit.tonality, "sections": sections, "recommended_action": self._recommended_action(ctx),
            "suggested_customer_message": opening, "supporting_facts": facts_out, "source_references": refs_out,
            "warnings": warnings,
            "confidence_or_uncertainty": self._uncertainty(ctx, selected, composed, ["briefing"], lang),
            "answer_origin": origin,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _try_llm_briefing(self, ctx: CustomerContext, facts: list[Fact], sections: dict[str, Any], lang: str
                          ) -> tuple[dict[str, str] | None, list[dict[str, str]], str | None]:
        msgs = self.prompts.briefing_messages(ctx, facts, {k: sections[k]["text"] for k in
                                                           ("current_situation", "recommended_approach")}, lang)
        try:
            raw = self.lighty.ai.llm.complete(msgs, max_tokens=self.lighty.cfg.ai_max_tokens)
        except LLMUnavailable as exc:
            return None, [{"code": "llm_unavailable", "message": f"{exc}. Deterministic briefing used."}], str(exc)
        obj = parse_json_object(raw)
        if not obj or not all(isinstance(obj.get(k), str) for k in ("current_situation", "recommended_approach")):
            return None, [{"code": "llm_output_rejected", "message": "AI output was not valid JSON."}], \
                "LLM output not parseable"
        problems = []
        for k in ("current_situation", "recommended_approach"):
            problems += [f"{k}:{p}" for p in self.prompts.validate_text(obj[k], facts, ctx.customer_id, 800)]
        _, id_problems = self.prompts.validate_fact_ids(obj.get("fact_ids"), facts, self._text_ids(ctx))
        problems += id_problems
        if problems:
            return None, [{"code": "llm_output_rejected",
                           "message": "AI output failed validation (" + "; ".join(problems) + ")."}], \
                "LLM output failed validation"
        return {"current_situation": obj["current_situation"].strip(),
                "recommended_approach": obj["recommended_approach"].strip()}, [], None

    def chat(self, employee: Employee, customer_id: str, message: str, conversation_id: str | None, language: str,
             require_llm: bool = False) -> dict[str, Any]:
        from app.services.lighty import Conflict, NotFound

        employee.require("copilot")
        self.lighty._require(customer_id)
        if conversation_id:
            conv = self.store.get(conversation_id)
            if conv is None or conv["employee_id"] != employee.employee_id:
                raise NotFound(f"Conversation {conversation_id} not found")
            if conv["customer_id"] != customer_id:
                raise Conflict("This conversation belongs to a different customer; start a new conversation")
            if conv["turns"] >= self.lighty.cfg.copilot_max_turns:
                raise Conflict("Conversation turn limit reached; start a new conversation")
            history = self.store.history(conversation_id, self.lighty.cfg.copilot_history_messages)
        else:
            conv, history = None, []
        if require_llm and not self.lighty.ai.enabled:
            raise CopilotUnavailable("The AI model is not configured; retry without require_llm for the "
                                     "deterministic answer")

        ctx = self._context(employee, customer_id)
        intents, pids, gaps = self.detect(message)
        if not intents and not gaps and history:
            # follow-up such as "and what should I avoid?" without keywords: keep the previous topic
            prev = next((h["intents"] for h in reversed(history) if h["author"] == "lighty" and h["intents"]), [])
            intents = [i for i in prev if i != "general"]
        intents = intents or ["general"]
        facts = ctx.select(self._topics(intents, pids))
        composed = self.compose(ctx, intents, pids, gaps, message, language)
        llm, warnings, reason = self._try_llm_chat(ctx, facts, message, intents, composed, history, language)
        if require_llm and llm is None:
            raise CopilotUnavailable(f"The AI model did not return a usable answer ({reason})")
        result = self._result(ctx, facts, composed, intents, language, llm, warnings, reason)
        if conv is None:
            conv = self.store.create(customer_id, employee.employee_id, employee.role)
        result = {"conversation_id": conv["conversation_id"], "customer_id": customer_id, "language": language,
                  **result, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        result["turn"] = self.store.add_turn(conv["conversation_id"], message, result["response"], result)
        return result

    def conversation(self, employee: Employee, conversation_id: str) -> dict[str, Any]:
        from app.services.lighty import NotFound

        employee.require("copilot")
        conv = self.store.get(conversation_id)
        if conv is None or (conv["employee_id"] != employee.employee_id and not employee.can("all_conversations")):
            raise NotFound(f"Conversation {conversation_id} not found")
        return {**conv, "messages": self.store.messages(conversation_id)}

    def conversations(self, employee: Employee, customer_id: str | None, all_employees: bool) -> dict[str, Any]:
        employee.require("copilot")
        if all_employees and not employee.can("all_conversations"):
            raise Forbidden("Only admins may list other employees' conversations")
        rows = self.store.list(None if all_employees else employee.employee_id, customer_id)
        return {"items": rows, "total": len(rows)}

    def suggested_questions(self, employee: Employee, customer_id: str, language: str) -> dict[str, Any]:
        ctx = self._context(employee, customer_id)
        sit, lang = ctx.situation, language
        qs = [(L(lang, "Wie sollte ich mit diesem Kunden umgehen?", "How should I approach this customer?"), "approach")]
        if sit.has_service_issue:
            qs.append((L(lang, "Welche offenen Probleme hat der Kunde?", "What unresolved issues does the customer have?"),
                       "service"))
        if sit.retention_relevant:
            qs.append((L(lang, "Wie kann ich den Kunden halten?", "How can I retain this customer?"), "retention"))
        if any("product:P-AS-01" in f.topics for f in ctx.by_key("order")):
            qs.append((L(lang, "Der Kunde hat eine Wallbox gekauft. Hat er schon Autostrom?",
                         "The customer bought a wallbox. Do they already have Autostrom?"), "product"))
        if not sit.service_first and ctx.decision.ranked:
            qs.append((L(lang, "Welches Angebot passt und warum?", "Which offer fits and why?"), "offer"))
        qs.append((L(lang, "Was sollte ich im Gespräch vermeiden?", "What should I avoid in the conversation?"), "avoid"))
        qs.append((L(lang, "Wie steige ich ins Gespräch ein?", "How do I open the conversation?"), "opening"))
        return {"customer_id": customer_id, "language": lang,
                "questions": [{"question": q, "intent": i} for q, i in qs]}
