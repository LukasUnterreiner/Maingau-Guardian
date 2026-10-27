"""One customer: Lighty's decision, the options it compared, and "Ask Lighty" (the employee copilot)."""
import streamlit as st

import lighty_api as api
import ui
from i18n import lang, tr

index = ui.load(ui.customer_index)
by_id = {c["customer_id"]: c for c in index}
ids = list(by_id)
current = st.session_state.get("customer_id")
if current not in by_id:
    current = next((c["customer_id"] for c in index if c.get("open_complaint")), ids[0])


def label(cid: str) -> str:
    c = by_id[cid]
    flag = tr(" · open complaint", " · offene Beschwerde") if c.get("open_complaint") else \
        tr(" · service issue", " · Service-Anliegen") if c.get("has_service_issue") else ""
    return f"{cid} · {c.get('city') or tr('unknown city', 'Stadt unbekannt')}{flag}"


head, pick = st.columns([3, 2], vertical_alignment="bottom")
cid = pick.selectbox(tr("Customer", "Kunde"), ids, index=ids.index(current), format_func=label, key="customer-picker")
st.session_state["customer_id"] = cid
c = by_id[cid]
with head:
    ui.page_head(tr("Customers", "Kunden"), cid)

tone = c.get("tonality") or "sie"
facts = [f'<span class="lt-tone{" lt-tone--du" if tone == "du" else ""}"><span class="lt-tone__value">'
         f'{ui.esc(ui.tone(tone))}</span><span class="lt-tone__source">{tr("form of address", "Anrede")}</span></span>']
if c.get("open_complaint"):
    facts.append(f'<span class="lt-pill lt-pill--issue">{tr("Open complaint", "Offene Beschwerde")}</span>')
elif c.get("has_service_issue"):
    facts.append(f'<span class="lt-pill lt-pill--issue">{tr("Service issue", "Service-Anliegen")}</span>')
facts.append(f'<span class="lt-small">{ui.esc(c.get("city"))} · {ui.esc(ui.business_lines(c.get("business_lines")))} · '
             f'{tr("customer since", "Kunde seit")} {ui.esc((c.get("customer_since") or "")[:4])}</span>')
ui.html_block(f'<div class="lt-row" style="gap: 8px; padding-bottom: 30px;">{"".join(facts)}</div>')

rec = ui.load(ui.recommendation, cid)
ui.html_block(ui.risk_card(ui.load(ui.customer, cid), rec, ui.risk_levels(index)))
ui.html_block(ui.hero(rec))
ui.review_buttons(rec, f"customer-{rec['decision_id']}")

left, right = st.columns([3, 2], gap="medium")
left.markdown(ui.options(rec), unsafe_allow_html=True)

# ------------------------------------------------------------------ Ask Lighty
chats = st.session_state.setdefault("chats", {})
chat = chats.setdefault(cid, {"conversation_id": None, "turns": []})


def take_suggestion(key: str) -> None:
    st.session_state["ask"] = st.session_state.get(key)
    st.session_state[key] = None


def ask(question: str) -> None:
    try:
        try:
            resp = api.chat(st.session_state["token"], cid, question, chat["conversation_id"], lang())
        except api.LightyError as exc:
            if exc.status != 409 or not chat["conversation_id"]:
                raise
            chat["conversation_id"] = None   # other customer or turn limit: start a new conversation
            resp = api.chat(st.session_state["token"], cid, question, language=lang())
    except api.LightyError as exc:
        st.session_state["chat-error"] = ui.error_text(exc)
        return
    chat["conversation_id"] = resp.get("conversation_id")
    chat["turns"].append((question, resp))


with right, st.container(key="ask-lighty"):
    st.html(f'<div class="lt-row" style="gap: 8px;"><h2 class="lt-h3">{tr("Ask Lighty", "Lighty fragen")}</h2>'
            '<span class="lt-spacer"></span><span class="lt-caption">'
            f'{tr("internal only · never contacts the customer", "nur intern · kontaktiert nie den Kunden")}</span></div>')
    if not chat["turns"]:
        st.html('<p class="lt-body">' + tr("Ask anything about this customer. Lighty answers from the data, says what is "
                                           "missing, and never changes the decision above.",
                                           "Alles zu diesem Kunden fragen. Lighty antwortet aus den Daten, sagt, was "
                                           "fehlt, und ändert nie die Entscheidung oben.") + '</p>')
    elif banner := ui.sales_banner(chat["turns"][-1][1]):
        ui.html_block(banner)
    for n, (question, resp) in enumerate(chat["turns"]):
        with st.container(key=f"turn-{'next-' if n else ''}{cid}-{n}", gap="medium"):   # "next" turns: line above
            ui.html_block(ui.turn(question, resp))
            ui.suggestion(resp, f"{cid}-{n}")
    if error := st.session_state.pop("chat-error", None):
        st.error(error)

    questions = [q["question"] for q in ui.load(ui.suggested_questions, cid)]
    pills_key = f"pills-{cid}"
    st.pills(tr("Suggested questions", "Vorgeschlagene Fragen"), questions, key=pills_key, label_visibility="collapsed",
             on_change=take_suggestion, args=(pills_key,))
    typed = st.chat_input(tr("Ask about this customer…", "Frage zu diesem Kunden…"), key=f"chat-{cid}", max_chars=2000)
    question = typed or st.session_state.pop("ask", None)
    if question:
        ui.html_block(ui.user_message(question))
        with st.spinner(tr("Lighty is writing…", "Lighty schreibt…")):
            ask(question)
        st.rerun()
