"""Lighty design pieces filled with live API data, plus cached data access for the pages.

Every value that comes from the API is escaped before it goes into HTML: customer and copilot texts are untrusted.
HTML with SVG icons goes through st.markdown (st.html strips SVG); single-line strings keep Markdown out of the way.
"""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

import lighty_api as api

CHANNEL = {"newsletter_email": "Newsletter e-mail", "portal_popup": "Portal pop-up", "app_push": "App push",
           "sms": "SMS", "outbound_call": "Outbound call", "service_email": "Service e-mail",
           "service_call": "Service call", "none": "None"}
STATUS = {"pending_approval": "Pending approval", "approved": "Approved", "rejected": "Rejected",
          "not_required": "No approval needed"}
KIND_CLASS = {"Offer": "offer", "Resolve an issue": "resolve", "Strengthen loyalty": "loyalty",
              "Do not contact": "nocontact"}
DECISION_COLORS = {"Offer": "#004BAD", "Resolve an issue": "#F08C1A", "Strengthen loyalty": "#008153",
                   "Do not contact": "#B5C5DA"}
RULE = {"CONSENT_WITHDRAWN": "Consent withdrawn", "CONSENT_NOT_GIVEN": "No channel consent",
        "CONSENT_UNKNOWN": "Consent unknown", "CONSENT_DOI_MISSING": "No double opt-in",
        "PROFILING_CONSENT_WITHDRAWN": "Profiling consent withdrawn",
        "PROFILING_CONSENT_NOT_GIVEN": "No profiling consent", "PROFILING_CONSENT_UNKNOWN": "Profiling consent unknown",
        "OPEN_COMPLAINT_BLOCKS_MARKETING": "Open complaint", "DUNNING_BLOCKS_MARKETING": "Dunning",
        "CANCELLATION_PENDING_BLOCKS_MARKETING": "Cancellation pending",
        "CONTACT_FREQUENCY_LIMIT": "Contact limit reached", "CONTACT_MIN_GAP": "Contacted too recently",
        "PRODUCT_ALREADY_HELD": "Already held", "PREREQUISITE_MISSING": "Prerequisite missing",
        "CHANNEL_NOT_AVAILABLE": "Channel not available", "ACTION_DISABLED_BY_SETTINGS": "Disabled in settings",
        "NO_SERVICE_ISSUE": "No service issue", "NO_CUSTOMER_REQUEST": "No customer request"}

ICON = {
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
    "trend": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    "lock": '<rect width="16" height="10" x="4" y="11" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "alert": '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "door": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "euro": '<path d="M4 10h12"/><path d="M4 14h9"/><path d="M19 6a7.7 7.7 0 0 0-5.2-2A7.9 7.9 0 0 0 6 12c0 4.4 3.5 8 7.8 8 2 0 3.8-.8 5.2-2"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
}
MAX_BLOCKED = 4   # blocked options shown per customer, highest value first
SPARK = ('<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 '
         '5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 '
         '0 0 1-1.3-1.3Z"/></svg>')


# ------------------------------------------------------------------ formatting
def esc(value) -> str:
    return "" if value is None else html.escape(str(value))


def svg(name: str, width: float = 2) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


def eur(value, *, sign: bool = False, decimals: int = 2) -> str:
    """66.5 -> '€66.50'; sign=True -> '+€66.50'. English number format, as in the design."""
    if value is None:
        return "–"
    prefix = "−" if value < 0 else ("+" if sign and value > 0 else "")
    return f"{prefix}€{abs(value):,.{decimals}f}"


def pct(p) -> str:
    return "–" if p is None else f"{p * 100:.0f}%" if p >= 0.01 or p == 0 else f"{p * 100:.1f}%"


def group(action_type: str | None) -> str:
    return api.DECISION_GROUP.get(action_type or "no_contact", "Do not contact")


def channel_tone(channel: str | None, tonality: str | None = None) -> str:
    label = CHANNEL.get(channel or "none", channel or "")
    return f"{label} · {tonality.capitalize()}" if tonality and channel != "none" else label


def greeting() -> str:
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    part = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
    return f"{now:%A}, {now.day} {now:%B} · {part}"


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def kind_chip(action_type: str | None, text: str | None = None) -> str:
    g = group(action_type)
    return f'<span class="lt-kind lt-kind--{KIND_CLASS[g]}">{esc(text or g)}</span>'


def rule_chips(codes) -> str:
    return "".join(f'<span class="lt-chip lt-chip--rule" title="{esc(c)}">{esc(RULE.get(c, c))}</span>'
                   for c in codes or [])


