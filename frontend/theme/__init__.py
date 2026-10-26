"""Lighty "Daylight" theme: the colours, font and building blocks of every Lighty screen.

In plain words: the look lives in files next to this one.
- lighty-theme.css         works in any web page (plain HTML, React, Streamlit). preview.html shows every part.
- .streamlit/config.toml   the same colours and font as Streamlit settings.
- streamlit.css            small Streamlit extras that the settings cannot do.

Streamlit, two steps:
1. copy the [theme] and [theme.sidebar] blocks from theme/.streamlit/config.toml into 03_Code/.streamlit/config.toml
2. call apply_theme() right after st.set_page_config() (for example in common.setup_page())
Then st.html(status_pill("pending_approval")) and the other helpers below render as Lighty chips.
For HTML with SVG icons (the hero card, nav) use st.markdown(..., unsafe_allow_html=True): st.html strips SVG.

See it: cd 03_Code/theme && streamlit run demo.py
"""
from __future__ import annotations

import html
from pathlib import Path

THEME_DIR = Path(__file__).resolve().parent

# Same values as the CSS variables, for Plotly charts and anything drawn in Python.
COLORS = {
    "canvas": "#F1F6FF", "surface": "#FFFFFF", "line": "#E2EAF6", "muted": "#567398",
    "ink_2": "#1B4274", "ink": "#002657", "night": "#002657", "brand": "#004BAD", "primary": "#0069F1",
    "spark": "#FFE500", "gain": "#008153", "loss": "#E20707",
}   # MAINGAU website tokens: brand-blue-dark, brand-blue, brand-blue-radiant, brand-yellow, green, red
# The four decisions in chart order. Keys match common.DECISION_ORDER.
DECISION_COLORS = {"Offer": "#004BAD", "Resolve an issue": "#F08C1A",
                   "Strengthen loyalty": "#008153", "Do not contact": "#B5C5DA"}

_KIND_CLASS = {"Offer": "offer", "Resolve an issue": "resolve",
               "Strengthen loyalty": "loyalty", "Do not contact": "nocontact"}
_STATUS = {"pending_approval": ("pending", "Pending approval"), "approved": ("approved", "Approved"),
           "rejected": ("rejected", "Rejected"), "not_required": ("", "No approval needed")}


def stylesheet() -> str:
    """The shared theme CSS plus the Streamlit extras, as one string."""
    return "\n".join((THEME_DIR / name).read_text(encoding="utf-8")
                     for name in ("lighty-theme.css", "streamlit.css"))


def apply_theme() -> None:
    """Call once per page, right after st.set_page_config().

    st.markdown, not st.html: in Streamlit 1.66 st.html drops a style-only body and strips SVG icons.
    """
    import streamlit as st
    st.markdown(f'<style id="lighty-theme">{stylesheet()}</style>', unsafe_allow_html=True)


def plotly_layout(**overrides) -> dict:
    """Daylight look for Plotly: fig.update_layout(**plotly_layout()), then st.plotly_chart(fig, theme=None)."""
    axis = dict(gridcolor=COLORS["line"], zerolinecolor=COLORS["line"], linecolor=COLORS["line"])
    layout = dict(
        font=dict(family="Plus Jakarta Sans, sans-serif", size=13, color=COLORS["ink_2"]),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=list(DECISION_COLORS.values()) + [COLORS["primary"], COLORS["muted"]],
        margin=dict(l=8, r=8, t=48, b=8),
        title_x=0, title_xanchor="left",
        title_font=dict(family="Plus Jakarta Sans, sans-serif", size=16, color=COLORS["ink"]),
        xaxis=axis, yaxis=axis,
        legend=dict(orientation="h", yanchor="top", y=-0.04, xanchor="left", x=0),
        hoverlabel=dict(bgcolor=COLORS["ink"], bordercolor=COLORS["ink"], font=dict(color="#FFFFFF")),
    )
    if isinstance(overrides.get("title"), str):           # a plain title must not replace the styled one
        overrides["title_text"] = overrides.pop("title")
    layout.update(overrides)
    return layout


# ---------------------------------------------------------------- small HTML pieces for st.html()
def status_pill(status: str) -> str:
    """'pending_approval' -> a Pending approval pill with an amber dot."""
    modifier, label = _STATUS.get(status, ("", status.replace("_", " ").capitalize()))
    cls = f"lt-pill lt-pill--{modifier}" if modifier else "lt-pill"
    return f'<span class="{cls}">{html.escape(label)}</span>'


def decision_chip(decision_type: str, text: str | None = None) -> str:
    """'Resolve an issue' -> an orange chip. Optional text, e.g. 'Offer · Mobil S / M / L'."""
    kind = _KIND_CLASS.get(decision_type, "nocontact")
    return f'<span class="lt-kind lt-kind--{kind}">{html.escape(text or decision_type)}</span>'


def value_tag(kind: str = "estimate") -> str:
    """'estimate' (model output), 'observed' (source data) or 'simulated' (what-if)."""
    return f'<span class="lt-tag lt-tag--{html.escape(kind)}">{html.escape(kind.capitalize())}</span>'


def tone_chip(tone: str, source: str = "") -> str:
    """'sie', "customer's own words" -> a Sie | source chip. Du is drawn in radiant blue."""
    value = tone.capitalize()
    du = " lt-tone--du" if tone.lower() == "du" else ""
    extra = f'<span class="lt-tone__source">{html.escape(source)}</span>' if source else ""
    return f'<span class="lt-tone{du}"><span class="lt-tone__value">{html.escape(value)}</span>{extra}</span>'
