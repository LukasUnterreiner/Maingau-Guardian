"""Lighty design pieces filled with live API data, plus cached data access for the pages.

Every value that comes from the API is escaped before it goes into HTML: customer and copilot texts are untrusted.
HTML with SVG icons goes through st.markdown (st.html strips SVG); single-line strings keep Markdown out of the way.
"""
from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

import lighty_api as api
from i18n import lang, switch_page, tr

# codes from the API in words: (English, German)
CHANNEL = {"newsletter_email": ("Newsletter e-mail", "Newsletter-E-Mail"),
           "portal_popup": ("Portal pop-up", "Portal-Pop-up"), "app_push": ("App push", "App-Push"), "sms": ("SMS", "SMS"),
           "outbound_call": ("Outbound call", "Anruf"),
           "service_email": ("Service e-mail", "Service-E-Mail"), "service_call": ("Service call", "Service-Anruf"),
           "none": ("None", "Keiner")}
STATUS = {"pending_approval": ("Pending approval", "Wartet auf Freigabe"), "approved": ("Approved", "Freigegeben"),
          "rejected": ("Rejected", "Abgelehnt"), "not_required": ("No approval needed", "Keine Freigabe nötig")}
# the four decision groups keep their English names as keys (see lighty_api.DECISION_GROUP)
GROUP = {"Offer": ("Offer", "Angebot"), "Resolve an issue": ("Resolve an issue", "Anliegen lösen"),
         "Strengthen loyalty": ("Strengthen loyalty", "Bindung stärken"),
         "Do not contact": ("Do not contact", "Nicht kontaktieren")}
KIND_CLASS = {"Offer": "offer", "Resolve an issue": "resolve", "Strengthen loyalty": "loyalty",
              "Do not contact": "nocontact"}
DECISION_COLORS = {"Offer": "#004BAD", "Resolve an issue": "#F08C1A", "Strengthen loyalty": "#008153",
                   "Do not contact": "#B5C5DA"}
RULE = {"CONSENT_WITHDRAWN": ("Consent withdrawn", "Einwilligung widerrufen"),
        "CONSENT_NOT_GIVEN": ("No channel consent", "Keine Kanal-Einwilligung"),
        "CONSENT_UNKNOWN": ("Consent unknown", "Einwilligung unbekannt"),
        "CONSENT_DOI_MISSING": ("No double opt-in", "Kein Double-Opt-in"),
        "PROFILING_CONSENT_WITHDRAWN": ("Profiling consent withdrawn", "Profiling-Einwilligung widerrufen"),
        "PROFILING_CONSENT_NOT_GIVEN": ("No profiling consent", "Keine Profiling-Einwilligung"),
        "PROFILING_CONSENT_UNKNOWN": ("Profiling consent unknown", "Profiling-Einwilligung unbekannt"),
        "OPEN_COMPLAINT_BLOCKS_MARKETING": ("Open complaint", "Offene Beschwerde"),
        "DUNNING_BLOCKS_MARKETING": ("Dunning", "Mahnung"),
        "CANCELLATION_PENDING_BLOCKS_MARKETING": ("Cancellation pending", "Kündigung liegt vor"),
        "CONTACT_FREQUENCY_LIMIT": ("Contact limit reached", "Kontaktlimit erreicht"),
        "CONTACT_MIN_GAP": ("Contacted too recently", "Letzter Kontakt zu kurz her"),
        "PRODUCT_ALREADY_HELD": ("Already held", "Bereits vorhanden"),
        "PREREQUISITE_MISSING": ("Prerequisite missing", "Voraussetzung fehlt"),
        "CHANNEL_NOT_AVAILABLE": ("Channel not available", "Kanal nicht verfügbar"),
        "ACTION_DISABLED_BY_SETTINGS": ("Disabled in settings", "In den Einstellungen deaktiviert"),
        "NO_SERVICE_ISSUE": ("No service issue", "Kein Service-Anliegen"),
        "NO_CUSTOMER_REQUEST": ("No customer request", "Keine Kundenanfrage")}
# churn drivers arrive as English labels (app/services/churn_model.py DRIVER_DEFS)
DRIVER_DE = {"Price guarantee ends within 90 days": "Preisgarantie endet in 90 Tagen",
             "Open complaint": "Offene Beschwerde",
             "Two or more tickets in 12 months": "Zwei oder mehr Tickets in 12 Monaten",
             "Last CSAT rating 1 or 2": "Letzte Bewertung 1 oder 2",
             "Dunning level 2 or higher": "Mahnstufe 2 oder höher",
             "Three or more failed charging sessions in 30 days": "Drei oder mehr fehlgeschlagene Ladevorgänge in 30 Tagen",
             "HEMS user (churns less)": "HEMS-Nutzer (kündigt seltener)"}
LINE = {"energy": ("Energy", "Energie"), "mobile": ("Mobile", "Mobilfunk"), "internet": ("Internet", "Internet"),
        "e_mobility": ("E-mobility", "E-Mobilität"), "smart_living": ("Smart living", "Smart Living"),
        "shop": ("Shop", "Shop")}
# English has no Sie and Du, so the English app says how formal the address is
TONE = {"sie": ("Formal", "Sie"), "du": ("Informal", "Du")}
RISK = {"High": ("High", "Hoch"), "Medium": ("Medium", "Mittel"), "Low": ("Low", "Niedrig")}
RISK_LABEL = {"High": ("High risk", "Hohes Risiko"), "Medium": ("Medium risk", "Mittleres Risiko"),
              "Low": ("Low risk", "Niedriges Risiko")}
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
             "Dezember"]