# ------------------------------------------------------------------ cached data
def _token() -> str:
    return st.session_state["token"]


@st.cache_data(ttl=60, show_spinner="Lighty is evaluating all customers…")
def overview(token: str) -> dict:
    return api.overview(token)


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
def customer(token: str, customer_id: str) -> dict:
    return api.customer(token, customer_id)


@st.cache_data(ttl=60, show_spinner=False)
def recommendation(token: str, customer_id: str) -> dict:
    return api.recommendation(token, customer_id)


@st.cache_data(ttl=600, show_spinner=False)
def suggested_questions(token: str, customer_id: str) -> list[dict]:
    return api.suggested_questions(token, customer_id)


def load(fn, *args):
    """Call a data function; show the backend's error and stop the page if it fails."""
    try:
        return fn(_token(), *args)
    except api.LightyError as exc:
        if exc.status == 401:
            st.session_state.pop("token", None)
            st.warning("Your sign-in is no longer valid. Please sign in again.")
            st.rerun()
        st.error(exc.message)
        st.stop()


# ------------------------------------------------------------------ approve / reject
def review_buttons(rec: dict, key: str, *, open_customer: bool = False) -> None:
    """Approve and Reject for one decision, in one row. 409 explains why it is no longer possible."""
    status = rec.get("approval_status")
    with st.container(horizontal=True, vertical_alignment="center", key=f"actions-{key}"):
        approve = reject = False
        if status == "pending_approval":
            approve = st.button("Approve", type="primary", icon=":material/check:", key=f"approve-{key}")
            reject = st.button("Reject", key=f"reject-{key}")
        elif status == "not_required":
            st.caption("No contact recommended, so there is nothing to approve.")
        else:
            st.caption(f"{STATUS.get(status, status)}. Every contact is still carried out by a person.")
        if open_customer and st.button("Open customer", icon=":material/arrow_forward:", type="tertiary",
                                       key=f"open-{key}"):
            st.session_state["customer_id"] = rec["customer_id"]
            st.switch_page("views/customer.py")
    if approve or reject:
        try:
            api.review(_token(), rec["decision_id"], approve, reviewer=st.session_state["me"]["employee_id"])
        except api.LightyError as exc:
            st.session_state["flash"] = ("error", f"Not saved: {exc.message}")
        else:
            verb = "approved" if approve else "rejected"
            st.session_state["flash"] = ("success", f"Decision for {rec['customer_id']} {verb}.")
        st.cache_data.clear()
        st.rerun()


def show_flash() -> None:
    if flash := st.session_state.pop("flash", None):
        kind, text = flash
        (st.success if kind == "success" else st.error)(text)


# ------------------------------------------------------------------ cards
def kpi_tiles(ov: dict) -> str:
    protected = ov.get("projected_protected_customer_value_eur") or 0
    baseline = (ov.get("baseline") or {}).get("total_expected_dclv_eur") or 0
    trend = f'<span class="lt-trend">↑ {protected / baseline * 100:.0f}%</span>' if baseline > 0 else ""

    def tile(color, icon, label, value, note):
        return (f'<div class="lt-kpi lt-kpi--{color}"><div class="lt-kpi__head"><span class="lt-kpi__icon">{svg(icon)}'
                f'</span>{label}</div><span class="lt-kpi__value">{value}</span><div class="lt-kpi__note">{note}</div></div>')

    return ('<div class="lt-grid" style="--lt-grid-min: 230px;">'
            + tile("blue", "shield", "Protected customer value", esc(eur(protected, decimals=0)),
                   f"{trend}vs. sales-first · Estimate")
            + tile("teal", "trend", "Expected ΔCLV", esc(eur(ov.get("total_projected_incremental_clv_eur"), sign=True, decimals=0)),
                   f"on {esc(eur(ov.get('total_current_clv_eur'), decimals=0))} current CLV")
            + tile("amber", "inbox", "Pending approvals", esc(f"{ov.get('pending_approvals', 0):,}"),
                   "every contact needs a person's yes")
            + tile("orange", "wrench", "Customers with service issues",
                   esc(f"{ov.get('customers_with_active_service_issues', 0):,}"), "resolve first, offers wait")
            + "</div>")


def hero_title(rec: dict) -> str:
    name, channel = rec.get("recommended_action_name"), CHANNEL.get(rec.get("channel"), rec.get("channel"))
    match rec.get("action_type"):
        case "no_contact":
            return "Leave this customer alone today."
        case "service":
            return f"Resolve the open service issue first ({channel}). No offer."
        case "retention":
            return f"Strengthen loyalty with {name} via {channel}."
        case _:
            return f"Offer {name} via {channel}."


