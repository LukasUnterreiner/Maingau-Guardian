"""Churn risk: which customers are likely to cancel, why, and how much customer value is at stake."""
import pandas as pd
import streamlit as st

import ui

index = ui.load(ui.customer_index)
levels = ui.risk_levels(index)
at_risk = [c for c in index if (c.get("churn_probability") or 0) >= levels["high"]]
at_stake = sum(c.get("current_clv_eur") or 0 for c in at_risk)

ui.page_head("Churn risk · next 12 months", f"{len(at_risk):,} customers are likely to cancel.",
             f"If they leave, {ui.eur(at_stake, decimals=0)} of customer value goes with them. Lighty shows why each "
             "one is at risk and what the best next step is worth.")
ui.html_block(ui.risk_tiles(at_risk, index, levels))

f1, f2, _ = st.columns([2, 2, 2], vertical_alignment="bottom")
scope = f1.segmented_control("Show", ["Likely to cancel", "All customers"], default="Likely to cancel",
                             key="risk-scope") or "Likely to cancel"
sort = f2.selectbox("Sort by", ["Churn risk", "Customer value at stake", "Lost to service problems"])
rows = at_risk if scope == "Likely to cancel" else index
key = {"Churn risk": lambda c: (-(c.get("churn_probability") or 0), -(c.get("current_clv_eur") or 0)),
       "Customer value at stake": lambda c: -(c.get("current_clv_eur") or 0),
       "Lost to service problems": lambda c: c.get("clv_service_impact_reported_eur") or 0}[sort]
rows = sorted(rows, key=key)

table = pd.DataFrame([{
    "Customer": c["customer_id"],
    "Churn risk": (c.get("churn_probability") or 0) * 100,
    "Risk": ui.risk_level(c.get("churn_probability") or 0, levels),
    "Why": "Cancellation received" if c.get("cancellation_pending")
           else ", ".join(c.get("churn_drivers") or []) or "Base risk of the contracts",
    "At stake (€)": c.get("current_clv_eur"),
    "Lost to service (€)": c.get("clv_service_impact_reported_eur"),
    "City": c.get("city"),
} for c in rows])
event = st.dataframe(
    table, hide_index=True, width="stretch", height=min(460, 38 + 35 * len(rows)), on_select="rerun",
    selection_mode="single-row", key=f"risk-{scope}-{sort}",
    column_config={
        "Churn risk": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100, width="small"),
        "Why": st.column_config.TextColumn(width="large"),
        "At stake (€)": st.column_config.NumberColumn(format="euro"),
        "Lost to service (€)": st.column_config.NumberColumn(format="euro"),
    })

selected = event.selection.rows if event and event.selection else []
if not selected:
    st.caption(f"Likely to cancel = the top quarter of all {len(index):,} customers by churn risk "
               f"(≥ {ui.pct(levels['high'])}). Churn risk and customer value are model-based estimates; "
               "'lost to service problems' is the CLV effect of service cases reported in the data. "
               "Select a row to see the customer.")
    st.stop()

cid = rows[selected[0]]["customer_id"]
c360 = ui.load(ui.customer, cid)
rec = ui.load(ui.recommendation, cid)
ui.html_block(ui.risk_card(c360, rec, levels))
if st.button(f"Open {cid}", icon=":material/arrow_forward:", type="tertiary", key="open-risk"):
    st.session_state["customer_id"] = cid
    st.switch_page("views/customer.py")