ICON = {
    "up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
    "trend": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    "lock": '<rect width="16" height="10" x="4" y="11" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "alert": '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "door": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "euro": '<path d="M4 10h12"/><path d="M4 14h9"/><path d="M19 6a7.7 7.7 0 0 0-5.2-2A7.9 7.9 0 0 0 6 12c0 4.4 3.5 8 7.8 8 2 0 3.8-.8 5.2-2"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
}
MAX_BLOCKED = 4   # blocked options shown per customer, highest value first
# the Lighty bulb as a data URI, for <img> tags inside st.html / st.markdown
BULB = "data:image/svg+xml;base64," + base64.b64encode(
    (Path(__file__).resolve().parent / "static" / "lighty-bulb.svg").read_bytes()).decode()
SPARK = ('<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 '
         '5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 '
         '0 0 1-1.3-1.3Z"/></svg>')


# ------------------------------------------------------------------ words for codes
def _say(table: dict, key, fallback=None) -> str:
    if key not in table:
        return str(fallback if fallback is not None else key or "")
    en, de = table[key]
    return de if lang() == "de" else en


def channel(code: str | None) -> str:
    return _say(CHANNEL, code or "none")


def status(code: str | None) -> str:
    return _say(STATUS, code)


def group_name(name: str) -> str:
    return _say(GROUP, name)


def rule(code: str) -> str:
    return _say(RULE, code)


def driver(label: str | None) -> str:
    return DRIVER_DE.get(label, label or "") if lang() == "de" else label or ""


def business_lines(codes) -> str:
    return ", ".join(_say(LINE, c, str(c).replace("_", " ").capitalize()) for c in codes or [])


def tone(tonality: str | None) -> str:
    return _say(TONE, tonality or "sie", (tonality or "").capitalize())


def action_name(rec: dict) -> str:
    """The product name from the data; the backend's "No contact" in the app language."""
    if rec.get("action_type") == "no_contact":
        return tr("No contact", "Kein Kontakt")
    return rec.get("recommended_action_name") or rec.get("product_name") or ""


def risk_name(level: str) -> str:
    return _say(RISK, level)


def risk_label(level: str) -> str:
    return _say(RISK_LABEL, level)


# ------------------------------------------------------------------ formatting
def esc(value) -> str:
    return "" if value is None else html.escape(str(value))


def svg(name: str, width: float = 2) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


def _german(text: str) -> str:
    """'1,234.5' -> '1.234,5' when the app is German."""
    return text.translate(str.maketrans(",.", ".,")) if lang() == "de" else text


def num(value, decimals: int = 0) -> str:
    return _german(f"{value:,.{decimals}f}")


def eur(value, *, sign: bool = False, decimals: int = 2) -> str:
    """66.5 -> '€66.50' in English, '66,50 €' in German; sign=True -> '+€66.50' / '+66,50 €'."""
    if value is None:
        return "–"
    prefix = "−" if value < 0 else ("+" if sign and value > 0 else "")
    amount = num(abs(value), decimals)
    return f"{prefix}{amount} €" if lang() == "de" else f"{prefix}€{amount}"


def pct(p) -> str:
    """0.24 -> '24%' in English, '24 %' in German."""
    if p is None:
        return "–"
    text = num(p * 100, 0 if p >= 0.01 or p == 0 else 1)
    return f"{text} %" if lang() == "de" else f"{text}%"


def group(action_type: str | None) -> str:
    return api.DECISION_GROUP.get(action_type or "no_contact", "Do not contact")


def channel_tone(code: str | None, tonality: str | None = None) -> str:
    label = channel(code)
    return f"{label} · {tone(tonality)}" if tonality and code != "none" else label


def greeting() -> str:
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    if lang() == "de":
        part = "Guten Morgen" if now.hour < 12 else "Guten Tag" if now.hour < 18 else "Guten Abend"
        return f"{WEEKDAYS_DE[now.weekday()]}, {now.day}. {MONTHS_DE[now.month - 1]} · {part}"
    part = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
    return f"{now:%A}, {now.day} {now:%B} · {part}"


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def kind_chip(action_type: str | None, text: str | None = None) -> str:
    g = group(action_type)
    return f'<span class="lt-kind lt-kind--{KIND_CLASS[g]}">{esc(text or group_name(g))}</span>'


def rule_chips(codes) -> str:
    return "".join(f'<span class="lt-chip lt-chip--rule" title="{esc(c)}">{esc(rule(c))}</span>'
                   for c in codes or [])


# ------------------------------------------------------------------ cached data
def _token() -> str:
    return st.session_state["token"]


@st.cache_data(ttl=60, show_spinner=False)
def _overview(token: str) -> dict:
    return api.overview(token)


def overview(token: str) -> dict:
    with st.spinner(tr("Lighty is evaluating all customers…", "Lighty bewertet alle Kunden…")):
        return _overview(token)


@st.cache_data(ttl=60, show_spinner=False)
def decisions(token: str, approval_status: str | None) -> list[dict]:
    first = api.decisions(token, approval_status=approval_status, page_size=500)
    items = list(first["items"])
    for page in range(2, first.get("total_pages", 1) + 1):
        items += api.decisions(token, approval_status=approval_status, page=page, page_size=500)["items"]
    return items


@st.cache_data(ttl=600, show_spinner=False)
def customer_index(token: str) -> list[dict]:
    first = api.customers(token, page_size=200)
    items = list(first["items"])
    for page in range(2, first.get("total_pages", 1) + 1):
        items += api.customers(token, page=page, page_size=200)["items"]
    return items


@st.cache_data(ttl=60, show_spinner=False)
def regions(token: str, level: str) -> dict:
    return api.regions(token, level=level)


@st.cache_data(ttl=60, show_spinner=False)
def customer(token: str, customer_id: str) -> dict:
    return api.customer(token, customer_id)


@st.cache_data(ttl=60, show_spinner=False)
def _recommendation(token: str, customer_id: str, language: str) -> dict:
    return api.recommendation(token, customer_id, language)


def recommendation(token: str, customer_id: str) -> dict:
    """Lighty's decision; its reason comes in the app language."""
    return _recommendation(token, customer_id, lang())


@st.cache_data(ttl=600, show_spinner=False)
def _suggested_questions(token: str, customer_id: str, language: str) -> list[dict]:
    return api.suggested_questions(token, customer_id, language)


