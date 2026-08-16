"""Fill ``scale_meters`` into model manifests from Wikidata size claims.

The frontend normalises every GLB to unit-radius and sizes it off the body's
scene radius, so it needs the real length of each model's longest dimension.
This backfills that from Wikidata physical-size claims (length / width /
height / diameter / wingspan), choosing the largest value — the longest
extent, matching how the mesh's bounding box is normalised. Rejected claims
are recorded in a comment for manual review; entries with no usable claim
get a ``null`` slot and a TODO.

QID per entry: the manifest's own ``wikidata_qid`` when present, else resolved
through its missions to a DB Object and that object's ``wikidata_qid``.

Run from data/:

    uv run python scripts/fill_model_scale_meters.py            # dry-run report
    uv run python scripts/fill_model_scale_meters.py --apply     # rewrite manifests
    uv run python scripts/fill_model_scale_meters.py --apply --slug cassini
"""

import argparse
import logging
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache, active_statements
from space_map_data.export.objects.wikidata_claims import _parse_quantity
from space_map_data.ingest.providers.models import config
from space_map_data.ingest.providers.models.metadata import resolve_mission_object_id
from space_map_data.models.object.main import Object
from space_map_data.utils.db import get_session, session_scope

log = logging.getLogger(__name__)

# Length-like properties, with the human label used in the review comment.
# Order is cosmetic (comment ordering); the chosen value is always the max.
SIZE_PROPS: list[tuple[str, str]] = [
    ("P2043", "length"),
    ("P2049", "width"),
    ("P2048", "height"),
    ("P2386", "diameter"),
    ("P2050", "wingspan"),
]

# Hand-researched longest dimension (metres) for shipping models whose Wikidata
# entry has no usable size claim. Each value is the longest extent a typical 3D
# model depicts (deployed arrays / dishes / structural booms). For spin or
# field missions whose longest feature is a thin wire/dipole boom that models
# omit, the solid-body span is used instead (noted). Values sourced from
# NASA/ESA/eoPortal/Gunter's; (slug -> (metres, "what it is")).
_MANUAL_SCALES: dict[str, tuple[float, str]] = {
    "advanced-composition-explorer": (8.3, "solar-array/boom span"),
    "apollo-soyuz": (21.5, "docked Apollo+DM+Soyuz stack length"),
    "aqua": (16.7, "deployed length, solar array out"),
    "aquarius": (4.85, "overall length (fixed arrays)"),
    "atlas-6-friendship-7": (3.3, "Mercury capsule length incl. antenna"),
    "atlas-7-aurora-7": (3.3, "Mercury capsule length incl. antenna"),
    "atlas-9-faith-7": (3.3, "Mercury capsule length incl. antenna"),
    "aura": (17.03, "deployed length, solar array out"),
    "clementine": (1.88, "octagonal body height"),
    "communication-and-navigation-outage-forecast-system-cnofs": (
        3.4,
        "body length (20 m VEFI wire booms omitted)",
    ),
    "cubesat-icecube": (0.3, "3U body long axis"),
    "cubesat-mirata": (0.34, "3U body long axis"),
    "curiosity-rover-msl": (3.0, "rover body length"),
    "cyclone-global-navigation-satellite-system-cygnss": (
        1.67,
        "deployed solar-array span",
    ),
    "deep-space-1": (11.75, "solar-array span"),
    "deep-space-climate-observatory-dscovr-triana": (4.0, "solar-array span"),
    "earth-observing-1-eo-1": (5.25, "deployed solar wing"),
    "europa-clipper": (30.5, "solar-array span"),
    "far-ultraviolet-spectroscopic-explorer": (7.6, "length with baffle deployed"),
    "fermi-gamma-ray-large-area-space-telescope": (
        2.8,
        "stowed body (deployed array span unverified)",
    ),
    "firefly": (0.34, "3U body long axis (3 m GG boom omitted)"),
    "global-precipitation-measurement": (13.41, "width, solar arrays deployed"),
    "high-energy-transient-explorer": (1.0, "body long axis"),
    "hinode-solar-b": (10.0, "solar-array span"),
    "ice-clouds-and-land-elevation-satellite-icesat": (3.2, "solar wing (per-wing)"),
    "ingenuity-mars-helicopter": (1.2, "rotor span"),
    "jason-1": (9.8, "deployed span (Proteus bus; low confidence)"),
    "landsat-1-2-and-3": (4.0, "solar-paddle span"),
    "landsat-4-and-5": (4.3, "body height"),
    "landsat-8": (9.0, "deployed solar array"),
    "magellan": (9.2, "width, solar panels extended"),
    "magnetospheric-multiscale-mms": (3.5, "octagonal body span (wire booms omitted)"),
    "mars-global-surveyor": (10.0, "solar-array span"),
    "mars-odyssey": (6.0, "GRS boom (solar span 5.7 m)"),
    "mars-reconnaissance-orbiter-mro": (13.6, "solar-array span"),
    "messenger": (6.0, "solar-panel span"),
    "near-shoemaker": (2.75, "body length"),
    "new-horizons": (2.74, "body long edge"),
    "ocean-surface-topography-mission-ostm-jason-2": (3.7, "body length"),
    "polar": (2.8, "body diameter (wire booms omitted)"),
    "quick-scatterometer-quikscat": (2.2, "bus length (array span unverified)"),
    "radar-satellite-1-radarsat-1": (15.0, "deployed SAR antenna"),
    "satellite-for-scientific-applications-sac-c": (2.4, "body length"),
    "seastar": (4.3, "deployed length"),
    "solar-dynamics-observatory": (6.25, "solar-array span"),
    "solar-radiation-and-climate-experiment-sorce": (3.39, "width, arrays deployed"),
    "space-systems-loral-ssl-1300": (31.4, "solar-array span (representative)"),
    "spartan-201": (3.1, "instrument-cylinder length"),
    "stereo": (8.7, "deployed envelope (booms); bus ~6.5 m"),
    "submillimeter-wave-astronomy-satellite-swas": (1.63, "body length"),
    "suomi-national-polar-orbiting-partnership-suomi-npp": (
        8.0,
        "deployed solar array",
    ),
    "suzaku": (6.5, "length, optical bench deployed"),
    "swift": (5.6, "solar-array span"),
    "terra": (9.0, "deployed solar array"),
    "topex-poseidon": (11.5, "deployed span"),
    "transiting-exoplanet-survey-satellite-tess": (3.7, "solar-array span"),
    "tropical-rainfall-measuring-mission-trmm": (14.6, "deployed span"),
    "ulysses": (7.5, "axial boom (72 m wire dipole omitted)"),
    "van-allen-probes": (8.1, "solid-body span (101 m wire booms omitted)"),
    "viking-lander": (3.0, "width across legs"),
    "voyager-probe": (13.0, "magnetometer boom"),
    "wind": (2.4, "drum body diameter (wire booms omitted)"),
    "bepi_mcs": (30.0, "launch stack, MTM wings deployed"),
    "bepi_mmo": (1.8, "octagonal body (30 m wire antennas omitted)"),
    "bepi_mpo": (7.5, "deployed solar wing"),
    "bepi_mtm": (30.0, "solar-wing span"),
    "cheops": (1.55, "body height"),
    "double_star": (2.1, "spin-body cylinder diameter"),
    "gaia": (10.2, "deployable sunshield diameter"),
    "huygens": (2.7, "heat-shield diameter"),
    "huygens_in": (2.7, "heat-shield diameter"),
    "huygens_pc": (2.7, "heat-shield diameter"),
    "integral": (16.0, "solar-array span"),
    "iso": (5.3, "overall height"),
    "juice": (27.1, "solar-array span; RIME antenna 16 m"),
    "lisa_pathfinder": (2.9, "height with propulsion module"),
    "mars_express": (12.0, "solar-array span (40 m MARSIS booms omitted)"),
    "proba_2": (0.85, "body long axis (array span unverified)"),
    "proba_3": (1.8, "coronagraph-craft body length"),
    "smart_1": (14.0, "solar-array span"),
    "schiaparelli": (2.4, "aeroshell diameter"),
}

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # match the ingest loader; don't reflow long URLs/notes