def hero(rec: dict) -> str:
    reason, _, restrictions = (rec.get("reason") or "").partition(" Marketing restrictions in force:")
    status = rec.get("approval_status")
    p_label = "Success chance" if rec.get("action_type") == "service" else "Acceptance"

    def stat(label, value):
        return (f'<div class="lt-hero__stat"><span class="lt-hero__stat-label">{label}</span>'
                f'<span class="lt-hero__stat-value">{esc(value)}</span></div>')

    codes = [c.strip(" .") for c in restrictions.split(",") if c.strip(" .")]
    chips = (f'<div class="lt-row" style="gap: 6px;"><span class="lt-hero__fine">Marketing blocked by</span>'
             f'{rule_chips(codes)}</div>') if codes else ""
    return ('<article class="lt-hero"><div class="lt-hero__meta">'
            f'<span class="lt-hero__badge">{SPARK}Lighty recommends</span>{kind_chip(rec.get("action_type"))}'
            f'<span class="lt-spacer"></span><span class="lt-hero__status">{esc(STATUS.get(status, status))}</span></div>'
            f'<h2 class="lt-hero__title">{esc(hero_title(rec))}</h2>'
            f'<p class="lt-hero__reason">{esc(reason)}</p>{chips}'
            '<div class="lt-hero__stats">'
            + stat("Expected ΔCLV", eur(rec.get("expected_dclv_eur"), sign=True))
            + stat(p_label, pct(rec.get("acceptance_probability")))
            + stat("CLV after", eur(rec.get("estimated_clv_after_eur")))
            + stat("Channel", channel_tone(rec.get("channel"), rec.get("tonality")))
            + '</div><div class="lt-hero__actions"><span class="lt-hero__fine">'
            f'{esc(rec.get("customer_id"))} · {esc(rec.get("decision_id"))} · Estimate, not proven uplift</span></div>'
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
        caption = "baseline" if is_baseline else f"{group(o.get('action_type'))} · {pct(o.get('acceptance_probability'))}"
        width = f"{max(abs(value) / scale * 100, 2 if value else 0):.0f}%"
        color = DECISION_COLORS[group(o.get("action_type"))]
        if state == "blocked":
            out.append(f'<div class="lt-option"><span class="lt-rank">{svg("lock", 2.2)}</span>'
                       f'<div class="lt-stack" style="gap: 6px;"><div style="font-weight: 700; color: var(--lt-ink-2);">'
                       f'{esc(o.get("product_name"))}</div><div class="lt-row" style="gap: 4px;">'
                       f'{rule_chips(o.get("exclusion_reasons"))}</div></div>'
                       f'<span class="lt-caption">{esc(CHANNEL.get(o.get("channel"), o.get("channel")))}</span>'
                       '<div class="lt-bar lt-bar--blocked"><span></span></div>'
                       f'<span class="lt-num lt-delta--void">{esc(eur(value, sign=True))}</span></div>')
            continue
        delta_class = "lt-delta--gain" if value > 0 else "lt-delta--loss" if value < 0 else ""
        delta_style = "" if delta_class else ' style="font-weight: 700; color: var(--lt-ink-2);"'
        out.append(f'<div class="lt-option{" lt-option--top" if state == "top" else ""}"><span class="lt-rank">{rank}</span>'
                   f'<div><div style="font-weight: 700;">{esc(o.get("product_name"))}</div>'
                   f'<div class="lt-caption">{esc(caption)}</div></div>'
                   f'<span class="lt-small">{esc(CHANNEL.get(o.get("channel"), o.get("channel")))}</span>'
                   f'<div class="lt-bar" style="--value: {width}; --lt-bar-color: {color};'
                   f'{" background: #FFFFFF;" if state == "top" else ""}"><span></span></div>'
                   f'<span class="lt-num {delta_class}"{delta_style}>{esc(eur(value, sign=True))}</span></div>')
    more = len(blocked) - MAX_BLOCKED
    footer = f'<span class="lt-caption">+{more} more blocked options with lower value</span>' if more > 0 else ""
    return ('<section class="lt-card"><div class="lt-card__header"><h2 class="lt-h3">Options Lighty compared</h2>'
            '<span class="lt-caption">blocked options stay visible</span></div>'
            f'<div class="lt-options">{"".join(out)}</div>{footer}</section>')


# ------------------------------------------------------------------ Ask Lighty
def user_message(text: str) -> str:
    return f'<div class="lt-msg-user" lang="de">{esc(text)}</div>'


def _fact_label(fact: dict) -> str:
    key = fact.get("key") or ""
    name, _, ident = key.partition(":")
    label = {"open_ticket": "Ticket", "contract": "Contract", "order": "Order", "consent": "Consent",
             "product_status": "Product", "nba": "Next Best Action", "clv": "CLV", "churn": "Churn"}.get(name)
    return f"{label} {ident}".strip() if label else key.replace("_", " ").replace(":", " ").capitalize()


def lighty_answer(resp: dict) -> str:
    """One copilot answer: banners, origin chip, the answer lines, fact chips and confidence."""
    origin = resp.get("answer_origin") or {}
    chip = ('<span class="lt-origin lt-origin--ai">AI-phrased · checked</span>' if origin.get("llm_used")
            else '<span class="lt-origin">Rule-based</span>')
    banners = "".join(f'<div class="lt-banner lt-banner--attention">{svg("alert")}{esc(w.get("message"))}</div>'
                      for w in resp.get("warnings", []) if w.get("code") == "sales_restricted")
    items, paragraphs = [], []
    for line in (resp.get("response") or "").splitlines():
        if line.startswith("- "):
            items.append(f"<li>{esc(line[2:])}</li>")
        elif line.strip():
            paragraphs.append(f"<p style='margin: 0;'>{esc(line)}</p>")
    body = "".join(paragraphs) + (f'<ul lang="de">{"".join(items)}</ul>' if items else "")

    facts = {f["fact_id"]: f for f in resp.get("supporting_facts", [])}
    parts = resp.get("answer_parts") or {}
    chips = []
    for ids, cls in (("verified_fact_ids", "fact"), ("engine_computed_fact_ids", "calc"), ("data_gap_fact_ids", "gap")):
        for fid in parts.get(ids, []):
            if fid in facts:
                chips.append(f'<span class="lt-chip lt-chip--{cls}" title="{esc(facts[fid].get("text"))}">'
                             f'{esc(_fact_label(facts[fid]))}</span>')
    conf = resp.get("confidence_or_uncertainty") or {}
    level = conf.get("level")
    confidence = (f'<div class="lt-row" style="gap: 8px;"><span class="lt-label">Confidence</span>'
                  f'<span class="lt-confidence lt-confidence--{esc(level)}" aria-hidden="true"><span></span><span></span>'
                  f'<span></span></span><span class="lt-small">{esc(level.capitalize())}</span></div>') if level else ""
    other = [w for w in resp.get("warnings", []) if w.get("code") != "sales_restricted"]
    notes = "".join(f'<div class="lt-caption">{esc(w.get("message"))}</div>' for w in other)
    return (f'{banners}<div class="lt-msg-lighty"><div class="lt-row" style="gap: 8px;"><strong>Lighty</strong>{chip}</div>'
            f'{body}</div>'
            + (f'<div class="lt-row" style="gap: 6px;">{"".join(chips)}</div>' if chips else "")
            + confidence + notes)


def suggestion(resp: dict, key: str) -> None:
    """The German wording box: copy only, never send. st.code gives the copy button."""
    msg = resp.get("suggested_customer_message")
    if not msg or not msg.get("text"):
        return
    label = "Suggested opening" if msg.get("kind") == "call_opening" else "Suggested draft"
    with st.container(key=f"suggestion-{key}"):
        st.html(f'<span class="lt-suggestion__label">{label} · review before use</span>')
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


def risk_tiles(at_risk: list[dict], index: list[dict], levels: dict) -> str:
    cancelled = [c for c in index if c.get("cancellation_pending")]
    lost = sum(c.get("clv_service_impact_reported_eur") or 0 for c in index)

    def tile(color, icon, label, value, note):
        return (f'<div class="lt-kpi lt-kpi--{color}"><div class="lt-kpi__head"><span class="lt-kpi__icon">{svg(icon)}'
                f'</span>{label}</div><span class="lt-kpi__value">{value}</span><div class="lt-kpi__note">{note}</div></div>')

    return ('<div class="lt-grid" style="--lt-grid-min: 230px;">'
            + tile("orange", "users", "Likely to cancel", esc(f"{len(at_risk):,}"),
                   f"customers with ≥ {esc(pct(levels['high']))} churn risk in 12 months")
            + tile("amber", "euro", "Customer value at stake",
                   esc(eur(sum(c.get("current_clv_eur") or 0 for c in at_risk), decimals=0)),
                   "lost if they cancel (their CLV) · Estimate")
            + tile("blue", "wrench", "Already lost to service problems", esc(eur(lost, decimals=0)),
                   "CLV reduced by service cases, all customers · from the data")
            + tile("teal", "door", "Cancellations received", esc(f"{len(cancelled):,}"),
                   "contract cancelled, churn risk 95%")
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

    base = c360.get("structural_churn") or 0
    drivers = c360.get("churn_drivers") or []
    if cancelled:
        segments = [("Cancellation received", churn, "var(--lt-loss)")]
    else:
        segments = [("Base risk of the contracts", max(base, 0), "var(--lt-line-strong)")] + [
            (d.get("label"), d.get("increment") or 0,
             "var(--lt-resolve)" if d.get("category") == "service" else "var(--lt-primary)")
            for d in drivers if (d.get("increment") or 0) > 0]
    bar = "".join(f'<span title="{esc(lbl)}: {esc(pct(inc))}" style="display: block; height: 100%; '
                  f'width: {inc * 100:.1f}%; background: {col};"></span>' for lbl, inc, col in segments)
    reasons = "".join(
        f'<div class="lt-row" style="gap: 8px;"><span class="lt-swatch" style="--lt-swatch: {col};"></span>'
        f'<span class="lt-small" style="flex: 1;">{esc(lbl)}</span>'
        f'<span class="lt-small" style="font-weight: 700;">{"+" if i else ""}{esc(f"{inc * 100:.0f}")} pp</span></div>'
        for i, (lbl, inc, col) in enumerate(segments))
    reasons += "".join(f'<div class="lt-caption">{esc(d.get("label"))}: {esc(f"{(d.get("increment") or 0) * 100:.0f}")} pp '
                       '(lowers the risk)</div>' for d in drivers if (d.get("increment") or 0) < 0)

    after, gain = rec.get("churn_after_accept"), rec.get("expected_dclv_eur") or 0
    if rec.get("action_type") == "no_contact":
        action = ("No permitted action is worth more than leaving this customer alone today.", "")
    else:
        action = (f"{esc(rec.get('recommended_action_name'))}: churn risk {esc(pct(churn))} → {esc(pct(after))} if it "
                  f"succeeds.", f"{esc(eur(gain, sign=True))} expected customer value")

    def money(label, amount, note, tone=""):
        return (f'<div class="lt-hero__stat" style="background: var(--lt-sunken); border: 1px solid var(--lt-line);">'
                f'<span class="lt-label">{label}</span><span class="lt-metric" style="{tone}">{amount}</span>'
                f'<span class="lt-caption">{note}</span></div>')

    return (
        '<section class="lt-card lt-card--shadow" style="border-radius: var(--lt-radius-xl);">'
        '<div class="lt-card__header"><h2 class="lt-h3">Will this customer cancel?</h2>'
        '<span class="lt-tag lt-tag--estimate">Estimate · churn model of the data</span></div>'
        '<div class="lt-grid" style="--lt-grid-min: 300px; gap: 24px; align-items: start;">'
        '<div class="lt-stack" style="gap: 10px;">'
        f'<div class="lt-row" style="gap: 10px; align-items: baseline;"><span class="lt-metric--xl" style="color: {color};">'
        f'{esc(pct(churn))}</span><span class="lt-body">chance to cancel within 12 months</span></div>'
        f'<div class="lt-row" style="gap: 8px;"><span class="lt-pill" style="font-weight: 700; color: {color};">{level} risk'
        f'</span><span class="lt-caption">higher than {esc(pct(share_below(churn, levels)))} of all customers</span></div>'
        f'<div class="lt-bar lt-bar--thick" style="display: flex;">{bar}</div>'
        f'<div class="lt-stack" style="gap: 6px;"><span class="lt-label">Why</span>{reasons}</div></div>'
        '<div class="lt-stack" style="gap: 10px;">'
        '<div class="lt-grid" style="--lt-grid-min: 150px; gap: 8px;">'
        + money("At stake if they cancel", esc(eur(clv)), "customer value (CLV, 10 years) · Estimate")
        + money("Lost to service problems", esc(eur(impact)) if impact else "€0",
                "CLV reduced by service cases · from the data", "color: var(--lt-loss);" if impact else "")
        + '</div>'
        f'<div class="lt-banner lt-banner--info">{svg("info")}<span>{action[0]}'
        f'{" <strong>" + action[1] + "</strong>" if action[1] else ""}</span></div>'
        '</div></div></section>')
