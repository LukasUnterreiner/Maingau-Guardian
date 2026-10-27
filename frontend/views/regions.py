"""Regions: customers, churn risk, value and workload per state and city, on a map of Germany.

The colour of a state shows a rate, the height of a city's pillar an amount. Click a state to zoom in, click a city to
narrow the customer cards to it. Reporting only: Lighty never uses the region for a recommendation.
"""
import json
import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
import streamlit as st

import theme
import ui
from i18n import lang, tr

STATIC = Path(__file__).resolve().parent.parent / "static"
# view: its name, rate (state colour), amount (city pillar) and whether the amount is money
VIEWS = {
    "Churn": (tr("Churn", "Kündigung"), tr("Likely to cancel", "Kündigungsgefährdet"),
              lambda r: r["likely_to_cancel_share"] or 0, tr("Value at stake", "Gefährdeter Wert"), "clv_at_stake_eur",
              True),
    "Service": (tr("Service", "Service"), tr("With a service issue", "Mit Service-Anliegen"),
                lambda r: r["service_issues"] / r["customers"], tr("Open service issues", "Offene Service-Anliegen"),
                "service_issues", False),
    "Opportunity": (tr("Opportunity", "Chance"), tr("ΔCLV per customer", "ΔCLV pro Kunde"),
                    lambda r: r["expected_dclv_eur"] / r["customers"], tr("Expected ΔCLV", "Erwarteter ΔCLV"),
                    "expected_dclv_eur", True),
    "Workload": (tr("Workload", "Arbeit"), tr("Waiting for review", "Wartet auf Prüfung"),
                 lambda r: r["pending_approvals"] / r["customers"], tr("Decisions to review", "Zu prüfende Entscheidungen"),
                 "pending_approvals", False),
}
CUSTOMERS = tr("customers", "Kunden")
CROWDED = {"Offenbach", "Obertshausen"}  # 5 to 10 km from Frankfurt and Hanau: name on hover only
LABEL_AT = {"Frankfurt": "top left", "Hanau": "top right", "Wiesbaden": "middle left", "Mainz": "bottom left"}
# the map sits on the night blue of the sidebar; on it a higher rate is a lighter blue, and a city is a spark-yellow
# pillar as tall as its amount
LAND, LAND_LINE, EDGE, LABEL = "#0A3270", "#1D4886", "#002657", "#DCE6F5"
SCALE = [[0, "#1F4F9A"], [0.5, "#0069F1"], [1, "#9CCBFF"]]
PILLAR = {"left": (255, 229, 0), "right": (224, 196, 0), "top": (255, 243, 153)}   # spark yellow, lit from the left
GHOST = {"left": (181, 197, 218), "right": (143, 164, 194), "top": (220, 230, 245)}  # a pillar out of focus
MAP_W, MAP_H, PILLAR_W, PILLAR_MAX = 600, 540, 14, 120   # the map in pixels (its width is a guess), pillar sizes
# a click selects a point and Plotly would fade everything else (states turned white): keep every look as it is
KEEP = dict(selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))


def rgba(color: tuple[int, int, int], alpha: float) -> str:
    return f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha})"


def mercator(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def pillar(lon: float, lat: float, height: float, half: float, scale: float) -> dict[str, list[tuple]]:
    """A square pillar seen from the front and a little above: its left face, right face and top, as rings of
    (lon, lat). height and half are pixels, scale is pixels per radian of the Mercator map."""
    def at(dx: float, dy: float) -> tuple[float, float]:   # pixels right of and above the city
        y = mercator(lat) + dy / scale
        return lon + math.degrees(dx / scale), math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)
    d = half * 0.5   # depth of the top
    # clockwise rings: Plotly's map fills the outside of a counter-clockwise ring
    return {"left": [at(-half, 0), at(-half, height), at(0, height - d), at(0, -d)],
            "right": [at(0, -d), at(0, height - d), at(half, height), at(half, 0)],
            "top": [at(-half, height), at(0, height + d), at(half, height), at(0, height - d)]}