def _manifest_paths() -> list[Path]:
    """Every manifest doc the ingest reads, in the same order."""
    paths: list[Path] = []
    if config.MERGED_MANIFEST.exists():
        paths.append(config.MERGED_MANIFEST)
    if config.NASA_MANIFEST.exists():
        paths.append(config.NASA_MANIFEST)
    if config.ESA_DIR.exists():
        for sub in sorted(config.ESA_DIR.iterdir()):
            meta = sub / "metadata.yaml"
            if meta.is_file():
                paths.append(meta)
    return paths


def _build_qid_lookup() -> dict[str, str]:
    """object_id → wikidata_qid for every Object that has a QID."""
    session = get_session()
    rows = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.isnot(None))
        .all()
    )
    return {oid: qid for oid, qid in rows}


def _build_satcat_norad_map() -> dict[int, str]:
    """satcat NORAD number → object_id, for consolidated-onto-probe lookups."""
    session = get_session()
    rows = (
        session.query(Object.satcat_norad_cat_id, Object.id)
        .filter(Object.satcat_norad_cat_id.isnot(None))
        .all()
    )
    return {norad: oid for norad, oid in rows}


def _entry_qid(
    entry: dict,
    qid_by_object: dict[str, str],
    satcat_norad: dict[int, str],
) -> str | None:
    """Manifest QID if set, else the first QID reachable through a mission."""
    qid = entry.get("wikidata_qid")
    if qid:
        return str(qid)
    for mission in entry.get("missions") or []:
        oid = resolve_mission_object_id(mission, satcat_norad)
        if oid and (resolved := qid_by_object.get(oid)):
            return resolved
    return None


