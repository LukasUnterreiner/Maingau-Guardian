"""Regions: customers, churn risk, value and workload per state and city, on a map of Germany.

The colour of a state shows a rate, the size of a city bubble an amount. Click a state to zoom in, click a city to
narrow the customer cards to it. Reporting only: Lighty never uses the region for a recommendation.
"""
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import theme
import ui

STATIC = Path(__file__).resolve().parent.parent / "static"
# view: rate (state colour), amount (city bubble) and whether the amount is money
VIEWS = {
    "Churn": ("Likely to cancel", lambda r: r["likely_to_cancel_share"] or 0, "Value at stake", "clv_at_stake_eur", True),
    "Service": ("With a service issue", lambda r: r["service_issues"] / r["customers"], "Open service issues",
                "service_issues", False),
    "Opportunity": ("ΔCLV per customer", lambda r: r["expected_dclv_eur"] / r["customers"], "Expected ΔCLV",
                    "expected_dclv_eur", True),
    "Workload": ("Waiting for review", lambda r: r["pending_approvals"] / r["customers"], "Decisions to review",
                 "pending_approvals", False),
}
CROWDED = {"Offenbach", "Obertshausen"}  # 5 to 10 km from Frankfurt and Hanau: name on hover only
LABEL_AT = {"Frankfurt": "top left", "Hanau": "top right", "Wiesbaden": "middle left", "Mainz": "bottom left",
            "Darmstadt": "bottom center"}


@st.cache_resource
def outlines() -> dict:
    """The 16 states (Natural Earth, public domain), ids are ISO 3166-2 codes such as DE-HE."""
    return json.loads((STATIC / "geo" / "de-states.geojson").read_text(encoding="utf-8"))


def bounds(geo: dict, code: str) -> tuple[float, float, float, float]:
    feature = next(f for f in geo["features"] if f["properties"]["id"] == code)
    polygons = feature["geometry"]["coordinates"]
    if feature["geometry"]["type"] == "Polygon":
        polygons = [polygons]
    points = [p for polygon in polygons for ring in polygon for p in ring]
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    return min(lons), max(lons), min(lats), max(lats)


geo = outlines()
names = {f["properties"]["id"]: f["properties"]["name"] for f in geo["features"]}
by_level = {level: ui.load(ui.regions, level) for level in ("state", "city")}
states = {r["id"]: r for r in by_level["state"]["regions"] if r["state_code"]}
cities = {r["id"]: r for r in by_level["city"]["regions"] if r["state_code"]}
total = by_level["state"]["totals"]

region = st.query_params.get("region")
region = region if region in states else None
city = st.query_params.get("city")
city = city if city in cities and cities[city]["state_code"] == region else None

ui.page_head("Regions", "Where customers and value are at risk",
             f"{len(cities)} cities in {len(states)} states. Click a state on the map to look closer.")


def go_to(new_region: str | None, new_city: str | None = None) -> None:
    st.query_params.clear()
    if new_region:
        st.query_params["region"] = new_region
    if new_city:
        st.query_params["city"] = new_city
    st.rerun()


with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
    view = st.segmented_control("View", list(VIEWS), default="Churn", key="region-view",
                                label_visibility="collapsed") or "Churn"
    options = [None] + sorted(states, key=lambda k: names[k])
    picked = st.selectbox("Region", options, index=options.index(region), label_visibility="collapsed",
                          format_func=lambda k: names[k] if k else "All of Germany", width=230)
    if picked != region:
        go_to(picked)
rate_label, rate, amount_label, amount_key, money = VIEWS[view]


def show_amount(v: float) -> str:
    return ui.eur(v, decimals=0) if money else f"{v:,.0f}"


def show_rate(v: float) -> str:
    return ui.eur(v, decimals=0) if view == "Opportunity" else f"{v * 100:.1f} %"


