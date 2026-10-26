"""Cockpit: today's numbers, the most valuable decision waiting for review and the decision mix."""
import plotly.graph_objects as go
import streamlit as st

import theme
import ui

ov = ui.load(ui.overview)
pending = ov.get("pending_approvals", 0)
total = ov.get("total_customers_evaluated", 0)
by_type = ov.get("recommended_by_action_type", {})

ui.html_block('<div class="lt-stack" style="gap: 8px;">'
              f'<span class="lt-small" style="color: var(--lt-primary); font-weight: 600;">{ui.esc(ui.greeting())}</span>'
              f'<h1 class="lt-display">{pending:,} decisions are ready for your review.</h1>'
              f'<p class="lt-body">Lighty evaluated all {total:,} customers. {by_type.get("no_contact", 0):,} of them are '
              'best left alone today.</p></div>')
ui.html_block(ui.kpi_tiles(ov))

index = ui.load(ui.customer_index)
levels = ui.risk_levels(index)
at_risk = [c for c in index if (c.get("churn_probability") or 0) >= levels["high"]]
with st.container(horizontal=True, vertical_alignment="center", key="risk-banner"):
    st.html(f'<div class="lt-row" style="gap: 10px;">{ui.svg("alert")}<span><strong>{len(at_risk):,} customers are '
            f'likely to cancel</strong> (≥ {ui.esc(ui.pct(levels["high"]))} churn risk in 12 months). '
            f'{ui.esc(ui.eur(sum(c.get("current_clv_eur") or 0 for c in at_risk), decimals=0))} customer value is '
            'at stake.</span></div>')
    if st.button("Show churn risk", icon=":material/arrow_forward:", type="tertiary", key="to-risk"):
        st.switch_page("views/risk.py")

queue = ui.load(ui.decisions, "pending_approval")
if queue:
    top = queue[0]   # the list is sorted by expected ΔCLV
    rec = ui.load(ui.recommendation, top["customer_id"])
    ui.html_block(ui.hero(rec))
    ui.review_buttons(rec, "cockpit", open_customer=True)
else:
    st.info("No decisions are waiting for review.")

mix = {g: 0 for g in ui.DECISION_COLORS}
for action_type, count in by_type.items():
    mix[ui.group(action_type)] += count
channels = {ui.CHANNEL.get(k, k): v for k, v in ov.get("recommended_by_channel", {}).items() if k != "none"}

c1, c2 = st.columns(2)
with c1, st.container(border=True, key="card-mix"):
    fig = go.Figure(go.Pie(labels=list(mix), values=list(mix.values()), hole=0.62, sort=False, textinfo="none",
                           marker=dict(colors=list(ui.DECISION_COLORS.values())),
                           hovertemplate="%{label}: %{value} customers<extra></extra>"))
    fig.update_layout(**theme.plotly_layout(title="Today's decision mix", height=320))
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})
with c2, st.container(border=True, key="card-channels"):
    ordered = sorted(channels.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(x=[v for _, v in ordered], y=[k for k, _ in ordered], orientation="h",
                           marker_color=theme.COLORS["primary"], hovertemplate="%{y}: %{x} contacts<extra></extra>"))
    fig.update_layout(**theme.plotly_layout(title="Recommended contacts by channel", height=320))
    fig.update_yaxes(automargin=True)
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})

st.caption(ov.get("projected_protected_customer_value_label", ""))
