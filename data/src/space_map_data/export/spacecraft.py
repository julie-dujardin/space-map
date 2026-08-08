"""Write `v1/spacecraft.json` — the catalogue the travel panel filters routes by.

Always-loaded like `atmospheres.json`: one small file the frontend fetches once
and keeps, because the panel needs every vehicle at once to rank them against a
route.

Two things are derived here rather than in the frontend. Δv comes out of the
rocket equation, so the panel gets a number and the inputs behind it and can
show either. C3 curves named by dataset are read out of the downloaded
launch-performance files and thinned: a hundred digitised points describe the
same curve as eight within a few kilograms, and the eight fit in the payload
budget of a file that loads at boot.
"""

import logging
import time
from pathlib import Path

import orjson

from space_map_data.constants.spacecraft import (
    CATALOGUE,
    SPACECRAFT_SOURCES,
    Spacecraft,
    delta_v_kms,
)
from space_map_data.constants.spacecraft.specs import C3Curve, Measured
from space_map_data.utils.paths import EXPORT_DIR, SOURCES_LAUNCH_PERFORMANCE_DIR

logger = logging.getLogger(__name__)

# Thinning tolerance: a kept curve reproduces every dropped point to within
# this fraction of the payload there. A launcher's payload is quoted to three
# figures at best, so half a percent is below the noise in the source.
_CURVE_TOLERANCE = 0.005


def _load_curve(dataset: str) -> list[tuple[float, float]]:
    path = SOURCES_LAUNCH_PERFORMANCE_DIR / f"{dataset}.csv"
    points: list[tuple[float, float]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        c3, payload_kg = line.split(",")
        points.append((float(c3), float(payload_kg)))
    return points


def _thin(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop points the linear interpolation between their neighbours already
    predicts. Douglas-Peucker on the payload axis, keeping both ends."""
    if len(points) <= 2:
        return points

    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        (c3_lo, kg_lo), (c3_hi, kg_hi) = points[lo], points[hi]
        span = c3_hi - c3_lo
        worst, worst_error = None, 0.0
        for i in range(lo + 1, hi):
            c3, kg = points[i]
            predicted = kg_lo + (kg_hi - kg_lo) * (c3 - c3_lo) / span
            error = abs(predicted - kg) / max(kg, 1.0)
            if error > worst_error:
                worst, worst_error = i, error
        if worst is not None and worst_error > _CURVE_TOLERANCE:
            keep.add(worst)
            stack.extend(((lo, worst), (worst, hi)))
    return [points[i] for i in sorted(keep)]


def _curve_payload(curve: C3Curve) -> dict:
    if curve.points:
        points = list(curve.points)
    else:
        assert curve.dataset is not None  # one or the other, checked in tests
        points = _thin(_load_curve(curve.dataset))
    entry: dict = {
        "points": [[round(c3, 2), round(kg)] for c3, kg in points],
        "source": curve.source,
        # A curve that ends where the vehicle does means "cannot fly this".
        # A truncated one means "nobody published that far", which is a
        # different sentence and a different UI.
        "truncated": curve.truncated,
    }
    if curve.cross_check is not None:
        entry["cross_check"] = curve.cross_check
    return entry


def _measured(measured: Measured | None) -> dict | None:
    if measured is None:
        return None
    return {"value": measured.value, "source": measured.source}


def _entry(craft: Spacecraft) -> dict:
    entry: dict = {
        "id": craft.id,
        "kind": craft.kind,
        "propulsion": craft.propulsion,
        "status": craft.status,
    }
    if craft.qid:
        entry["qid"] = craft.qid
    if craft.name:
        entry["name"] = craft.name
    if craft.power:
        entry["power"] = craft.power

    for key, measured in (
        ("dry_mass_kg", craft.dry_mass_kg),
        ("propellant_mass_kg", craft.propellant_mass_kg),
        ("isp_s", craft.isp_s),
        ("thrust_n", craft.thrust_n),
        ("crew", craft.crew),
        ("endurance_days", craft.endurance_days),
        ("max_entry_speed_kms", craft.max_entry_speed_kms),
        ("accel_m_s2", craft.accel_m_s2),
    ):
        if (value := _measured(measured)) is not None:
            entry[key] = value

    # Derived, and shipped alongside its inputs so the panel can show the
    # working. Absent where an input is: a Δv nobody can check is worse than
    # no Δv at all.
    if (delta_v := delta_v_kms(craft)) is not None:
        entry["delta_v_kms"] = round(delta_v, 3)

    if craft.c3_curve is not None:
        entry["c3_curve"] = _curve_payload(craft.c3_curve)
    if craft.capabilities:
        entry["capabilities"] = sorted(craft.capabilities)
        entry["capability_source"] = craft.capability_source
    if craft.cost is not None:
        entry["cost"] = {
            "usd_millions": craft.cost.usd_millions,
            "year": craft.cost.year,
            "kind": craft.cost.kind,
            "source": craft.cost.source,
        }
    if craft.object_ids:
        entry["object_ids"] = list(craft.object_ids)
    if craft.group_slug:
        entry["group_slug"] = craft.group_slug
    return entry


def build_spacecraft() -> dict:
    """Assemble the catalogue plus the citations its source keys point at."""
    vehicles = [_entry(craft) for craft in CATALOGUE.values()]
    sources = {
        key: {"title": ref.title, "url": ref.url, "note": ref.note}
        for key, ref in SPACECRAFT_SOURCES.items()
    }
    return {"vehicles": vehicles, "sources": sources}


def write_spacecraft(out_dir: Path) -> None:
    t0 = time.monotonic()
    payload = build_spacecraft()
    (out_dir / "spacecraft.json").write_bytes(orjson.dumps(payload))

    with_dv = sum(1 for v in payload["vehicles"] if "delta_v_kms" in v)
    with_curve = sum(1 for v in payload["vehicles"] if "c3_curve" in v)
    logger.info(
        "Wrote spacecraft.json (%d vehicles, %d with a derived Δv, %d with a "
        "C3 curve) in %.1fs",
        len(payload["vehicles"]),
        with_dv,
        with_curve,
        time.monotonic() - t0,
    )
    # The gaps are the interesting part of this file, so they are logged
    # rather than left to be noticed.
    for vehicle in payload["vehicles"]:
        if vehicle["kind"] == "launcher" and "c3_curve" not in vehicle:
            logger.info("%s: no published escape performance", vehicle["id"])
        elif (
            vehicle["kind"] != "launcher"
            and "delta_v_kms" not in vehicle
            # A torch drive has no Δv to be missing.
            and "accel_m_s2" not in vehicle
        ):
            missing = [
                field
                for field in ("dry_mass_kg", "propellant_mass_kg", "isp_s")
                if field not in vehicle
            ]
            if missing:
                logger.info("%s: no Δv, missing %s", vehicle["id"], ", ".join(missing))


def export_spacecraft_only() -> None:
    """`space-map-export --only spacecraft` — additive, no DB needed."""
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_spacecraft(out_dir)