def suggested_questions(token: str, customer_id: str) -> list[dict]:
    return _suggested_questions(token, customer_id, lang())


def load(fn, *args):
    """Call a data function; show the backend's error and stop the page if it fails."""
    try:
        return fn(_token(), *args)
    except api.LightyError as exc:
        if exc.status == 401:
            st.session_state.pop("token", None)
            st.warning(tr("Your sign-in is no longer valid. Please sign in again.",
                          "Die Anmeldung ist nicht mehr gültig. Bitte erneut anmelden."))
            st.rerun()
        st.error(error_text(exc))
        st.stop()


def error_text(exc: api.LightyError) -> str:
    if exc.status == 0:
        return tr(exc.message, "Lighty ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen.")
    return exc.message


# ------------------------------------------------------------------ approve / reject
def review_buttons(rec: dict, key: str, *, open_customer: bool = False) -> None:
    """Approve and Reject for one decision, in one row. 409 explains why it is no longer possible."""
    state = rec.get("approval_status")
    with st.container(horizontal=True, vertical_alignment="center", key=f"actions-{key}"):
        approve = reject = False
        if state == "pending_approval":
            approve = st.button(tr("Approve", "Freigeben"), type="primary", icon=":material/check:", key=f"approve-{key}")
            reject = st.button(tr("Reject", "Ablehnen"), key=f"reject-{key}")
        elif state == "not_required":
            st.caption(tr("No contact recommended, so there is nothing to approve.",
                          "Kein Kontakt empfohlen, daher gibt es nichts freizugeben."))
        else:
            st.caption(tr(f"{status(state)}. Every contact is still carried out by a person.",
                          f"{status(state)}. Jeder Kontakt wird weiterhin von einem Menschen durchgeführt."))
        if open_customer and st.button(tr("Open customer", "Kunde öffnen"), icon=":material/arrow_forward:",
                                       type="tertiary", key=f"open-{key}"):
            st.session_state["customer_id"] = rec["customer_id"]
            switch_page("views/customer.py")
    if approve or reject:
        save_review(rec, approve)


def save_review(rec: dict, approve: bool) -> None:
    try:
        api.review(_token(), rec["decision_id"], approve, reviewer=st.session_state["me"]["employee_id"])
    except api.LightyError as exc:
        st.session_state["flash"] = ("error", tr("Not saved: ", "Nicht gespeichert: ") + error_text(exc))
    else:
        verb = tr("approved", "freigegeben") if approve else tr("rejected", "abgelehnt")
        st.session_state["flash"] = ("success", tr(f"Decision for {rec['customer_id']} {verb}.",
                                                   f"Entscheidung für {rec['customer_id']} {verb}."))
    st.cache_data.clear()
    st.rerun()


def show_flash() -> None:
    if flash := st.session_state.pop("flash", None):
        kind, text = flash
        (st.success if kind == "success" else st.error)(text)


# ------------------------------------------------------------------ page parts (soft-card layout)
def page_head(eyebrow: str, title: str, subtitle: str = "") -> None:
    html_block(f'<div class="lt-pagehead"><span class="lt-eyebrow">{esc(eyebrow)}</span>'
               f'<h1 class="lt-title">{esc(title)}</h1>'
               + (f'<p class="lt-subtitle">{esc(subtitle)}</p>' if subtitle else "") + '</div>')


def minibars(values: list[float], color: str, title: str) -> str:
    """Small bar chart in a tile. Real numbers only, scaled to the largest; the tooltip says what they are."""
    top = max([v for v in values if v > 0] + [1e-9])
    return (f'<div class="lt-minibars" title="{esc(title)}" aria-hidden="true">'
            + "".join(f'<span class="lt-minibar"><span style="height: {max(v / top * 100, 8) if v > 0 else 0:.0f}%; '
                      f'background: {color};"></span></span>' for v in values) + '</div>')


def tile(icon: str, label: str, value: str, note: str, color: str, bars: str = "") -> str:
    return (f'<div class="lt-tile"><div class="lt-tile__head"><span class="lt-tile__icon" style="color: {color};">'
            f'{svg(icon)}</span><span>{label}</span></div>'
            f'<span class="lt-tile__value">{value}</span>{bars}'
            f'<span class="lt-tile__note">{note}</span></div>')


def tiles(*parts: str) -> None:
    html_block(f'<div class="lt-tiles">{"".join(parts)}</div>')


def churn_histogram(index: list[dict]) -> list[float]:
    """Customers per 10-point churn band: 0–9 %, 10–19 %, …, 60 % and more."""
    bins = [0.0] * 7
    for c in index:
        bins[min(int((c.get("churn_probability") or 0) * 10), 6)] += 1
    return bins


def section(title: str, count: int | None, dot: str, key: str, button: str | None = None) -> bool:
    """A section title with a coloured dot and a count, and an optional "View all" button on the right."""
    with st.container(horizontal=True, vertical_alignment="center", key=f"sec-{key}"):
        st.html(f'<div class="lt-section"><span class="lt-section__dot" style="background: {dot};"></span>'
                f'<h2 class="lt-section__title">{esc(title)}</h2>'
                + (f'<span class="lt-section__count">{num(count)}</span>' if count is not None else "") + '</div>')
        if button:
            st.space("stretch")
            return st.button(button, key=f"sec-btn-{key}", icon=":material/arrow_forward:", icon_position="right")
    return False


RISK_COLOR = {"High": "var(--lt-loss)", "Medium": "var(--lt-resolve)", "Low": "var(--lt-gain)"}
RISK_TINT = {"High": "var(--lt-loss-tint)", "Medium": "var(--lt-resolve-tint)", "Low": "var(--lt-gain-tint)"}


