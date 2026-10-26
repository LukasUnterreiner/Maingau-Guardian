"""Regional view: customers, churn risk, value and workload added up per state and per city.

Reporting only. The recommendation engine never sees city or postal code, and nothing here feeds back into it.
The dataset has a city (customer_master.city) but no state, so data/reference/city_regions.csv maps each city to
its state and to a map position. A city missing from that table is counted as "Unassigned", never dropped.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.recommendation_engine import Decision

log = logging.getLogger("lighty")

UNASSIGNED = "unassigned"
HIGH_RISK_QUANTILE = 0.75  # likely to cancel = the top quarter by churn risk, as on the web app's Churn risk page
NOTE = ("Reporting only: the region is never used for a recommendation. The data is synthetic and groups have about "
        "50 customers, so differences of a few percentage points between regions are not meaningful.")


@dataclass(frozen=True)
class Place:
    city: str
    state_code: str
    state_name: str
    latitude: float
    longitude: float


def load_places(path: Path) -> dict[str, Place]:
    if not path.exists():
        log.warning("City table %s not found: every customer is shown as unassigned", path)
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["city"]: Place(r["city"], r["state_code"], r["state_name"], float(r["latitude"]),
                                 float(r["longitude"])) for r in csv.DictReader(fh)}


def high_risk_threshold(churn: Iterable[float]) -> float:
    """Churn risk at the start of the top quarter, on the same rounded values the customer list returns."""
    values = sorted(round(c, 4) for c in churn)
    return values[int(HIGH_RISK_QUANTILE * (len(values) - 1))] if values else 1.0


def _add_up(rows: list[tuple[Decision, str]], threshold: float) -> dict[str, Any]:
    n = len(rows)
    at_risk = [d for d, _ in rows if round(d.state.churn_now, 4) >= threshold]
    return {
        "customers": n,
        "likely_to_cancel": len(at_risk),
        "likely_to_cancel_share": round(len(at_risk) / n, 4) if n else None,
        "avg_churn_probability": round(sum(d.state.churn_now for d, _ in rows) / n, 4) if n else None,
        "clv_eur": round(sum(d.state.clv_now_eur for d, _ in rows), 2),
        "clv_at_stake_eur": round(sum(d.state.clv_now_eur for d in at_risk), 2),
        "service_issues": sum(1 for d, _ in rows if d.state.has_service_issue),
        "open_complaints": sum(1 for d, _ in rows if d.state.open_complaint),
        "cancellations_pending": sum(1 for d, _ in rows if d.state.cancellation_pending),
        "contacts_recommended": sum(1 for d, _ in rows if d.recommended is not None),
        "pending_approvals": sum(1 for _, status in rows if status == "pending_approval"),
        "expected_dclv_eur": round(sum(d.expected_dclv for d, _ in rows), 2),
    }


def regions(portfolio: list[Decision], statuses: dict[str, str], places: dict[str, Place], level: str,
            state: str | None, threshold: float) -> dict[str, Any]:
    """Totals per state (level="state") or per city (level="city"), optionally only inside one state."""
    rows = [(d, statuses.get(d.decision_id, "pending_approval" if d.recommended else "not_required"))
            for d in portfolio]
    groups: dict[str, list[tuple[Decision, str]]] = {}
    unassigned = 0
    for d, status in rows:
        city = d.state.profile.get("city")
        place = places.get(city)
        if place is None:
            unassigned += 1
        if state and (place.state_code if place else UNASSIGNED) != state:
            continue
        key = (place.state_code if place else UNASSIGNED) if level == "state" else (city or UNASSIGNED)
        groups.setdefault(key, []).append((d, status))

    states = {p.state_code: p.state_name for p in places.values()}
    out = []
    for key, members in groups.items():
        if level == "state":
            item = {"id": key, "name": states.get(key, "Unassigned"), "state_code": key if key in states else None}
        else:
            place = places.get(key)
            item = {"id": key, "name": key if key != UNASSIGNED else "Unassigned",
                    "state_code": place.state_code if place else None,
                    "latitude": place.latitude if place else None, "longitude": place.longitude if place else None}
        out.append(item | _add_up(members, threshold))
    out.sort(key=lambda r: (-r["customers"], r["name"]))
    selected = [r for members in groups.values() for r in members]
    return {"level": level, "state": state, "high_risk_threshold": threshold, "regions": out,
            "totals": _add_up(selected, threshold), "unassigned_customers": unassigned, "note": NOTE}
