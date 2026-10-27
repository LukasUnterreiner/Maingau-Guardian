"""Approval queue: every decision that needs a person's yes, with filters, approve and reject, and an Excel export."""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from openpyxl.styles import Font

import ui

STATUS_FILTER = {"Pending": "pending_approval", "Approved": "approved", "Rejected": "rejected"}
EXCEL_FORMATS = {"CLV now (€)": '#,##0.00 "€"', "Expected ΔCLV (€)": '+#,##0.00 "€";-#,##0.00 "€";0.00 "€"',
                 "Chance of acceptance": "0%"}


def excel(rows: list[dict]) -> bytes:
    """The filtered queue as an .xlsx file: plain numbers with formats, header row frozen, filters on."""
    def berlin(iso: str | None) -> str:
        return f"{datetime.fromisoformat(iso).astimezone(ZoneInfo('Europe/Berlin')):%Y-%m-%d %H:%M}" if iso else ""

    frame = pd.DataFrame([{
        "Customer": i["customer_id"],
        "Decision": ui.group(i.get("action_type")),
        "Action": i.get("recommended_action_name"),
        "Product id": i.get("recommended_action"),
        "Channel": ui.CHANNEL.get(i.get("channel"), i.get("channel")),
        "Form of address": (i.get("tonality") or "").capitalize(),
        "CLV now (€)": i.get("current_clv_eur"),
        "Expected ΔCLV (€)": i.get("expected_dclv_eur"),
        "Chance of acceptance": i.get("acceptance_probability"),
        "Service process required": "yes" if i.get("required_service_workflow") else "no",
        "Status": ui.STATUS.get(i.get("approval_status"), i.get("approval_status")),
        "Reviewed by": i.get("reviewed_by") or "",
        "Reviewed at (Berlin)": berlin(i.get("reviewed_at")),
        "Decision id": i["decision_id"],
    } for i in rows])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as book:
        frame.to_excel(book, sheet_name="Approval queue", index=False)
        sheet = book.sheets["Approval queue"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for name, cells in zip(frame.columns, sheet.iter_cols()):
            cells[0].font = Font(bold=True)
            for cell in cells[1:]:
                cell.number_format = EXCEL_FORMATS.get(name, cell.number_format)
            width = max(len(str(c.value)) if c.value is not None else 0 for c in cells)
            sheet.column_dimensions[cells[0].column_letter].width = min(width + 3, 48)
    return out.getvalue()


head, pill = st.columns([3, 1], vertical_alignment="bottom")
with head:
    ui.page_head("Approval queue", "Every contact needs a person's yes.", "Select a row to review it.")

f1, f2, f3 = st.columns([2.5, 2, 2], vertical_alignment="bottom")
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
pill.download_button("Export to Excel", excel(rows), icon=":material/download:", width="stretch",
                     file_name=f"lighty-approval-queue-{status_label.lower()}-{datetime.now(ZoneInfo('Europe/Berlin')):%Y-%m-%d}.xlsx",
                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     help="All rows that match the filters, as an Excel file")

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