def customer_card(c: dict, rec: dict, levels: dict, key: str) -> None:
    """One customer as a card: who, churn risk, value at stake, Lighty's next step, and approve / reject."""
    churn = c.get("churn_probability") or 0
    level = risk_level(churn, levels)
    color = RISK_COLOR[level]
    cancelled = tr("Cancellation received", "Kündigung liegt vor")
    badge = (cancelled, "var(--lt-loss)") if c.get("cancellation_pending") else (risk_label(level), color)
    filled = max(1, round(churn * 10))
    segments = '<span class="on"></span>' * filled + "<span></span>" * (10 - filled)
    why = cancelled if c.get("cancellation_pending") else \
        ", ".join(driver(d) for d in c.get("churn_drivers") or []) or tr("Base risk of the contracts",
                                                                        "Grundrisiko der Verträge")
    gain = rec.get("expected_dclv_eur") or 0
    if rec.get("action_type") == "no_contact":
        step = f'<strong>{tr("Leave alone today", "Heute in Ruhe lassen")}</strong>'
    else:
        step = (f'<strong>{esc(channel(rec.get("channel")))}</strong>'
                f'{kind_chip(rec.get("action_type"), rec.get("recommended_action_name"))}')
    with st.container(key=f"ccard-{key}"):
        html_block(
            '<div class="lt-ccard">'
            '<div class="lt-ccard__head">'
            f'<div class="lt-avatar" style="--av: {RISK_TINT[level]}; --av-ink: {color};">{svg("user")}'
            f'<span class="lt-avatar__badge">{esc(tone(c.get("tonality")))}</span></div>'
            f'<div class="lt-ccard__who"><span class="lt-ccard__name">{esc(c["customer_id"])}</span>'
            f'<span class="lt-caption">{esc(c.get("city"))} · {esc(business_lines(c.get("business_lines")))}</span></div>'
            f'<span class="lt-status" style="--dot: {badge[1]};">{esc(badge[0])}</span></div>'
            '<div class="lt-ccard__risk">'
            f'<div class="lt-row"><span class="lt-caption">{tr("Churn risk · 12 months", "Kündigungsrisiko · 12 Monate")}'
            f'</span><span class="lt-spacer"></span><span class="lt-caption">{tr("At stake", "Gefährdet")} '
            f'<strong class="lt-ccard__num">{esc(eur(c.get("current_clv_eur"), decimals=0))}</strong></span></div>'
            f'<div class="lt-segbar" style="--seg: {color};" title="{esc(pct(churn))}">{segments}</div>'
            f'<div class="lt-row" style="gap: 8px;"><strong class="lt-ccard__num">{esc(pct(churn))}</strong>'
            f'<span class="lt-caption lt-ccard__why">{esc(why)}</span></div></div>'
            # the value sits on the caption line, so a long chip never pushes it onto a line of its own
            f'<div class="lt-ccard__task"><div class="lt-row" style="gap: 8px;"><span class="lt-caption">'
            f'{tr("Lighty recommends", "Lighty empfiehlt")}</span><span class="lt-spacer"></span>'
            + (f'<span class="lt-delta--gain">{esc(eur(gain, sign=True))}</span>' if gain > 0 else "")
            + f'</div><div class="lt-row" style="gap: 8px;">{step}</div></div></div>')
        # small gap: the German "Ablehnen" and "Freigeben" still fit on one line
        with st.container(horizontal=True, vertical_alignment="center", gap="xsmall", key=f"cact-{key}"):
            if st.button("Details", type="tertiary", key=f"open-{key}"):
                st.session_state["customer_id"] = c["customer_id"]
                switch_page("views/customer.py")
            st.space("stretch")
            if rec.get("approval_status") == "pending_approval":
                if st.button(tr("Reject", "Ablehnen"), key=f"reject-{key}"):
                    save_review(rec, False)
                if st.button(tr("Approve", "Freigeben"), type="primary", icon=":material/check:", key=f"approve-{key}"):
                    save_review(rec, True)
            else:
                st.html(f'<span class="lt-caption">{esc(status(rec.get("approval_status")))}</span>')


def _local_time(iso: str | None) -> str:
    if not iso:
        return ""
    when = datetime.fromisoformat(iso).astimezone(ZoneInfo("Europe/Berlin"))
    if when.date() == datetime.now(ZoneInfo("Europe/Berlin")).date():
        return f"{when:%H:%M}"
    return f"{when.day}. {MONTHS_DE[when.month - 1][:3]}." if lang() == "de" else f"{when.day} {when:%b}"


def activity_feed(reviewed: list[dict], limit: int = 7) -> str:
    """The latest approvals and rejections, newest first."""
    rows = sorted(reviewed, key=lambda d: d.get("reviewed_at") or "", reverse=True)[:limit]
    if not rows:
        items = ('<p class="lt-caption" style="margin: 0;">'
                 + tr("No reviews yet. Every decision you approve or reject shows up here.",
                      "Noch keine Prüfungen. Jede freigegebene oder abgelehnte Entscheidung erscheint hier.") + '</p>')
    else:
        items = "".join(
            '<div class="lt-feed__item">'
            f'<span class="lt-feed__dot" style="background: var(--lt-dot-{"approved" if d["approval_status"] == "approved" else "rejected"});"></span>'
            '<div class="lt-feed__text">'
            f'<div><span class="lt-mention">@{esc(d.get("reviewed_by") or tr("unknown", "unbekannt"))}</span> '
            + (tr("approved", "hat freigegeben") if d["approval_status"] == "approved" else tr("rejected", "hat abgelehnt"))
            + '</div>'
            f'<div class="lt-row" style="gap: 6px;">{kind_chip(d.get("action_type"))}'
            f'<span class="lt-tagid">{esc(d["customer_id"])}</span></div></div>'
            f'<span class="lt-caption">{esc(_local_time(d.get("reviewed_at")))}</span></div>'
            for d in rows)
    return ('<section class="lt-softcard"><div class="lt-row" style="gap: 10px; flex-wrap: nowrap;">'
            f'<span class="lt-tile__icon" style="color: var(--lt-primary);">{svg("inbox")}</span>'
            '<div class="lt-stack" style="gap: 0;"><h2 class="lt-section__title" style="font-size: 18px;">'
            f'{tr("Activity", "Aktivität")}</h2><span class="lt-caption">'
            f'{tr("latest approvals and rejections", "letzte Freigaben und Ablehnungen")}</span></div></div>'
            f'<div class="lt-feed">{items}</div></section>')