@st.cache_resource
def outlines() -> dict:
    """The 16 states (Natural Earth, public domain), ids are ISO 3166-2 codes such as DE-HE."""
    return json.loads((STATIC / "geo" / "de-states.geojson").read_text(encoding="utf-8"))


def bounds(geo: dict, code: str | None) -> tuple[float, float, float, float]:
    """lon and lat range of one state, or of Germany without a code."""
    features = [f for f in geo["features"] if code in (None, f["properties"]["id"])]
    points = [p for f in features
              for polygon in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon"
                              else f["geometry"]["coordinates"])
              for ring in polygon for p in ring]
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

ui.page_head(tr("Regions", "Regionen"), tr("Where customers and value are at risk", "Wo Kunden und Werte gefährdet sind"),
             tr(f"{len(cities)} cities in {len(states)} states. Click a state on the map to look closer.",
                f"{len(cities)} Städte in {len(states)} Bundesländern. Ein Bundesland auf der Karte anklicken, um "
                "genauer hinzusehen."))


def go_to(new_region: str | None, new_city: str | None = None) -> None:
    # only our own two parameters: ?lang= belongs to the language switch
    for name, value in (("region", new_region), ("city", new_city)):
        if value:
            st.query_params[name] = value
        elif name in st.query_params:
            del st.query_params[name]
    st.rerun()


with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
    view = st.segmented_control(tr("View", "Ansicht"), list(VIEWS), format_func=lambda k: VIEWS[k][0], default="Churn",
                                key="region-view", label_visibility="collapsed") or "Churn"
    options = [None] + sorted(states, key=lambda k: names[k])
    picked = st.selectbox("Region", options, index=options.index(region), label_visibility="collapsed",
                          format_func=lambda k: names[k] if k else tr("All of Germany", "Ganz Deutschland"), width=230)
    if picked != region:
        go_to(picked)
_, rate_label, rate, amount_label, amount_key, money = VIEWS[view]


def show_amount(v: float) -> str:
    return ui.eur(v, decimals=0) if money else ui.num(v)


def show_rate(v: float) -> str:
    return ui.eur(v, decimals=0) if view == "Opportunity" else f"{ui.num(v * 100, 1)} %"


rates = [rate(r) for r in states.values()]
low, high = min(rates), max(rates)


def tint(value: float) -> str:
    """The map colour of a rate, for the swatches next to the map."""
    return sample_colorscale(SCALE, [min(max((value - low) / (high - low), 0), 1) if high > low else 0.5])[0]


def ink_on(color: str) -> str:
    """Night blue on a light map colour, white on a dark one."""
    r, g, b = (float(v) for v in color[color.index("(") + 1:-1].split(","))
    return theme.COLORS["night"] if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#FFFFFF"


