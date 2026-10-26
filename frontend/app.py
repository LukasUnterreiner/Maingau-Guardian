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

HERE = Path(__file__).resolve().parent

st.set_page_config(page_title="Lighty", page_icon=str(HERE / "static" / "lighty-mark.svg"), layout="wide")
theme.apply_theme()
st.markdown(f"<style>{(HERE / 'app.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
st.logo(str(HERE / "static" / "lighty-logo.svg"), size="large", icon_image=str(HERE / "static" / "lighty-mark.svg"))


def sign_in(token: str) -> bool:
    try:
        st.session_state["me"] = api.me(token)
    except api.LightyError as exc:
        st.session_state.pop("me", None)
        st.error("This token is not valid." if exc.status == 401 else exc.message)
        return False
    st.session_state["token"] = token
    return True


def sign_in_page() -> None:
    try:
        mode = api.health().get("employee_auth", {}).get("mode")
    except api.LightyError as exc:
        st.error(exc.message)
        st.stop()
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid, st.container(border=True, key="sign-in"):
        st.html('<div class="lt-stack" style="gap: 6px;"><span class="lt-label">Lighty · MAINGAU Energie</span>'
                '<h1 class="lt-h1">Smarter decisions. Better conversations.</h1>'
                '<p class="lt-body">Sign in with your employee token to see today\'s decisions and ask Lighty about a '
                'customer.</p></div>')
        if mode != "token":
            st.warning("Employee sign-in is not set up on this Lighty server (EMPLOYEE_TOKENS is empty).")
            st.stop()
        with st.form("sign-in-form", border=False):
            token = st.text_input("Employee token", type="password", placeholder="Paste your token")
            if st.form_submit_button("Sign in", type="primary", width="stretch") and token.strip():
                if sign_in(token.strip()):
                    st.rerun()


if "token" not in st.session_state and os.environ.get("LIGHTY_TOKEN"):
    sign_in(os.environ["LIGHTY_TOKEN"])

if "token" not in st.session_state:
    st.navigation([st.Page(sign_in_page, title="Sign in", icon=":material/login:")], position="hidden").run()
    st.stop()

pages = [
    st.Page("views/cockpit.py", title="Cockpit", icon=":material/space_dashboard:", default=True),
    st.Page("views/risk.py", title="Churn risk", icon=":material/trending_down:"),
    st.Page("views/approvals.py", title="Approval queue", icon=":material/inbox:"),
    st.Page("views/customer.py", title="Customers", icon=":material/group:"),
]
nav = st.navigation({"Workspace": pages})

with st.sidebar:
    me = st.session_state["me"]
    st.caption(f"Signed in as **{me.get('employee_id')}** · {str(me.get('role', '')).replace('_', ' ')}")
    if st.button("Sign out", icon=":material/logout:", type="tertiary"):
        for key in ("token", "me", "chats"):
            st.session_state.pop(key, None)
        st.cache_data.clear()
        st.rerun()

ui.show_flash()
nav.run()