# ------------------------------------------------------------------ cards
def hero_title(rec: dict) -> str:
    name, via = rec.get("recommended_action_name"), channel(rec.get("channel"))
    match rec.get("action_type"):
        case "no_contact":
            return tr("Leave this customer alone today.", "Diesen Kunden heute in Ruhe lassen.")
        case "service":
            return tr(f"Resolve the open service issue first ({via}). No offer.",
                      f"Zuerst das offene Service-Anliegen lösen ({via}). Kein Angebot.")
        case "retention":
            return tr(f"Strengthen loyalty with {name} via {via}.", f"Bindung stärken mit {name} über {via}.")
        case _:
            return tr(f"Offer {name} via {via}.", f"{name} über {via} anbieten.")


# the reason ends with the marketing blocks as codes; they are shown as chips instead
RESTRICTIONS = (" Marketing restrictions in force:", " Marketing-Sperren aktiv:")


def hero(rec: dict) -> str:
    reason, restrictions = rec.get("reason") or "", ""
    for marker in RESTRICTIONS:
        if marker in reason:
            reason, _, restrictions = reason.partition(marker)
    state = rec.get("approval_status")
    p_label = tr("Success chance", "Erfolgschance") if rec.get("action_type") == "service" else \
        tr("Acceptance", "Annahmechance")

    def stat(label, value):
        return (f'<div class="lt-hero__stat"><span class="lt-hero__stat-label">{label}</span>'
                f'<span class="lt-hero__stat-value">{esc(value)}</span></div>')

    codes = [c.strip(" .") for c in restrictions.split(",") if c.strip(" .")]
    chips = (f'<div class="lt-row" style="gap: 6px;"><span class="lt-hero__fine">'
             f'{tr("Marketing blocked by", "Marketing gesperrt durch")}</span>{rule_chips(codes)}</div>') if codes else ""
    return ('<article class="lt-hero"><div class="lt-hero__meta">'
            f'<span class="lt-hero__badge">{SPARK}{tr("Lighty recommends", "Lighty empfiehlt")}</span>'
            f'{kind_chip(rec.get("action_type"))}'
            f'<span class="lt-spacer"></span><span class="lt-hero__status">{esc(status(state))}</span></div>'
            f'<h2 class="lt-hero__title">{esc(hero_title(rec))}</h2>'
            f'<p class="lt-hero__reason">{esc(reason)}</p>{chips}'
            '<div class="lt-hero__stats">'
            + stat(tr("Expected ΔCLV", "Erwarteter ΔCLV"), eur(rec.get("expected_dclv_eur"), sign=True))
            + stat(p_label, pct(rec.get("acceptance_probability")))
            + stat(tr("CLV after", "CLV danach"), eur(rec.get("estimated_clv_after_eur")))
            + stat(tr("Channel", "Kanal"), channel_tone(rec.get("channel"), rec.get("tonality")))
            + '</div><div class="lt-hero__actions"><span class="lt-hero__fine">'
            f'{esc(rec.get("customer_id"))} · {esc(rec.get("decision_id"))} · '
            f'{tr("Estimate, not proven uplift", "Schätzung, kein nachgewiesener Effekt")}</span></div>'
            '</article>')


def options(rec: dict) -> str:
    """The recommendation, the other executable options and the blocked ones, as ranked rows."""
    top = {"product_name": rec.get("recommended_action_name"), "action_type": rec.get("action_type"),
           "channel": rec.get("channel"), "acceptance_probability": rec.get("acceptance_probability"),
           "expected_dclv_eur": rec.get("expected_dclv_eur")}
    blocked = sorted(rec.get("blocked_actions", []), key=lambda o: -(o.get("expected_dclv_eur") or 0))
    rows = [(top, "top")] + [(o, "ok") for o in rec.get("alternatives", [])] \
        + [(o, "blocked") for o in blocked[:MAX_BLOCKED]]
    scale = max([abs(o.get("expected_dclv_eur") or 0) for o, _ in rows] + [1])
    out = []
    for rank, (o, state) in enumerate(rows, start=1):
        value = o.get("expected_dclv_eur") or 0
        is_baseline = o.get("action_type") == "no_contact"
        caption = tr("baseline", "Vergleichswert") if is_baseline else \
            f"{group_name(group(o.get('action_type')))} · {pct(o.get('acceptance_probability'))}"
        width = f"{max(abs(value) / scale * 100, 2 if value else 0):.0f}%"
        color = DECISION_COLORS[group(o.get("action_type"))]
        if state == "blocked":
            # the rule chips get their own line under the name, so lock, channel, bar and value stay on the name's line
            out.append(f'<div class="lt-option lt-option--blocked"><span class="lt-rank">{svg("lock", 2.2)}</span>'
                       f'<div style="font-weight: 700; color: var(--lt-ink-2);">{esc(action_name(o))}</div>'
                       f'<span class="lt-caption">{esc(channel(o.get("channel")))}</span>'
                       '<div class="lt-bar lt-bar--blocked"><span></span></div>'
                       f'<span class="lt-num lt-delta--void">{esc(eur(value, sign=True))}</span>'
                       f'<div class="lt-option__rules">{rule_chips(o.get("exclusion_reasons"))}</div></div>')
            continue
        delta_class = "lt-delta--gain" if value > 0 else "lt-delta--loss" if value < 0 else ""
        delta_style = "" if delta_class else ' style="font-weight: 700; color: var(--lt-ink-2);"'
        out.append(f'<div class="lt-option{" lt-option--top" if state == "top" else ""}"><span class="lt-rank">{rank}</span>'
                   f'<div><div style="font-weight: 700;">{esc(action_name(o))}</div>'
                   f'<div class="lt-caption">{esc(caption)}</div></div>'
                   f'<span class="lt-small">{esc(channel(o.get("channel")))}</span>'
                   f'<div class="lt-bar" style="--value: {width}; --lt-bar-color: {color};'
                   f'{" background: #FFFFFF;" if state == "top" else ""}"><span></span></div>'
                   f'<span class="lt-num {delta_class}"{delta_style}>{esc(eur(value, sign=True))}</span></div>')
    more = len(blocked) - MAX_BLOCKED
    footer = ('<span class="lt-caption">' + tr(f"+{more} more blocked options with lower value",
                                               f"+{more} weitere gesperrte Optionen mit geringerem Wert")
              + '</span>') if more > 0 else ""
    return (f'<section class="lt-card"><div class="lt-card__header"><h2 class="lt-h3">'
            f'{tr("Options Lighty compared", "Optionen, die Lighty verglichen hat")}</h2>'
            '<span class="lt-caption">' + tr("blocked options stay visible", "gesperrte Optionen bleiben sichtbar")
            + '</span></div>'
            f'<div class="lt-options">{"".join(out)}</div>{footer}</section>')