def _claim_metres(
    claims: dict, prop: str, qid: str, units: UnitConverter
) -> float | None:
    """Largest value of ``prop`` (in metres) across its active statements.

    Multiple statements usually mean stowed-vs-deployed configs; the longest
    extent is what the deployed model depicts, so take the max. Statements in
    an unconvertible/non-length unit are skipped.
    """
    best: float | None = None
    for stmt in active_statements(claims, prop):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if not isinstance(dv, dict):
            continue
        parsed = _parse_quantity(dv)
        if not isinstance(parsed, dict) or "unit" not in parsed:
            continue
        metres = units.convert_to_base(
            parsed["value"], parsed["unit"], expected_type="length"
        )
        if metres is not None and metres > 0 and (best is None or metres > best):
            best = metres
    return best


def _wikidata_scale(
    entry: dict,
    cache: WikidataEntityCache,
    units: UnitConverter,
    qid_by_object: dict[str, str],
    satcat_norad: dict[int, str],
) -> tuple[float | None, str]:
    """Scale + comment from Wikidata claims, or (None, reason) if unavailable."""
    qid = _entry_qid(entry, qid_by_object, satcat_norad)
    if not qid:
        return None, "no Wikidata QID resolved"
    entity = cache.get_entity(qid)
    if not entity:
        return None, f"{qid}: no Wikidata entity on disk"

    found: list[tuple[str, str, float]] = []  # (label, pid, metres)
    for pid, label in SIZE_PROPS:
        metres = _claim_metres(entity["claims"], pid, qid, units)
        if metres is not None:
            found.append((label, pid, metres))
    if not found:
        return None, f"{qid}: no size claims (length/width/height/diameter)"

    chosen = max(found, key=lambda f: f[2])
    parts = [
        f"{label}({pid})={metres:.3g}m"
        + (" [chosen]" if (label, pid, metres) == chosen else "")
        for label, pid, metres in found
    ]
    return round(chosen[2], 3), f"{qid}: " + "; ".join(parts)


def _resolve_scale(
    entry: dict,
    cache: WikidataEntityCache,
    units: UnitConverter,
    qid_by_object: dict[str, str],
    satcat_norad: dict[int, str],
) -> tuple[float | None, str]:
    """Return (scale_meters, review_comment): Wikidata first, then manual table."""
    value, reason = _wikidata_scale(entry, cache, units, qid_by_object, satcat_norad)
    if value is not None:
        return value, reason
    slug = entry.get("slug")
    manual = _MANUAL_SCALES.get(slug) if slug else None
    if manual:
        metres, what = manual
        return float(metres), f"manual: {what}"
    return None, f"TODO {reason}; fill scale_meters by hand"


def _set_scale(entry: CommentedMap, value: float | None, comment: str) -> None:
    """Write scale_meters + its review comment onto a ruamel CommentedMap entry.

    The comment is end-of-line (attached to the key itself) rather than a
    standalone line: a line before the last key round-trips as a trailing
    comment of the *previous* key, which would stack on every rerun. EOL
    comments stay bound to ``scale_meters`` and clear cleanly.
    """
    entry["scale_meters"] = value
    # Drop any comment a prior run attached so reruns don't stack them.
    entry.ca.items.pop("scale_meters", None)
    entry.yaml_add_eol_comment(comment, key="scale_meters")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="rewrite manifests in place"
    )
    parser.add_argument("--slug", help="limit to a single model slug (for testing)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    cache = WikidataEntityCache()
    units = UnitConverter(cache)
    with session_scope():
        qid_by_object = _build_qid_lookup()
        satcat_norad = _build_satcat_norad_map()
    log.info(
        "Loaded %d object QIDs, %d satcat NORAD mappings",
        len(qid_by_object),
        len(satcat_norad),
    )

    n_filled = n_gap = n_total = 0
    gaps: list[str] = []
    for path in _manifest_paths():
        doc = _yaml.load(path.read_text())
        changed = False
        for entry in doc.get("entries") or []:
            slug = entry.get("slug")
            if not slug or (args.slug and slug != args.slug):
                continue
            n_total += 1
            value, comment = _resolve_scale(
                entry, cache, units, qid_by_object, satcat_norad
            )
            _set_scale(entry, value, comment)
            changed = True
            if value is None:
                n_gap += 1
                gaps.append(f"  {slug}: {comment}")
            else:
                n_filled += 1
                log.debug("%s -> %sm  (%s)", slug, value, comment)
        if changed and args.apply:
            with path.open("w") as f:
                _yaml.dump(doc, f)
            log.info("wrote %s", path.relative_to(config.MODELS_DOWNLOAD_DIR.parent))

    log.info(
        "=== %d entries: %d filled from Wikidata, %d gaps ===", n_total, n_filled, n_gap
    )
    if gaps:
        log.info("Gaps needing a manual scale_meters:\n%s", "\n".join(gaps))
    if not args.apply:
        log.info("dry-run only — re-run with --apply to write the manifests")


if __name__ == "__main__":
    main()