def region_map() -> go.Figure:
    coloured = [k for k in names if k in states and region in (None, k)]  # zoomed in: neighbours stay dark land
    land = [k for k in names if k not in coloured]
    x0, x1, y0, y1 = bounds(geo, region)
    pad_x, pad_y = (max((x1 - x0) * 0.18, 0.35), max((y1 - y0) * 0.12, 0.25)) if region else (0.25, 0.2)
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.id", locations=land, z=[0] * len(land), showscale=False,
        # zoomed in, the neighbours are faint outlines only: filled, they would show the map's rectangular edge
        colorscale=[[0, "rgba(0, 0, 0, 0)" if region else LAND], [1, "rgba(0, 0, 0, 0)" if region else LAND]],
        marker_line_color="rgba(120, 160, 230, 0.1)" if region else LAND_LINE, marker_line_width=0.8,
        customdata=[["state" if k in states else "", k, names[k]] for k in land],
        text=[tr("Click to look closer", "Anklicken, um genauer hinzusehen") if k in states
              else tr("No customers in the data", "Keine Kunden in den Daten") for k in land],
        hovertemplate="<b>%{customdata[2]}</b><br>%{text}<extra></extra>", **KEEP))
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.id", locations=coloured, z=[rate(states[k]) for k in coloured],
        zmin=low, zmax=high, colorscale=SCALE, showscale=False,
        marker_line_color=["#FFFFFF" if k == region else EDGE for k in coloured],
        marker_line_width=[2 if k == region else 1 for k in coloured],
        customdata=[["state", k, names[k], show_rate(rate(states[k])), show_amount(states[k][amount_key]),
                     ui.num(states[k]["customers"])] for k in coloured],
        hovertemplate="<b>%{customdata[2]}</b><br>" + rate_label + ": <b>%{customdata[3]}</b><br>" + amount_label
                      + ": %{customdata[4]}<br>%{customdata[5]} " + CUSTOMERS + "<extra></extra>", **KEEP))

    # pillars, drawn from north to south so a pillar in front covers the one behind it
    places = list(cities)
    largest = max([cities[n][amount_key] for n in places] + [1e-9])
    scale = min(MAP_W / math.radians(x1 - x0), MAP_H / (mercator(y1) - mercator(y0)))
    focus = {n for n in places if region in (None, cities[n]["state_code"])}

    def dim(n: str) -> bool:
        return n not in focus or (city is not None and n != city)

    tops = {}   # the highest point of each pillar
    for n in sorted(places, key=lambda n: -cities[n]["latitude"]):
        c = cities[n]
        height = max(c[amount_key], 0) / largest * PILLAR_MAX
        faces = pillar(c["longitude"], c["latitude"], height, PILLAR_W / 2, scale)
        tops[n] = faces["top"][1]
        colors, alpha = (GHOST, 0.3 if n not in focus else 0.6) if dim(n) else (PILLAR, 1)
        for face, ring in faces.items():
            fig.add_trace(go.Scattergeo(
                lon=[p[0] for p in ring + ring[:1]], lat=[p[1] for p in ring + ring[:1]], mode="lines",
                fill="toself", fillcolor=rgba(colors[face], alpha), line=dict(color=rgba((0, 38, 87), 0.35), width=0.6),
                hoverinfo="skip"))

    # hover and click answer at a city's foot, in the middle and at the top of its pillar
    customdata = [["city", n, n, show_amount(cities[n][amount_key]), show_rate(rate(cities[n])),
                   ui.num(cities[n]["customers"])] for n in places]
    feet = [(cities[n]["longitude"], cities[n]["latitude"]) for n in places]
    middles = [(lon, (lat + tops[n][1]) / 2) for n, (lon, lat) in zip(places, feet)]
    targets = feet + middles + [tops[n] for n in places]
    fig.add_trace(go.Scattergeo(
        lon=[p[0] for p in targets], lat=[p[1] for p in targets], mode="markers", customdata=customdata * 3,
        hovertemplate="<b>%{customdata[2]}</b><br>" + amount_label + ": <b>%{customdata[3]}</b><br>" + rate_label
                      + ": %{customdata[4]}<br>%{customdata[5]} " + CUSTOMERS + "<extra></extra>",
        marker=dict(size=18, line_width=0, color="rgba(0, 0, 0, 0)"), **KEEP))
    # the city itself: a white dot at the pillar's foot, the chosen city with a spark-yellow ring
    # Mainz is across the river from Wiesbaden, so it is named on the map of Hessen too
    labels = [n if n not in CROWDED and region in (cities[n]["state_code"], "DE-HE" if n == "Mainz" else "") else ""
              for n in places]
    fig.add_trace(go.Scattergeo(
        lon=[cities[n]["longitude"] for n in places], lat=[cities[n]["latitude"] for n in places],
        mode="markers+text" if region else "markers", hoverinfo="skip",
        text=labels, textposition=[LABEL_AT.get(n, "bottom center") for n in places],
        textfont=dict(family="Plus Jakarta Sans, sans-serif", size=12, color=LABEL),
        marker=dict(size=[12 if n == city else 7 for n in places],
                    color=[rgba((255, 255, 255), 0.4 if n not in focus else 1) for n in places],
                    line=dict(color=["#FFE500" if n == city else theme.COLORS["primary"] for n in places],
                              width=[3 if n == city else 1.5 for n in places])),
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1), textfont=dict(color=LABEL))))

    fig.update_geos(visible=False, showframe=False, projection_type="mercator", bgcolor="rgba(0,0,0,0)",
                    lonaxis_range=[x0, x1], lataxis_range=[y0, y1])
    fig.update_layout(**theme.plotly_layout(
        height=540, margin=dict(l=0, r=0, t=0, b=0),
        hoverlabel=dict(bgcolor="#0A3270", bordercolor="#3A6AB0",
                        font=dict(family="Plus Jakarta Sans, sans-serif", size=13, color="#FFFFFF"))),
        # a city answers only close to its pillar, so a click next to it still picks the state
        clickmode="event+select", dragmode=False, showlegend=False, hoverdistance=8,
        separators=",." if lang() == "de" else ".,")
    return fig