# ------------------------------------------------------------------ Ask Lighty
def user_message(text: str) -> str:
    return f'<div class="lt-msg-user" lang="{lang()}">{esc(text)}</div>'


# the copilot's fact keys (app/services/customer_context_service.py), as "key" or "key:id"
FACT_LABEL = {"open_ticket": ("Ticket", "Ticket"), "contract": ("Contract", "Vertrag"), "order": ("Order", "Bestellung"),
              "consent": ("Consent", "Einwilligung"), "product_status": ("Product", "Produkt"),
              "nba": ("Next Best Action", "Next Best Action"), "nba_alternatives": ("Alternatives", "Alternativen"),
              "clv": ("CLV", "CLV"), "value": ("Customer value", "Kundenwert"), "churn": ("Churn", "Kündigungsrisiko"),
              "restrictions": ("Restrictions", "Einschränkungen"), "engine_reason": ("Reason", "Begründung"),
              "profile": ("Profile", "Profil"), "communication": ("Communication", "Kommunikation"),
              "contact_frequency": ("Contact frequency", "Kontakthäufigkeit"), "csat": ("CSAT", "Zufriedenheit"),
              "callback_requested": ("Callback requested", "Rückruf gewünscht"),
              "prior_problems": ("Earlier problems", "Frühere Probleme"),
              "goodwill_history": ("Goodwill so far", "Kulanz bisher"), "billing": ("Billing", "Abrechnung"),
              "energy": ("Energy", "Energie"), "e_mobility": ("E-mobility", "E-Mobilität"),
              "autostrom": ("Autostrom", "Autostrom"), "hems_devices": ("HEMS devices", "HEMS-Geräte"),
              "hems_offline": ("HEMS offline", "HEMS offline"), "retention": ("Retention", "Kundenbindung"),
              "interests": ("Interests", "Interessen"), "portal_interest": ("Portal interest", "Interesse im Portal"),
              "newsletter_engagement": ("Newsletter", "Newsletter"),
              "cart_abandoned": ("Cart abandoned", "Warenkorb abgebrochen"),
              "previous_offer": ("Earlier offer", "Früheres Angebot"),
              "agent_feedback": ("Agent feedback", "Service-Feedback"),
              "customer_texts": ("Customer's own words", "Worte des Kunden")}


def _fact_label(fact: dict) -> str:
    key = fact.get("key") or ""
    name, _, ident = key.partition(":")
    label = _say(FACT_LABEL, name) if name in FACT_LABEL else None
    return f"{label} {ident}".strip() if label else key.replace("_", " ").replace(":", " ").capitalize()


# The copilot's technical warnings in plain words; the original text stays in the tooltip.
WARNING_TEXT = {
    "llm_output_rejected": ("Lighty's check did not accept the AI wording, so this is the rule-based answer.",
                            "Lightys Prüfung hat die KI-Formulierung nicht angenommen, daher kommt die regelbasierte "
                            "Antwort."),
    "llm_message_rejected": ("Lighty's check did not accept the AI wording for the customer, so the template is shown.",
                             "Lightys Prüfung hat die KI-Formulierung für den Kunden nicht angenommen, daher kommt die "
                             "Vorlage."),
    "llm_unavailable": ("The AI was not reachable, so this is the rule-based answer.",
                        "Die KI war nicht erreichbar, daher kommt die regelbasierte Antwort."),
}
CONFIDENCE = {"high": ("High", "Hoch"), "medium": ("Medium", "Mittel"), "low": ("Low", "Niedrig")}


def sales_banner(resp: dict) -> str:
    """The yellow "no sales offers" banner; shown once at the top of the chat, not under every answer."""
    return "".join(f'<div class="lt-banner lt-banner--attention">{svg("alert")}{esc(w.get("message"))}</div>'
                   for w in resp.get("warnings", []) if w.get("code") == "sales_restricted")


