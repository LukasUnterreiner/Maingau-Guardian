"""Approval queue: every decision that needs a person's yes, with filters, approve and reject."""
import pandas as pd
import streamlit as st

import ui

STATUS_FILTER = {"Pending": "pending_approval", "Approved": "approved", "Rejected": "rejected"}

head, pill = st.columns([3, 1], vertical_alignment="bottom")
head.html('<h1 class="lt-h1">Approval queue</h1>'
          '<p class="lt-body">Every customer contact needs a person\'s yes. Select a row to review it.</p>')

f1, f2, f3 = st.columns([2, 2, 2], vertical_alignment="bottom")
status_label = f1.segmented_control("Status", list(STATUS_FILTER), default="Pending", key="queue-status") or "Pending"
items = ui.load(ui.decisions, STATUS_FILTER[status_label])
groups = sorted({ui.group(i.get("action_type")) for i in items})
group_filter = f2.selectbox("Decision", ["All decisions"] + groups)
channel_filter = f3.selectbox("Channel", ["All channels"] + sorted({ui.CHANNEL.get(i.get("channel"), i.get("channel"))
                                                                      for i in items}))
rows = [i for i in items
        if group_filter in ("All decisions", ui.group(i.get("action_type")))
        and channel_filter in ("All channels", ui.CHANNEL.get(i.get("channel"), i.get("channel")))]
pill.html(f'<div style="text-align: right;"><span class="lt-pill lt-pill--{"pending" if status_label == "Pending" else status_label.lower()}">'
          f'{len(rows):,} {status_label.lower()}</span></div>')

if not rows:
    st.info("Nothing here with these filters.")
    st.stop()

table = pd.DataFrame([{
    "Customer": i["customer_id"],
    "Decision": f"{ui.group(i.get('action_type'))} · {i.get('recommended_action_name')}",
    "Channel · tone": ui.channel_tone(i.get("channel"), i.get("tonality")),
    "CLV now (€)": i.get("current_clv_eur"),
    "Expected ΔCLV (€)": i.get("expected_dclv_eur"),
    "Chance": (i.get("acceptance_probability") or 0) * 100,
} for i in rows])
event = st.dataframe(
    table, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(rows)), on_select="rerun", selection_mode="single-row",
    key=f"queue-{status_label}-{group_filter}-{channel_filter}",
    column_config={
        "CLV now (€)": st.column_config.NumberColumn(format="euro"),
        "Expected ΔCLV (€)": st.column_config.NumberColumn(format="%+.2f"),
        "Chance": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
    })

selected = event.selection.rows if event and event.selection else []
if not selected:
    st.caption("Values are model-based estimates, not realised savings. Select a row to see the full decision.")
    st.stop()

row = rows[selected[0]]
rec = ui.load(ui.recommendation, row["customer_id"])
ui.html_block(ui.hero(rec))
ui.review_buttons(rec, f"queue-{rec['decision_id']}", open_customer=True)