def map_key() -> str:
    """Under the map: the colour range with High / Medium / Low, the highest and the lowest, and what pillar and dot
    mean."""
    group = ([(n, c) for n, c in cities.items() if c["state_code"] == region] if region
             else [(names[k], s) for k, s in states.items()])
    ranked = sorted(group, key=lambda kv: rate(kv[1]))
    extremes = ""
    if len(ranked) > 1:
        def extreme(icon: str, name: str, r: dict, label: str) -> str:
            return (f'<div class="lt-mapkey__extreme"><span class="lt-mapkey__arrow" '
                    f'style="background: {tint(rate(r))}; color: {ink_on(tint(rate(r)))};">'
                    f'{ui.svg(icon, 2.4)}</span><span class="lt-mapkey__who"><span class="lt-mapkey__small">{label}</span>'
                    f'<span class="lt-mapkey__name">{ui.esc(name)}</span></span>'
                    f'<span class="lt-mapkey__value">{ui.esc(show_rate(rate(r)))}</span></div>')
        extremes = ('<div class="lt-mapkey__block"><span class="lt-mapkey__title">'
                    + (tr("Highest and lowest city", "Höchste und niedrigste Stadt") if region
                       else tr("Highest and lowest state", "Höchstes und niedrigstes Bundesland"))
                    + '</span><div class="lt-mapkey__extremes">'
                    + extreme("up", *ranked[-1], tr("Highest", "Höchste"))
                    + extreme("down", *ranked[0], tr("Lowest", "Niedrigste")) + '</div></div>')
    return (
        '<div class="lt-mapkey">'
        f'<div class="lt-mapkey__block"><span class="lt-mapkey__title">{ui.esc(rate_label)} · '
        f'{tr("colour of a state", "Farbe eines Bundeslands")}</span>'
        '<span class="lt-mapkey__ramp"></span><div class="lt-mapkey__ticks">'
        f'<span>{tr("High", "Hoch")} · {ui.esc(show_rate(high))}</span><span>{tr("Medium", "Mittel")}</span>'
        f'<span>{tr("Low", "Niedrig")} · {ui.esc(show_rate(low))}</span></div></div>'
        + extremes
        + '<div class="lt-mapkey__legend">'
        f'<span><span class="lt-mapkey__pillar"></span>{tr("Pillar", "Säule")}: {ui.esc(amount_label)} '
        f'{tr("per city", "pro Stadt")}</span>'
        f'<span><span class="lt-mapkey__dot"></span>'
        f'{tr("City · click it to see its customers", "Stadt · anklicken, um ihre Kunden zu sehen")}</span></div></div>')