def lighty_answer(resp: dict) -> str:
    """One copilot answer: origin chip, the answer lines, the facts it is based on and confidence."""
    origin = resp.get("answer_origin") or {}
    chip = (f'<span class="lt-origin lt-origin--ai">{tr("AI-phrased · checked", "KI-formuliert · geprüft")}</span>'
            if origin.get("llm_used") else f'<span class="lt-origin">{tr("Rule-based", "Regelbasiert")}</span>')
    items, paragraphs = [], []
    for line in (resp.get("response") or "").splitlines():
        if line.startswith("- "):
            items.append(f"<li>{esc(line[2:])}</li>")
        elif line.strip():
            paragraphs.append(f"<p style='margin: 0;'>{esc(line)}</p>")
    body = "".join(paragraphs) + (f'<ul lang="{esc(resp.get("language") or lang())}">{"".join(items)}</ul>'
                                  if items else "")

    facts = {f["fact_id"]: f for f in resp.get("supporting_facts", [])}
    parts = resp.get("answer_parts") or {}
    chips = []
    for ids, cls, kind in (("verified_fact_ids", "fact", tr("From the data", "Aus den Daten")),
                           ("engine_computed_fact_ids", "calc", tr("Calculated by Lighty", "Von Lighty berechnet")),
                           ("data_gap_fact_ids", "gap", tr("Missing in the data", "Fehlt in den Daten"))):
        for fid in parts.get(ids, []):
            if fid in facts:
                chips.append(f'<span class="lt-chip lt-chip--{cls}" title="{kind}: {esc(facts[fid].get("text"))}">'
                             f'{esc(_fact_label(facts[fid]))}</span>')
    conf = resp.get("confidence_or_uncertainty") or {}
    level = conf.get("level")
    confidence = (f'<div class="lt-row" style="gap: 8px;"><span class="lt-label">{tr("Confidence", "Sicherheit")}</span>'
                  f'<span class="lt-confidence lt-confidence--{esc(level)}" aria-hidden="true"><span></span><span></span>'
                  f'<span></span></span><span class="lt-small">{esc(_say(CONFIDENCE, level, level.capitalize()))}</span>'
                  '</div>') if level else ""
    other = [w for w in resp.get("warnings", []) if w.get("code") != "sales_restricted"]
    notes = "".join(f'<div class="lt-caption" title="{esc(w.get("message"))}">'
                    f'{esc(_say(WARNING_TEXT, w.get("code"), w.get("message")))}</div>' for w in other)
    out = [f'<div class="lt-msg-lighty"><div class="lt-row" style="gap: 8px;"><span class="lt-answer__mark"><img src="{BULB}" alt=""></span>'
           f'<strong>Lighty</strong>{chip}</div>{body}</div>']
    if chips:
        out.append(f'<div class="lt-stack" style="gap: 6px;"><span class="lt-label">{tr("Based on", "Grundlage")}</span>'
                   f'<div class="lt-row" style="gap: 6px;">{"".join(chips)}</div></div>')
    if confidence or notes:
        out.append(f'<div class="lt-stack" style="gap: 6px;">{confidence}{notes}</div>')
    return f'<div class="lt-answer">{"".join(out)}</div>'


def turn(question: str, resp: dict) -> str:
    """One question and its answer as one block, so the spacing between them is fixed."""
    return f'<div class="lt-turn">{user_message(question)}{lighty_answer(resp)}</div>'


def suggestion(resp: dict, key: str) -> None:
    """The German wording box: copy only, never send. st.code gives the copy button."""
    msg = resp.get("suggested_customer_message")
    if not msg or not msg.get("text"):
        return
    opening = msg.get("kind") == "call_opening"
    label = tr(f'{"Suggested opening" if opening else "Suggested draft"} for the customer, in German · review before use',
               f'{"Vorschlag für den Gesprächseinstieg" if opening else "Entwurf"} für den Kunden · vor Verwendung prüfen')
    with st.container(key=f"suggestion-{key}"):
        st.html(f'<span class="lt-suggestion__label">{label}</span>')
        st.code(msg["text"], language=None, wrap_lines=True)


# ------------------------------------------------------------------ churn risk
def risk_levels(index: list[dict]) -> dict:
    """Portfolio view of churn risk: thresholds from the current churn of all customers (no new model).

    High = the top quarter of customers by churn risk, medium = above the median.
    """
    values = sorted(c.get("churn_probability") or 0 for c in index)
    n = len(values) or 1
    return {"values": values, "high": values[int(0.75 * (n - 1))], "medium": values[int(0.5 * (n - 1))]}


def risk_level(churn: float, levels: dict) -> str:
    return "High" if churn >= levels["high"] else "Medium" if churn >= levels["medium"] else "Low"


def share_below(churn: float, levels: dict) -> float:
    values = levels["values"]
    return sum(1 for v in values if v < churn) / (len(values) or 1)


def churn_bands_title() -> str:
    return tr("All customers by churn risk: 0–9 %, 10–19 %, … 60 % and more",
              "Alle Kunden nach Kündigungsrisiko: 0–9 %, 10–19 %, … 60 % und mehr")


def risk_tiles(at_risk: list[dict], index: list[dict], levels: dict) -> str:
    cancelled = [c for c in index if c.get("cancellation_pending")]
    lost = sum(c.get("clv_service_impact_reported_eur") or 0 for c in index)
    return ('<div class="lt-tiles">'
            + tile("users", tr("Likely to cancel", "Kündigungsgefährdet"), esc(num(len(at_risk))),
                   tr(f"customers with ≥ {esc(pct(levels['high']))} churn risk in 12 months",
                      f"Kunden mit ≥ {esc(pct(levels['high']))} Kündigungsrisiko in 12 Monaten"), "var(--lt-resolve)",
                   minibars(churn_histogram(index), "var(--lt-resolve)", churn_bands_title()))
            + tile("euro", tr("Customer value at stake", "Gefährdeter Kundenwert"),
                   esc(eur(sum(c.get("current_clv_eur") or 0 for c in at_risk), decimals=0)),
                   tr("lost if they cancel (their CLV) · Estimate", "geht bei Kündigung verloren (ihr CLV) · Schätzung"),
                   "var(--lt-loss)")
            + tile("wrench", tr("Already lost to service problems", "Schon durch Serviceprobleme verloren"),
                   esc(eur(lost, decimals=0)),
                   tr("CLV reduced by service cases, all customers · from the data",
                      "CLV-Minderung durch Servicefälle, alle Kunden · aus den Daten"), "var(--lt-primary)")
            + tile("door", tr("Cancellations received", "Eingegangene Kündigungen"), esc(num(len(cancelled))),
                   tr(f"contract cancelled, churn risk {pct(0.95)}", f"Vertrag gekündigt, Kündigungsrisiko {pct(0.95)}"),
                   "var(--lt-brand)")
            + "</div>")


