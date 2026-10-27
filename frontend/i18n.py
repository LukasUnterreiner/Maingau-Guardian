"""English and German for the web app.

The language is picked in the sidebar (or on the sign-in card) and kept in the address as ?lang=Deutsch, so a
reload keeps it. English is the default. Texts sit where they are used, as tr("English", "Deutsch"). The wording
for the customer is always German, whatever the app language.
"""
from __future__ import annotations

import streamlit as st

# label on the switch -> language code. The address shows the label (?lang=Deutsch): a bound widget keeps its
# label there, not the value behind it.
LANGUAGES = {"English": "en", "Deutsch": "de"}


def language_switch() -> None:
    st.segmented_control("Language", list(LANGUAGES), default="English", required=True, key="lang",
                         bind="query-params", persist_state="session", label_visibility="collapsed")


def lang() -> str:
    # before the switch is drawn on a fresh page load, the address is the only place that knows the language
    return LANGUAGES.get(st.session_state.get("lang") or st.query_params.get("lang"), "en")


def tr(en: str, de: str) -> str:
    return de if lang() == "de" else en


def switch_page(page: str) -> None:
    # st.switch_page on its own clears the whole address, and Streamlit refuses that while ?lang= is bound to
    # the switch. An empty dict clears it without the check; the switch puts ?lang= back on the next page.
    st.switch_page(page, query_params={})
