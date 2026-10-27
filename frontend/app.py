"""Lighty web app: the "Daylight" design from theme/ filled with live data from the Lighty backend.

Run locally (backend on http://localhost:8000):   cd frontend && streamlit run app.py
Settings: LIGHTY_API_URL (backend address), LIGHTY_TOKEN (optional: skip the sign-in, local use only),
LIGHTY_ADMIN_TOKEN (only if the backend sets ADMIN_TOKEN for approve/reject).
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

import lighty_api as api
import theme
import ui
from i18n import language_switch, tr

HERE = Path(__file__).resolve().parent
ROLE = {"service_agent": ("service agent", "Service"), "sales_agent": ("sales agent", "Vertrieb"),
        "marketing": ("marketing", "Marketing"), "admin": ("admin", "Admin")}

st.set_page_config(page_title="Lighty", page_icon=str(HERE / "static" / "lighty-mark.svg"), layout="wide")
theme.apply_theme()
st.markdown(f"<style>{(HERE / 'app.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
st.logo(str(HERE / "static" / "lighty-logo.svg"), size="large", icon_image=str(HERE / "static" / "lighty-mark.svg"))


def sign_in(token: str) -> bool:
    try:
        st.session_state["me"] = api.me(token)
    except api.LightyError as exc:
        st.session_state.pop("me", None)
        st.error(tr("This token is not valid.", "Dieses Token ist nicht gültig.") if exc.status == 401
                 else ui.error_text(exc))
        return False
    st.session_state["token"] = token
    return True


def sign_in_page() -> None:
    try:
        mode = api.health().get("employee_auth", {}).get("mode")
    except api.LightyError as exc:
        st.error(ui.error_text(exc))
        st.stop()
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid, st.container(border=True, key="sign-in"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(f'<img src="{ui.BULB}" alt="Lighty" style="height: 64px; width: auto;">')
            st.space("stretch")
            language_switch()
        st.html('<div class="lt-stack" style="gap: 6px;"><span class="lt-label">Lighty · MAINGAU Energie</span>'
                '<h1 class="lt-h1">Smarter decisions. Better conversations.</h1>'
                '<p class="lt-body">' + tr("Sign in with your employee token to see today's decisions and ask Lighty "
                                           "about a customer.",
                                           "Mit dem Mitarbeiter-Token anmelden, um die Entscheidungen von heute zu sehen "
                                           "und Lighty zu einem Kunden zu fragen.") + '</p></div>')
        if mode != "token":
            st.warning(tr("Employee sign-in is not set up on this Lighty server (EMPLOYEE_TOKENS is empty).",
                          "Die Anmeldung für Mitarbeitende ist auf diesem Lighty-Server nicht eingerichtet "
                          "(EMPLOYEE_TOKENS ist leer)."))
            st.stop()
        with st.form("sign-in-form", border=False):
            token = st.text_input(tr("Employee token", "Mitarbeiter-Token"), type="password",
                                  placeholder=tr("Paste your token", "Token einfügen"))
            if st.form_submit_button(tr("Sign in", "Anmelden"), type="primary", width="stretch") and token.strip():
                if sign_in(token.strip()):
                    st.rerun()


if "token" not in st.session_state and os.environ.get("LIGHTY_TOKEN"):
    sign_in(os.environ["LIGHTY_TOKEN"])

if "token" not in st.session_state:
    st.navigation([st.Page(sign_in_page, title=tr("Sign in", "Anmelden"), icon=":material/login:")],
                  position="hidden").run()
    st.stop()

pages = [
    st.Page("views/cockpit.py", title="Cockpit", icon=":material/space_dashboard:", default=True),
    st.Page("views/risk.py", title=tr("Churn risk", "Kündigungsrisiko"), icon=":material/trending_down:"),
    st.Page("views/regions.py", title=tr("Regions", "Regionen"), icon=":material/map:"),
    st.Page("views/approvals.py", title=tr("Approval queue", "Freigaben"), icon=":material/inbox:"),
    st.Page("views/customer.py", title=tr("Customers", "Kunden"), icon=":material/group:"),
]
nav = st.navigation({tr("Workspace", "Arbeitsbereich"): pages})

with st.sidebar:
    me = st.session_state["me"]
    role = str(me.get("role", ""))
    role = tr(*ROLE[role]) if role in ROLE else role.replace("_", " ")
    st.caption(tr(f"Signed in as **{me.get('employee_id')}** · {role}",
                  f"Angemeldet als **{me.get('employee_id')}** · {role}"))
    language_switch()
    if st.button(tr("Sign out", "Abmelden"), icon=":material/logout:", type="tertiary"):
        for key in ("token", "me", "chats"):
            st.session_state.pop(key, None)
        st.cache_data.clear()
        st.rerun()

ui.show_flash()
nav.run()