left, right = st.columns([1.35, 1], gap="medium")
with left, st.container(key="card-map"):
    # a new key per region and city starts the chart without Plotly's own selection
    event = st.plotly_chart(region_map(), theme=None, on_select="rerun", selection_mode="points",
                            key=f"region-map-{region}-{city}",
                            config={"displayModeBar": False, "topojsonURL": "/app/static/topojson/"})
    ui.html_block(map_key())
    points = event.selection.points if event and event.selection else []
    kind, key = ((points[0].get("customdata") or []) + [None, None])[:2] if points else (None, None)
    if kind == "state" and key in states and key != region:
        go_to(key)
    if kind == "city" and key in cities and key != city:
        go_to(cities[key]["state_code"], key)

with right:
    here = states[region] if region else total
    with st.container(horizontal=True, vertical_alignment="center"):
        ui.html_block(f'<div class="lt-section"><span class="lt-section__dot" style="background: var(--lt-primary);">'
                      f'</span><h2 class="lt-section__title">'
                      f'{ui.esc(names[region] if region else tr("All of Germany", "Ganz Deutschland"))}'
                      f'</h2><span class="lt-section__count">{ui.num(here["customers"])} {CUSTOMERS}</span></div>')
        if region:
            st.space("stretch")
            if st.button(tr("All of Germany", "Ganz Deutschland"), icon=":material/zoom_out_map:", key="region-reset"):
                go_to(None)
    share = here[amount_key] / total[amount_key] * 100 if total[amount_key] else 0
    ui.html_block(
        '<div class="lt-tiles lt-tiles--two">'
        + ui.tile("shield" if money else "inbox", ui.esc(amount_label), ui.esc(show_amount(here[amount_key])),
                  tr(f"{share:.0f} % of the total", f"{share:.0f} % der Summe") if region
                  else tr("all regions", "alle Regionen"), "var(--lt-brand)")
        + ui.tile("users", ui.esc(rate_label), ui.esc(show_rate(rate(here))),
                  tr(f"all regions: {ui.esc(show_rate(rate(total)))}", f"alle Regionen: {ui.esc(show_rate(rate(total)))}")
                  if region else tr(f"of {ui.num(total['customers'])} customers",
                                    f"von {ui.num(total['customers'])} Kunden"),
                  "var(--lt-resolve)")
        + '</div>')
    rows = ([(n, c) for n, c in cities.items() if c["state_code"] == region] if region
            else [(names[k], s) for k, s in states.items()])
    rows.sort(key=lambda kv: -kv[1][amount_key])
    longest = max([r[amount_key] for _, r in rows] + [1e-9])
    items = "".join(
        f'<div class="lt-reglist__row{" is-on" if n == city else ""}"><span class="lt-reglist__name">'
        f'<span class="lt-reglist__swatch" style="background: {tint(rate(r))};"></span>{ui.esc(n)}</span>'
        f'<span class="lt-reglist__bar"><span style="width: {max(r[amount_key], 0) / longest * 100:.0f}%;"></span></span>'
        f'<span class="lt-reglist__value">{ui.esc(show_amount(r[amount_key]))}</span>'
        f'<span class="lt-reglist__note">{ui.esc(rate_label)}: {ui.esc(show_rate(rate(r)))} · '
        f'{r["customers"]} {CUSTOMERS}{tr(" · small group", " · kleine Gruppe") if r["customers"] < 30 else ""}</span></div>'
        for n, r in rows)
    by = tr("by city", "nach Stadt") if region else tr("by state", "nach Bundesland")
    hint = tr("click a city on the map to see its customers", "eine Stadt auf der Karte anklicken, um ihre Kunden zu sehen") \
        if region else tr("click a state on the map to look closer",
                          "ein Bundesland auf der Karte anklicken, um genauer hinzusehen")
    ui.html_block(f'<section class="lt-softcard"><div class="lt-stack" style="gap: 0;"><h2 class="lt-section__title" '
                  f'style="font-size: 18px;">{ui.esc(amount_label)} {by}</h2>'
                  f'<span class="lt-caption">{hint}</span></div><div class="lt-reglist">{items}</div></section>')

