"""Approval queue: every decision that needs a person's yes, with filters, approve and reject, and an Excel export."""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from openpyxl.styles import Font

import ui
from i18n import tr

# filter key -> (approval status in the API, English, German)
STATUS_FILTER = {"pending": ("pending_approval", "Pending", "Offen"), "approved": ("approved", "Approved", "Freigegeben"),
                 "rejected": ("rejected", "Rejected", "Abgelehnt")}
# Excel shows the numbers in the reader's own format; these only say what kind of number it is
MONEY, SIGNED_MONEY, SHARE = '#,##0.00 "€"', '+#,##0.00 "€";-#,##0.00 "€";0.00 "€"', "0%"


def excel(rows: list[dict]) -> bytes:
    """The filtered queue as an .xlsx file: plain numbers with formats, header row frozen, filters on."""
    def berlin(iso: str | None) -> str:
        return f"{datetime.fromisoformat(iso).astimezone(ZoneInfo('Europe/Berlin')):%Y-%m-%d %H:%M}" if iso else ""

    clv, dclv, chance = tr("CLV now (€)", "CLV jetzt (€)"), tr("Expected ΔCLV (€)", "Erwarteter ΔCLV (€)"), \
        tr("Chance of acceptance", "Annahmechance")
    formats = {clv: MONEY, dclv: SIGNED_MONEY, chance: SHARE}
    frame = pd.DataFrame([{
        tr("Customer", "Kunde"): i["customer_id"],
        tr("Decision", "Entscheidung"): ui.group_name(ui.group(i.get("action_type"))),
        tr("Action", "Aktion"): ui.action_name(i),
        tr("Product id", "Produkt-ID"): i.get("recommended_action"),
        tr("Channel", "Kanal"): ui.channel(i.get("channel")),
        tr("Form of address", "Anrede"): ui.tone(i.get("tonality")) if i.get("tonality") else "",
        clv: i.get("current_clv_eur"),
        dclv: i.get("expected_dclv_eur"),
        chance: i.get("acceptance_probability"),
        tr("Service process required", "Serviceprozess nötig"):
            tr("yes", "ja") if i.get("required_service_workflow") else tr("no", "nein"),
        "Status": ui.status(i.get("approval_status")),
        tr("Reviewed by", "Geprüft von"): i.get("reviewed_by") or "",
        tr("Reviewed at (Berlin)", "Geprüft am (Berlin)"): berlin(i.get("reviewed_at")),
        tr("Decision id", "Entscheidungs-ID"): i["decision_id"],
    } for i in rows])
    sheet_name = tr("Approval queue", "Freigaben")
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as book:
        frame.to_excel(book, sheet_name=sheet_name, index=False)
        sheet = book.sheets[sheet_name]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for name, cells in zip(frame.columns, sheet.iter_cols()):
            cells[0].font = Font(bold=True)
            for cell in cells[1:]:
                cell.number_format = formats.get(name, cell.number_format)
            width = max(len(str(c.value)) if c.value is not None else 0 for c in cells)
            sheet.column_dimensions[cells[0].column_letter].width = min(width + 3, 48)
    return out.getvalue()


head, pill = st.columns([3, 1], vertical_alignment="bottom")
with head:
    ui.page_head(tr("Approval queue", "Freigaben"), tr("Every contact needs a person's yes.",
                                                     "Jeder Kontakt braucht das Ja eines Menschen."),
                 tr("Select a row to review it.", "Eine Zeile auswählen, um sie zu prüfen."))

f1, f2, f3 = st.columns([2.5, 2, 2], vertical_alignment="bottom")
status_key = f1.segmented_control("Status", list(STATUS_FILTER), format_func=lambda k: tr(*STATUS_FILTER[k][1:]),
                                  default="pending", key="queue-status") or "pending"
items = ui.load(ui.decisions, STATUS_FILTER[status_key][0])
groups = sorted({ui.group(i.get("action_type")) for i in items})
group_filter = f2.selectbox(
    tr("Decision", "Entscheidung"), ["all"] + groups, key="queue-group",
    format_func=lambda g: tr("All decisions", "Alle Entscheidungen") if g == "all" else ui.group_name(g))
channel_filter = f3.selectbox(
    tr("Channel", "Kanal"), ["all"] + sorted({i.get("channel") or "none" for i in items}, key=ui.channel),
    key="queue-channel", format_func=lambda c: tr("All channels", "Alle Kanäle") if c == "all" else ui.channel(c))
rows = [i for i in items
        if group_filter in ("all", ui.group(i.get("action_type")))
        and channel_filter in ("all", i.get("channel") or "none")]
pill.html(f'<div style="text-align: right;"><span class="lt-pill lt-pill--{status_key}">'
          f'{ui.num(len(rows))} {tr(*STATUS_FILTER[status_key][1:]).lower()}</span></div>')

if not rows:
    st.info(tr("Nothing here with these filters.", "Mit diesen Filtern gibt es nichts."))
    st.stop()
pill.download_button(tr("Export to Excel", "Als Excel exportieren"), excel(rows), icon=":material/download:",
                     width="stretch",
                     file_name=f"lighty-approval-queue-{status_key}-{datetime.now(ZoneInfo('Europe/Berlin')):%Y-%m-%d}.xlsx",
                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     help=tr("All rows that match the filters, as an Excel file",
                             "Alle Zeilen, die zu den Filtern passen, als Excel-Datei"))

CUSTOMER, DECISION, CHANNEL = tr("Customer", "Kunde"), tr("Decision", "Entscheidung"), tr("Channel · tone", "Kanal · Anrede")
CLV, DCLV, CHANCE = tr("CLV now (€)", "CLV jetzt (€)"), tr("Expected ΔCLV (€)", "Erwarteter ΔCLV (€)"), \
    tr("Chance", "Chance")
table = pd.DataFrame([{
    CUSTOMER: i["customer_id"],
    DECISION: f"{ui.group_name(ui.group(i.get('action_type')))} · {ui.action_name(i)}",
    CHANNEL: ui.channel_tone(i.get("channel"), i.get("tonality")),
    CLV: i.get("current_clv_eur"),
    DCLV: i.get("expected_dclv_eur"),
    CHANCE: (i.get("acceptance_probability") or 0) * 100,
} for i in rows])
event = st.dataframe(
    table, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(rows)), on_select="rerun", selection_mode="single-row",
    key=f"queue-{status_key}-{group_filter}-{channel_filter}",
    column_config={
        CLV: st.column_config.NumberColumn(format="euro"),
        DCLV: st.column_config.NumberColumn(format="%+.2f"),
        CHANCE: st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
    })

selected = event.selection.rows if event and event.selection else []
if not selected:
    st.caption(tr("Values are model-based estimates, not realised savings. Select a row to see the full decision.",
                  "Die Werte sind modellbasierte Schätzungen, keine realisierten Einsparungen. Eine Zeile auswählen, "
                  "um die ganze Entscheidung zu sehen."))
    st.stop()

row = rows[selected[0]]
rec = ui.load(ui.recommendation, row["customer_id"])
ui.html_block(ui.hero(rec))
ui.review_buttons(rec, f"queue-{rec['decision_id']}", open_customer=True)