def region_map() -> go.Figure:
    coloured = [k for k in names if k in states and region in (None, k)]  # zoomed in: neighbours turn grey
    grey = [k for k in names if k not in coloured]
    rates = [rate(r) for r in states.values()]
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.id", locations=grey, z=[0] * len(grey), showscale=False,
        colorscale=[[0, "#EDF1F7"], [1, "#EDF1F7"]], marker_line_color="#FFFFFF", marker_line_width=1,
        text=[names[k] + ("<br>Click to look closer" if k in states else "<br>No customers in the data") for k in grey],
        hovertemplate="%{text}<extra></extra>"))
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.id", locations=coloured, z=[rate(states[k]) for k in coloured],
        zmin=min(rates), zmax=max(rates), colorscale=[[0, "#D6E4F7"], [0.5, "#6E9BD6"], [1, "#002D67"]],
        marker_line_color=["#FFE500" if k == region else "#FFFFFF" for k in coloured],
        marker_line_width=[3 if k == region else 1 for k in coloured],
        customdata=[[names[k], show_rate(rate(states[k])), states[k]["customers"]] for k in coloured],
        hovertemplate="<b>%{customdata[0]}</b><br>" + rate_label + ": %{customdata[1]}<br>"
                      "%{customdata[2]} customers<extra></extra>",
        colorbar=dict(title=dict(text=rate_label, side="top"), orientation="h", x=0, xanchor="left", y=0,
                      yanchor="top", len=0.45, thickness=10, outlinewidth=0,
                      tickformat=",.0f" if view == "Opportunity" else ".0%"),
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))))
    places = list(cities)
    largest = max([cities[n][amount_key] for n in places] + [1e-9])
    fig.add_trace(go.Scattergeo(
        lat=[cities[n]["latitude"] for n in places], lon=[cities[n]["longitude"] for n in places],
        text=[n if region and n not in CROWDED and (cities[n]["state_code"] == region or n == "Mainz") else ""
              for n in places],
        mode="markers+text" if region else "markers", textposition=[LABEL_AT.get(n, "top center") for n in places],
        textfont=dict(family="Plus Jakarta Sans, sans-serif", size=12, color=theme.COLORS["ink"]),
        customdata=[[n, show_amount(cities[n][amount_key]), cities[n]["customers"]] for n in places],
        hovertemplate="<b>%{customdata[0]}</b><br>" + amount_label + ": %{customdata[1]}<br>"
                      "%{customdata[2]} customers<extra></extra>",
        marker=dict(size=[max(cities[n][amount_key], 0) for n in places], sizemode="area", sizemin=4,
                    sizeref=2 * largest / (24 if region else 26) ** 2, opacity=0.9,
                    color=["#FFE500" if region in (None, cities[n]["state_code"]) and city in (None, n) else "#FFF3A0"
                           for n in places],
                    line=dict(color="#002D67", width=[2.4 if n == city else 1.2 for n in places])),
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=0.9))))
    if region:
        x0, x1, y0, y1 = bounds(geo, region)
        pad_x, pad_y = max((x1 - x0) * 0.18, 0.35), max((y1 - y0) * 0.12, 0.25)
        fig.update_geos(lonaxis_range=[x0 - pad_x, x1 + pad_x], lataxis_range=[y0 - pad_y, y1 + pad_y])
    else:
        fig.update_geos(fitbounds="locations")
    fig.update_geos(visible=False, projection_type="mercator", bgcolor="rgba(0,0,0,0)")
    fig.update_layout(**theme.plotly_layout(height=580, margin=dict(l=0, r=0, t=4, b=64)),
                      clickmode="event+select", dragmode=False, showlegend=False)
    return fig


left, right = st.columns([1.35, 1], gap="medium")
with left, st.container(key="card-map"):
    # a new key per region and city starts the chart without Plotly's own selection
    event = st.plotly_chart(region_map(), theme=None, on_select="rerun", selection_mode="points",
                            key=f"region-map-{region}-{city}",
                            config={"displayModeBar": False, "topojsonURL": "/app/static/topojson/"})
    points = event.selection.points if event and event.selection else []
    if points:
        hit = points[0]
        if hit.get("location") in states and hit["location"] != region:
            go_to(hit["location"])
        clicked = list(cities)[hit["point_index"]] if hit.get("curve_number") == 2 else None
        if clicked and clicked != city:
            go_to(cities[clicked]["state_code"], clicked)