if region:
    index = ui.load(ui.customer_index)
    levels = ui.risk_levels(index)
    inside = [c for c in index if (c.get("city") == city if city
                                   else (cities.get(c.get("city")) or {}).get("state_code") == region)]
    risky = sorted((c for c in inside if (c.get("churn_probability") or 0) >= levels["high"]),
                   key=lambda c: -(c.get("current_clv_eur") or 0))
    where = city or names[region]
    if ui.section(tr(f"Likely to cancel in {where}", f"Kündigungsgefährdet in {where}"), len(risky), "var(--lt-resolve)",
                  "region-risk", tr(f"All of {names[region]}", f"Ganz {names[region]}") if city else None):
        go_to(region)
    if not risky:
        st.info(tr(f"No customer in {where} is in the top quarter by churn risk.",
                   f"Kein Kunde in {where} gehört zum obersten Viertel nach Kündigungsrisiko."))
    cols = st.columns(3, gap="medium")
    for i, c in enumerate(risky[:3]):
        with cols[i]:
            ui.customer_card(c, ui.load(ui.recommendation, c["customer_id"]), levels, f"region-{c['customer_id']}")

table_rows = ([c for n, c in cities.items() if c["state_code"] == region] if region
              else [s | {"name": names[k]} for k, s in states.items()])
SHARE, AT_STAKE, DCLV = tr("Share likely to cancel", "Anteil kündigungsgefährdet"), \
    tr("Value at stake (€)", "Gefährdeter Wert (€)"), tr("Expected ΔCLV (€)", "Erwarteter ΔCLV (€)")
table = pd.DataFrame([{
    "Region": r["name"], tr("Customers", "Kunden"): r["customers"],
    tr("Likely to cancel", "Kündigungsgefährdet"): r["likely_to_cancel"], SHARE: (r["likely_to_cancel_share"] or 0) * 100,
    AT_STAKE: r["clv_at_stake_eur"], tr("Open service issues", "Offene Service-Anliegen"): r["service_issues"],
    tr("Waiting for review", "Wartet auf Prüfung"): r["pending_approvals"], DCLV: r["expected_dclv_eur"],
} for r in sorted(table_rows, key=lambda r: -r["customers"])])
with st.expander(tr("All numbers ", "Alle Zahlen ") + by, icon=":material/table:"):
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        SHARE: st.column_config.NumberColumn(format="%.1f %%"),
        AT_STAKE: st.column_config.NumberColumn(format="euro"),
        DCLV: st.column_config.NumberColumn(format="euro"),
    })
unassigned = by_level["state"]["unassigned_customers"]
threshold = ui.pct(by_level["state"]["high_risk_threshold"])
st.caption(tr(f"Likely to cancel = the top quarter of all customers by churn risk (≥ {threshold}). "
              + (f"{unassigned} customers have a city that is not on the map. " if unassigned else "")
              + "Regions are for reporting only; Lighty never uses them for a recommendation. The data is synthetic and "
                "groups have about 50 customers, so differences of a few percentage points are not meaningful. "
                "Outlines: Natural Earth.",
              f"Kündigungsgefährdet = das oberste Viertel aller Kunden nach Kündigungsrisiko (≥ {threshold}). "
              + (f"{unassigned} Kunden haben eine Stadt, die nicht auf der Karte ist. " if unassigned else "")
              + "Regionen dienen nur der Auswertung; Lighty nutzt sie nie für eine Empfehlung. Die Daten sind synthetisch "
                "und die Gruppen haben etwa 50 Kunden, daher sind Unterschiede von wenigen Prozentpunkten nicht "
                "aussagekräftig. Umrisse: Natural Earth."))
