"""See the Daylight theme in Streamlit: native widgets plus the shared CSS pieces.

Run:  cd 03_Code/theme && streamlit run demo.py
Numbers are real engine output from Maingau-Guardian/API_CONTRACT.md (MG-100004, marketing overview).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the 03_Code folder, so `import theme` works

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

import theme  # noqa: E402

st.set_page_config(page_title="Lighty · theme demo", layout="wide")
theme.apply_theme()

with st.sidebar:
    st.markdown("### Lighty")
    st.caption("MAINGAU Energie · theme demo")
    st.selectbox("Channel", ["All channels", "Newsletter e-mail", "App push"])
    st.toggle("Include “Do not contact”", value=True)

st.caption("Monday, 26 October · Good morning")
st.title("413 decisions are ready for your review.")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Protected customer value", "€7,959", "+99% vs. sales-first")
k2.metric("Expected ΔCLV", "+€15,982", "on €412,035 CLV", delta_color="off")
k3.metric("Pending approvals", "413")
k4.metric("Customers with service issues", "227")

st.markdown("""
<article class="lt-hero">
  <div class="lt-hero__meta">
    <span class="lt-hero__badge"><svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>Lighty recommends</span>
    <span class="lt-kind lt-kind--resolve">Resolve an issue</span>
    <span class="lt-spacer"></span>
    <span class="lt-hero__status">Pending approval</span>
  </div>
  <h2 class="lt-hero__title">Call back and resolve the open complaint. No offer.</h2>
  <p class="lt-hero__reason">Resolving removes the service churn drivers (open complaint, dunning level 2 or higher),
    lowering churn from 38% to 18% if successful.</p>
  <div class="lt-hero__stats">
    <div class="lt-hero__stat"><span class="lt-hero__stat-label">Expected ΔCLV</span><span class="lt-hero__stat-value">+€66.50</span></div>
    <div class="lt-hero__stat"><span class="lt-hero__stat-label">Success chance</span><span class="lt-hero__stat-value">71%</span></div>
    <div class="lt-hero__stat"><span class="lt-hero__stat-label">CLV after</span><span class="lt-hero__stat-value">€233.55</span></div>
    <div class="lt-hero__stat"><span class="lt-hero__stat-label">Channel</span><span class="lt-hero__stat-value">Call · Sie</span></div>
  </div>
  <span class="lt-hero__fine">MG-100004 · DEC-48c1817e05fdc73d · Estimate, not proven uplift</span>
</article>
""", unsafe_allow_html=True)

left, right = st.columns([3, 2])
with left:
    with st.container(border=True):
        st.subheader("Approval queue")
        queue = pd.DataFrame([
            ["MG-100315", "Resolve an issue", "Service e-mail · Sie", 898.31, 223.09],
            ["MG-100009", "Resolve an issue", "Service call · Sie", 402.96, 77.13],
            ["MG-100004", "Resolve an issue", "Service call · Sie", 167.05, 66.50],
            ["MG-100127", "Offer · Mobil S / M / L", "App push · Sie", 3263.46, 66.00],
        ], columns=["Customer", "Decision", "Channel · tone", "CLV (€)", "ΔCLV (€)"])
        st.dataframe(queue, hide_index=True, width="stretch")
        b1, b2, _ = st.columns([1, 1, 3])
        b1.button("Approve", type="primary", width="stretch")
        b2.button("Reject", width="stretch")
with right:
    with st.container(border=True):
        st.subheader("Building blocks")
        st.html(" ".join(theme.status_pill(s) for s in ("pending_approval", "approved", "rejected", "not_required")))
        st.html(" ".join(theme.decision_chip(d) for d in theme.DECISION_COLORS))
        st.html(theme.tone_chip("sie", "customer's own words") + " " + theme.tone_chip("du", "campaign history")
                + " " + " ".join(theme.value_tag(k) for k in ("estimate", "observed", "simulated")))
        st.html('<div class="lt-banner lt-banner--attention">Open service case: no sales offers.</div>')
        st.slider("Success chance P-SV-01", 0, 100, 50, format="%d%%")

mix = go.Figure(go.Pie(labels=list(theme.DECISION_COLORS), values=[271, 118, 24, 337], hole=0.62, sort=False,
                       marker=dict(colors=list(theme.DECISION_COLORS.values())), textinfo="none"))
mix.update_layout(**theme.plotly_layout(title="Today's decision mix", height=320))
with st.container(border=True):
    st.plotly_chart(mix, theme=None)
