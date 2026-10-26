"""Cockpit: today's numbers, the customers most likely to cancel, the decisions waiting for review and the latest
reviews, laid out as soft cards."""
import plotly.graph_objects as go
import streamlit as st

import theme
import ui

ov = ui.load(ui.overview)
pending = ov.get("pending_approvals", 0)
total = ov.get("total_customers_evaluated", 0)
by_type = ov.get("recommended_by_action_type", {})
index = ui.load(ui.customer_index)
by_id = {c["customer_id"]: c for c in index}
levels = ui.risk_levels(index)
at_risk = [c for c in index if (c.get("churn_probability") or 0) >= levels["high"]]
at_stake = sum(c.get("current_clv_eur") or 0 for c in at_risk)
queue = ui.load(ui.decisions, "pending_approval")

ui.page_head(ui.greeting(), f"{pending:,} decisions are ready for your review.",
             f"Lighty evaluated all {total:,} customers. {by_type.get('no_contact', 0):,} are best left alone today, "
             f"{ov.get('customers_with_active_service_issues', 0):,} have an open service issue.")

# ------------------------------------------------------------------ tiles
groups = ["Offer", "Resolve an issue", "Strengthen loyalty"]
pending_by_group = [sum(1 for d in queue if ui.group(d.get("action_type")) == g) for g in groups]
tiers = ov.get("value_by_clv_tier") or {}
tier_order = [k for k in ("negative_value", "clv_0_500", "clv_500_1500", "clv_1500_plus") if k in tiers]
tier_names = {"negative_value": "negative CLV", "clv_0_500": "€0–500", "clv_500_1500": "€500–1,500",
              "clv_1500_plus": "€1,500+"}
protected = ov.get("projected_protected_customer_value_eur") or 0
baseline = (ov.get("baseline") or {}).get("total_expected_dclv_eur") or 0
lighty_total = ov.get("total_projected_incremental_clv_eur") or 0
trend = f'<span class="lt-trend">↑ {protected / baseline * 100:.0f}%</span> ' if baseline > 0 else ""
ui.tiles(
    ui.tile("inbox", "Pending approvals", ui.esc(f"{pending:,}"), "every contact needs a person's yes",
            "var(--lt-primary)",
            ui.minibars(pending_by_group, "var(--lt-primary)",
                        "Pending by decision: " + ", ".join(f"{g} {n}" for g, n in zip(groups, pending_by_group)))),
    ui.tile("users", "Likely to cancel", ui.esc(f"{len(at_risk):,}"),
            f"{ui.esc(ui.eur(at_stake, decimals=0))} customer value at stake", "var(--lt-resolve)",
            ui.minibars(ui.churn_histogram(index), "var(--lt-resolve)",
                        "All customers by churn risk: 0–9 %, 10–19 %, … 60 % and more")),
    ui.tile("trend", "Expected ΔCLV", ui.esc(ui.eur(lighty_total, sign=True, decimals=0)),
            f"on {ui.esc(ui.eur(ov.get('total_current_clv_eur'), decimals=0))} current CLV · Estimate",
            "var(--lt-gain)",
            ui.minibars([max((tiers[k] or {}).get("expected_dclv_eur") or 0, 0) for k in tier_order], "var(--lt-gain)",
                        "Expected ΔCLV by CLV tier: " + ", ".join(tier_names[k] for k in tier_order))),
    ui.tile("shield", "Protected customer value", ui.esc(ui.eur(protected, decimals=0)),
            f"{trend}vs. sales-first · Estimate", "var(--lt-brand)",
            ui.minibars([baseline, lighty_total], "var(--lt-brand)",
                        f"Expected ΔCLV: sales-first {ui.eur(baseline, decimals=0)}, "
                        f"Lighty {ui.eur(lighty_total, decimals=0)}")),
)

# ------------------------------------------------------------------ cards and feed
main, side = st.columns([2.7, 1], gap="medium")

with main:
    if ui.section("Likely to cancel", len(at_risk), "var(--lt-resolve)", "risk", "View all"):
        st.switch_page("views/risk.py")
    risky = sorted(at_risk, key=lambda c: -(c.get("current_clv_eur") or 0))[:4]
    cols = st.columns(2, gap="medium")
    for i, c in enumerate(risky):
        with cols[i % 2]:
            ui.customer_card(c, ui.load(ui.recommendation, c["customer_id"]), levels, f"risk-{c['customer_id']}")

    if ui.section("Waiting for your review", pending, "var(--lt-dot-pending)", "queue", "View all"):
        st.switch_page("views/approvals.py")
    shown = {c["customer_id"] for c in risky}
    top = [d for d in queue if d["customer_id"] not in shown and d["customer_id"] in by_id][:4]
    if not top:
        st.info("No decisions are waiting for review.")
    cols = st.columns(2, gap="medium")
    for i, d in enumerate(top):
        with cols[i % 2]:
            ui.customer_card(by_id[d["customer_id"]], ui.load(ui.recommendation, d["customer_id"]), levels,
                             f"queue-{d['customer_id']}")

with side:
    reviewed = ui.load(ui.decisions, "approved") + ui.load(ui.decisions, "rejected")
    ui.html_block(ui.activity_feed(reviewed))

    mix = {g: 0 for g in ui.DECISION_COLORS}
    for action_type, count in by_type.items():
        mix[ui.group(action_type)] += count
    with st.container(key="card-mix"):
        fig = go.Figure(go.Pie(labels=list(mix), values=list(mix.values()), hole=0.64, sort=False, textinfo="none",
                               marker=dict(colors=list(ui.DECISION_COLORS.values())),
                               hovertemplate="%{label}: %{value} customers<extra></extra>"))
        fig.update_layout(**theme.plotly_layout(title="Today's decision mix", height=300))
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False})

    channels = {ui.CHANNEL.get(k, k): v for k, v in ov.get("recommended_by_channel", {}).items() if k != "none"}
    with st.container(key="card-channels"):
        ordered = sorted(channels.items(), key=lambda kv: kv[1])
        fig = go.Figure(go.Bar(x=[v for _, v in ordered], y=[k for k, _ in ordered], orientation="h",
                               marker_color=theme.COLORS["primary"], hovertemplate="%{y}: %{x} contacts<extra></extra>"))
        fig.update_layout(**theme.plotly_layout(title="Contacts by channel", height=300))
        fig.update_yaxes(automargin=True)
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False})

st.caption(ov.get("projected_protected_customer_value_label", ""))