with right:
    here = states[region] if region else total
    with st.container(horizontal=True, vertical_alignment="center"):
        ui.html_block(f'<div class="lt-section"><span class="lt-section__dot" style="background: var(--lt-primary);">'
                      f'</span><h2 class="lt-section__title">{ui.esc(names[region] if region else "All of Germany")}'
                      f'</h2><span class="lt-section__count">{here["customers"]:,} customers</span></div>')
        if region:
            st.space("stretch")
            if st.button("All of Germany", icon=":material/zoom_out_map:", key="region-reset"):
                go_to(None)
    share = here[amount_key] / total[amount_key] * 100 if total[amount_key] else 0
    ui.html_block(
        '<div class="lt-tiles lt-tiles--two">'
        + ui.tile("shield" if money else "inbox", ui.esc(amount_label), ui.esc(show_amount(here[amount_key])),
                  f"{share:.0f} % of the total" if region else "all regions", "var(--lt-brand)")
        + ui.tile("users", ui.esc(rate_label), ui.esc(show_rate(rate(here))),
                  f"all regions: {ui.esc(show_rate(rate(total)))}" if region else f"of {total['customers']:,} customers",
                  "var(--lt-resolve)")
        + '</div>')
    rows = ([(n, c) for n, c in cities.items() if c["state_code"] == region] if region
            else [(names[k], s) for k, s in states.items()])
    rows.sort(key=lambda kv: -kv[1][amount_key])
    longest = max([r[amount_key] for _, r in rows] + [1e-9])
    items = "".join(
        f'<div class="lt-reglist__row{" is-on" if n == city else ""}"><span class="lt-reglist__name">{ui.esc(n)}</span>'
        f'<span class="lt-reglist__bar"><span style="width: {max(r[amount_key], 0) / longest * 100:.0f}%;"></span></span>'
        f'<span class="lt-reglist__value">{ui.esc(show_amount(r[amount_key]))}</span>'
        f'<span class="lt-reglist__note">{ui.esc(rate_label)}: {ui.esc(show_rate(rate(r)))} · '
        f'{r["customers"]} customers{" · small group" if r["customers"] < 30 else ""}</span></div>'
        for n, r in rows)
    ui.html_block(f'<section class="lt-softcard"><div class="lt-stack" style="gap: 0;"><h2 class="lt-section__title" '
                  f'style="font-size: 18px;">{ui.esc(amount_label)} by {"city" if region else "state"}</h2>'
                  f'<span class="lt-caption">{"click a city bubble to see its customers" if region else "click a state on the map to look closer"}'
                  f'</span></div><div class="lt-reglist">{items}</div></section>')

if region:
    index = ui.load(ui.customer_index)
    levels = ui.risk_levels(index)
    inside = [c for c in index if (c.get("city") == city if city
                                   else (cities.get(c.get("city")) or {}).get("state_code") == region)]
    risky = sorted((c for c in inside if (c.get("churn_probability") or 0) >= levels["high"]),
                   key=lambda c: -(c.get("current_clv_eur") or 0))
    where = city or names[region]
    if ui.section(f"Likely to cancel in {where}", len(risky), "var(--lt-resolve)", "region-risk",
                  f"All of {names[region]}" if city else None):
        go_to(region)
    if not risky:
        st.info(f"No customer in {where} is in the top quarter by churn risk.")
    cols = st.columns(3, gap="medium")
    for i, c in enumerate(risky[:3]):
        with cols[i]:
            ui.customer_card(c, ui.load(ui.recommendation, c["customer_id"]), levels, f"region-{c['customer_id']}")

table_rows = ([c for n, c in cities.items() if c["state_code"] == region] if region
              else [s | {"name": names[k]} for k, s in states.items()])
table = pd.DataFrame([{
    "Region": r["name"], "Customers": r["customers"], "Likely to cancel": r["likely_to_cancel"],
    "Share likely to cancel": (r["likely_to_cancel_share"] or 0) * 100, "Value at stake (€)": r["clv_at_stake_eur"],
    "Open service issues": r["service_issues"], "Waiting for review": r["pending_approvals"],
    "Expected ΔCLV (€)": r["expected_dclv_eur"],
} for r in sorted(table_rows, key=lambda r: -r["customers"])])
with st.expander(f"All numbers by {'city' if region else 'state'}", icon=":material/table:"):
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Share likely to cancel": st.column_config.NumberColumn(format="%.1f %%"),
        "Value at stake (€)": st.column_config.NumberColumn(format="euro"),
        "Expected ΔCLV (€)": st.column_config.NumberColumn(format="euro"),
    })
unassigned = by_level["state"]["unassigned_customers"]
st.caption(f"Likely to cancel = the top quarter of all customers by churn risk (≥ {ui.pct(by_level['state']['high_risk_threshold'])}). "
           + (f"{unassigned} customers have a city that is not on the map. " if unassigned else "")
           + "Regions are for reporting only; Lighty never uses them for a recommendation. The data is synthetic and "
             "groups have about 50 customers, so differences of a few percentage points are not meaningful. "
             "Outlines: Natural Earth.")
