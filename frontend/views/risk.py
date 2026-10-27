"""Churn risk: which customers are likely to cancel, why, and how much customer value is at stake."""
import pandas as pd
import streamlit as st

import ui
from i18n import switch_page, tr

index = ui.load(ui.customer_index)
levels = ui.risk_levels(index)
at_risk = [c for c in index if (c.get("churn_probability") or 0) >= levels["high"]]
at_stake = sum(c.get("current_clv_eur") or 0 for c in at_risk)

ui.page_head(tr("Churn risk · next 12 months", "Kündigungsrisiko · nächste 12 Monate"),
             tr(f"{ui.num(len(at_risk))} customers are likely to cancel.",
                f"{ui.num(len(at_risk))} Kunden werden wahrscheinlich kündigen."),
             tr(f"If they leave, {ui.eur(at_stake, decimals=0)} of customer value goes with them. Lighty shows why each "
                "one is at risk and what the best next step is worth.",
                f"Wenn sie gehen, gehen {ui.eur(at_stake, decimals=0)} Kundenwert mit. Lighty zeigt, warum jeder "
                "einzelne gefährdet ist und was der beste nächste Schritt wert ist."))
ui.html_block(ui.risk_tiles(at_risk, index, levels))

SCOPES = {"at_risk": ("Likely to cancel", "Kündigungsgefährdet"), "all": ("All customers", "Alle Kunden")}
SORTS = {"churn": ("Churn risk", "Kündigungsrisiko"), "at_stake": ("Customer value at stake", "Gefährdeter Kundenwert"),
         "service": ("Lost to service problems", "Durch Serviceprobleme verloren")}
f1, f2, _ = st.columns([2, 2, 2], vertical_alignment="bottom")
scope = f1.segmented_control(tr("Show", "Anzeigen"), list(SCOPES), format_func=lambda k: tr(*SCOPES[k]),
                             default="at_risk", key="risk-scope") or "at_risk"
sort = f2.selectbox(tr("Sort by", "Sortieren nach"), list(SORTS), format_func=lambda k: tr(*SORTS[k]), key="risk-sort")
rows = at_risk if scope == "at_risk" else index
key = {"churn": lambda c: (-(c.get("churn_probability") or 0), -(c.get("current_clv_eur") or 0)),
       "at_stake": lambda c: -(c.get("current_clv_eur") or 0),
       "service": lambda c: c.get("clv_service_impact_reported_eur") or 0}[sort]
rows = sorted(rows, key=key)

CUSTOMER, CHURN, RISK, WHY = tr("Customer", "Kunde"), tr("Churn risk", "Kündigungsrisiko"), tr("Risk", "Risiko"), \
    tr("Why", "Warum")
AT_STAKE, LOST, CITY = tr("At stake (€)", "Gefährdet (€)"), tr("Lost to service (€)", "Verlust durch Service (€)"), \
    tr("City", "Stadt")
table = pd.DataFrame([{
    CUSTOMER: c["customer_id"],
    CHURN: (c.get("churn_probability") or 0) * 100,
    RISK: ui.risk_name(ui.risk_level(c.get("churn_probability") or 0, levels)),
    WHY: tr("Cancellation received", "Kündigung liegt vor") if c.get("cancellation_pending")
         else ", ".join(ui.driver(d) for d in c.get("churn_drivers") or [])
         or tr("Base risk of the contracts", "Grundrisiko der Verträge"),
    AT_STAKE: c.get("current_clv_eur"),
    LOST: c.get("clv_service_impact_reported_eur"),
    CITY: c.get("city"),
} for c in rows])
event = st.dataframe(
    table, hide_index=True, width="stretch", height=min(460, 38 + 35 * len(rows)), on_select="rerun",
    selection_mode="single-row", key=f"risk-{scope}-{sort}",
    column_config={
        CHURN: st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100, width="small"),
        WHY: st.column_config.TextColumn(width="large"),
        AT_STAKE: st.column_config.NumberColumn(format="euro"),
        LOST: st.column_config.NumberColumn(format="euro"),
    })

selected = event.selection.rows if event and event.selection else []
if not selected:
    st.caption(tr(f"Likely to cancel = the top quarter of all {ui.num(len(index))} customers by churn risk "
                  f"(≥ {ui.pct(levels['high'])}). Churn risk and customer value are model-based estimates; "
                  "'lost to service problems' is the CLV effect of service cases reported in the data. "
                  "Select a row to see the customer.",
                  f"Kündigungsgefährdet = das oberste Viertel aller {ui.num(len(index))} Kunden nach Kündigungsrisiko "
                  f"(≥ {ui.pct(levels['high'])}). Kündigungsrisiko und Kundenwert sind modellbasierte Schätzungen; "
                  "„durch Serviceprobleme verloren“ ist die CLV-Wirkung der Servicefälle aus den Daten. "
                  "Eine Zeile auswählen, um den Kunden zu sehen."))
    st.stop()

cid = rows[selected[0]]["customer_id"]
c360 = ui.load(ui.customer, cid)
rec = ui.load(ui.recommendation, cid)
ui.html_block(ui.risk_card(c360, rec, levels))
if st.button(tr(f"Open {cid}", f"{cid} öffnen"), icon=":material/arrow_forward:", type="tertiary", key="open-risk"):
    st.session_state["customer_id"] = cid
    switch_page("views/customer.py")