def risk_card(c360: dict, rec: dict, levels: dict) -> str:
    """Churn prediction for one customer: risk, why, and what is at stake in money."""
    value = c360.get("value") or {}
    churn = value.get("churn_probability_now") or 0
    clv = value.get("current_clv_eur")
    impact = value.get("clv_service_impact_reported_eur")
    level = risk_level(churn, levels)
    color = {"High": "var(--lt-loss)", "Medium": "var(--lt-resolve-text)", "Low": "var(--lt-gain)"}[level]
    cancelled = (c360.get("service") or {}).get("cancellation_pending")
    pp = tr("pp", "Pp.")
    below = esc(pct(share_below(churn, levels)))

    base = c360.get("structural_churn") or 0
    drivers = c360.get("churn_drivers") or []
    if cancelled:
        segments = [(tr("Cancellation received", "Kündigung liegt vor"), churn, "var(--lt-loss)")]
    else:
        base_label = tr("Base risk of the contracts", "Grundrisiko der Verträge")
        segments = [(base_label, max(base, 0), "var(--lt-line-strong)")] + [
            (driver(d.get("label")), d.get("increment") or 0,
             "var(--lt-resolve)" if d.get("category") == "service" else "var(--lt-primary)")
            for d in drivers if (d.get("increment") or 0) > 0]
    bar = "".join(f'<span title="{esc(lbl)}: {esc(pct(inc))}" style="display: block; height: 100%; '
                  f'width: {inc * 100:.1f}%; background: {col};"></span>' for lbl, inc, col in segments)
    reasons = "".join(
        f'<div class="lt-row" style="gap: 8px;"><span class="lt-swatch" style="--lt-swatch: {col};"></span>'
        f'<span class="lt-small" style="flex: 1;">{esc(lbl)}</span>'
        f'<span class="lt-small" style="font-weight: 700;">{"+" if i else ""}{esc(num(inc * 100))} {pp}</span></div>'
        for i, (lbl, inc, col) in enumerate(segments))
    reasons += "".join(f'<div class="lt-caption">{esc(driver(d.get("label")))}: {esc(num((d.get("increment") or 0) * 100))} '
                       f'{pp} {tr("(lowers the risk)", "(senkt das Risiko)")}</div>'
                       for d in drivers if (d.get("increment") or 0) < 0)

    after, gain = rec.get("churn_after_accept"), rec.get("expected_dclv_eur") or 0
    if rec.get("action_type") == "no_contact":
        action = (tr("No permitted action is worth more than leaving this customer alone today.",
                     "Keine zulässige Aktion ist heute mehr wert, als diesen Kunden in Ruhe zu lassen."), "")
    else:
        name = esc(rec.get("recommended_action_name"))
        action = (tr(f"{name}: churn risk {esc(pct(churn))} → {esc(pct(after))} if it succeeds.",
                     f"{name}: Kündigungsrisiko {esc(pct(churn))} → {esc(pct(after))}, wenn es gelingt."),
                  tr(f"{esc(eur(gain, sign=True))} expected customer value",
                     f"{esc(eur(gain, sign=True))} erwarteter Kundenwert"))

    def money(label, amount, note, tone=""):
        return (f'<div class="lt-hero__stat" style="background: var(--lt-sunken); border: 1px solid var(--lt-line);">'
                f'<span class="lt-label">{label}</span><span class="lt-metric" style="{tone}">{amount}</span>'
                f'<span class="lt-caption">{note}</span></div>')

    return (
        '<section class="lt-card lt-card--shadow" style="border-radius: var(--lt-radius-xl);">'
        '<div class="lt-card__header"><h2 class="lt-h3">'
        + tr("Will this customer cancel?", "Wird dieser Kunde kündigen?") + '</h2><span class="lt-tag lt-tag--estimate">'
        + tr("Estimate · churn model of the data", "Schätzung · Churn-Modell der Daten") + '</span></div>'
        '<div class="lt-grid" style="--lt-grid-min: 300px; gap: 24px; align-items: start;">'
        '<div class="lt-stack" style="gap: 10px;">'
        f'<div class="lt-row" style="gap: 10px; align-items: baseline;"><span class="lt-metric--xl" style="color: {color};">'
        f'{esc(pct(churn))}</span><span class="lt-body">'
        f'{tr("chance to cancel within 12 months", "Wahrscheinlichkeit einer Kündigung in 12 Monaten")}</span></div>'
        f'<div class="lt-row" style="gap: 8px;"><span class="lt-pill" style="font-weight: 700; color: {color};">'
        f'{risk_label(level)}</span><span class="lt-caption">'
        f'{tr(f"higher than {below} of all customers", f"höher als bei {below} aller Kunden")}</span></div>'
        f'<div class="lt-bar lt-bar--thick" style="display: flex;">{bar}</div>'
        f'<div class="lt-stack" style="gap: 6px;"><span class="lt-label">{tr("Why", "Warum")}</span>{reasons}</div></div>'
        '<div class="lt-stack" style="gap: 10px;">'
        '<div class="lt-grid" style="--lt-grid-min: 150px; gap: 8px;">'
        + money(tr("At stake if they cancel", "Gefährdet bei Kündigung"), esc(eur(clv)),
                tr("customer value (CLV, 10 years) · Estimate", "Kundenwert (CLV, 10 Jahre) · Schätzung"))
        + money(tr("Lost to service problems", "Durch Serviceprobleme verloren"),
                esc(eur(impact)) if impact else esc(eur(0, decimals=0)),
                tr("CLV reduced by service cases · from the data", "CLV-Minderung durch Servicefälle · aus den Daten"),
                "color: var(--lt-loss);" if impact else "")
        + '</div>'
        f'<div class="lt-banner lt-banner--info">{svg("info")}<span>{action[0]}'
        f'{" <strong>" + action[1] + "</strong>" if action[1] else ""}</span></div>'
        '</div></div></section>')
