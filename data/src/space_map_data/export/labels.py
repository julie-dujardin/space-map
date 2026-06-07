"""Write the global per-language label files used for pre-interaction labels.

One ``/v1/labels/{lang}.gz`` is emitted per supported language, listing only
*promoted* bodies — those rendered as individual meshes with labels on first
paint (planets, dwarf planets, moons, stars, barycenters, Lagrange points,
plus the curated extras in :mod:`space_map_data.constants.promoted`, plus
every probe shipped by the high-accuracy probe system).

Format: gzipped UTF-8, one ``{id}\\x1f{name}\\x1f{flags}`` line per object.
``flags`` is a single-character set; currently the only flag is ``m`` for
*minor* (rendered as a collapsed halo by default, expands on hover) — set
for moons whose label fell back to the provisional designation, and for
probes outside the curated :data:`PROMOTED_EXTRA_IDS` list (every probe still
ships in the probe export, but only the flagship ones label on first paint).
The frontend fetches one file at app start (or on locale change) and uses
its keys as the authoritative promoted set.
"""

import csv
import gzip
import logging
from pathlib import Path

from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS, PROMOTED_TYPES
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import ObjectType
from space_map_data.probes.probe_id import load_registry
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

_US = "\x1f"  # ASCII Unit Separator — delimiter between fields

_GEO_KM = 35786.0
_LOW_EARTH_ORBIT_APOGEE_KM = _GEO_KM * 1.2  # ~42 943 km


def _low_earth_orbit_probe_ids() -> set[str]:
    """Probe IDs whose SATCAT row places them in Earth orbit with apogee
    under GEO+20%. Joined via the registry's cospar_id / norad_cat_id.

    Promoting these clutters first paint with retired GEO comsats (GOES,
    EchoStar, …) and decayed LEO sats (NEOWISE, GRACE-1, …) that are either
    redundant with CelesTrak's live SGP4 feed or no longer in any catalog.
    Probes with no SATCAT row, no apogee field, or a non-Earth orbit center
    are NOT filtered — that covers escape missions where SATCAT only recorded
    the parking orbit (e.g. Mars Hope shows ORBIT_CENTER=MA so it survives).

    TODO: drop this heuristic once Earth-sat coverage moves to space-track —
    that catalog ships decayed/graveyard sats with current state vectors, so
    the "is this thing redundant with point-cloud coverage" question becomes
    "is this `obj_id` already a `norad_satcat-*` row" instead of an apogee
    guess. Until then, a few corner cases slip through: SATCAT records the
    *parking* orbit for escape attempts (Artemis-1 cubesats look EA-low even
    when they reached cislunar space) and lacks state vectors for several
    decayed entries (apogee=None ⇒ kept). The authoritative replacement is a
    pass over each SPK for max distance from Earth across its coverage.
    """
    satcat = SOURCES_POSITION_DIR / "celestrak" / "satcat.csv"
    if not satcat.exists():
        return set()
    by_norad: dict[int, tuple[float | None, str]] = {}
    by_cospar: dict[str, tuple[float | None, str]] = {}
    with satcat.open() as f:
        for row in csv.DictReader(f):
            try:
                apogee_km = float(row.get("APOGEE") or "")
            except ValueError:
                apogee_km = None
            orbit_center = (row.get("ORBIT_CENTER") or "").strip()
            cospar = (row.get("OBJECT_ID") or "").strip()
            norad_s = (row.get("NORAD_CAT_ID") or "").strip()
            if norad_s:
                try:
                    by_norad[int(norad_s)] = (apogee_km, orbit_center)
                except ValueError:
                    pass
            if cospar:
                by_cospar[cospar] = (apogee_km, orbit_center)

    out: set[str] = set()
    for entry in load_registry():
        ap_oc = None
        norad = entry.get("norad_cat_id")
        if norad is not None:
            ap_oc = by_norad.get(int(norad))
        if ap_oc is None and entry.get("cospar_id"):
            ap_oc = by_cospar.get(entry["cospar_id"])
        if ap_oc is None:
            continue
        apogee_km, orbit_center = ap_oc
        if (
            orbit_center == "EA"
            and apogee_km is not None
            and apogee_km < _LOW_EARTH_ORBIT_APOGEE_KM
        ):
            out.add(f"probe-{entry['probe_id']}")
    return out


def _is_promoted(
    obj_id: str,
    global_data: dict,
    cheb_covered_ids: set[str],
    probe_ids: set[str],
    rendered_ids: set[str],
) -> bool:
    """A body is promoted if it'd be rendered as an individual mesh on first
    paint. Type/curated/cheb/probe membership is the *intent* check;
    ``rendered_ids`` is the *capability* check — bodies absent from every
    position file can't render in 3D, so promoting them just makes the
    renderer's pending-promotion loop retry an unfindable ``getBody`` every
    frame. Every probe shipped by the probe export gets promoted (curated
    extras label normally; the rest ride the ``m`` minor flag).
    """
    if obj_id not in rendered_ids and obj_id not in cheb_covered_ids:
        return False
    return (
        global_data.get("type") in PROMOTED_TYPES
        or obj_id in PROMOTED_EXTRA_IDS
        or obj_id in cheb_covered_ids
        or obj_id in probe_ids
    )


def _resolve_label(
    obj_id: str, loc: dict | None, glob: dict, probe_ids: set[str]
) -> tuple[str, str]:
    """Return ``(name, flags)`` for one (object, lang) pair.

    Name precedence: localized Wikidata label → DB ``name`` → provisional
    designation → empty string. Flags is ``"m"`` when the chosen name is a
    moon's provisional designation (no real name in either Wikidata or the
    DB), or when the object is a probe outside :data:`PROMOTED_EXTRA_IDS` —
    the frontend renders flagged labels as collapsed halos that expand on
    hover, so e.g. Saturn's ``naif-65289``/``S2020 S48`` and every non-
    flagship probe doesn't crowd the map at first paint.
    """
    loc_name = loc.get("name") if loc else None
    db_name = glob.get("name")
    designation = glob.get("provisional_designation")
    name = loc_name or db_name or designation or ""
    is_minor_moon = (
        glob.get("type") == ObjectType.moon
        and not loc_name
        and (not db_name or db_name == designation)
        and bool(designation)
    )
    is_minor_probe = obj_id in probe_ids and obj_id not in PROMOTED_EXTRA_IDS
    return name, "m" if (is_minor_moon or is_minor_probe) else ""


def write_global_labels(
    out_dir: Path,
    all_objects: ChunkObjectData,
    cheb_covered_ids: set[str],
    probe_ids: set[str],
    rendered_ids: set[str],
) -> None:
    """Write ``/v1/labels/{lang}.gz`` for every supported language.

    Bodies with chebyshev coverage are auto-promoted regardless of type:
    they're rendered as individual meshes by virtue of their precise
    ephemerides, so they always belong in the labels set (catches the DE441
    perturber asteroids that aren't in :data:`PROMOTED_EXTRA_IDS`). Probes
    follow the same rule — every probe in ``probe_ids`` is promoted; the
    ones outside :data:`PROMOTED_EXTRA_IDS` carry the ``m`` minor flag so
    the renderer collapses them to halos by default.

    ``rendered_ids`` is the union of object IDs that ship in any elements
    position file. Bodies present only in object bundles (e.g. orbit-less
    SBDB satellites added for navigation) are excluded — promoting them
    would make the frontend's pending-promotion loop retry an unfindable
    ``getBody`` every frame.
    """
    missing_extras = sorted(PROMOTED_EXTRA_IDS - all_objects.global_data.keys())
    if missing_extras:
        logger.warning(
            "PROMOTED_EXTRA_IDS not found in exported objects (typo or filtered out upstream): %s",
            missing_extras,
        )

    low_orbit_excludes = _low_earth_orbit_probe_ids() - PROMOTED_EXTRA_IDS
    promoted_ids = sorted(
        obj_id
        for obj_id, glob in all_objects.global_data.items()
        if obj_id not in low_orbit_excludes
        and _is_promoted(obj_id, glob, cheb_covered_ids, probe_ids, rendered_ids)
    )
    dropped_low_orbit = sum(
        1 for oid in all_objects.global_data if oid in low_orbit_excludes
    )
    if dropped_low_orbit:
        logger.info(
            "Filtered %d low-apogee Earth-orbit probes from labels "
            "(apogee < %.0f km, ORBIT_CENTER=EA, not in PROMOTED_EXTRA_IDS)",
            dropped_low_orbit,
            _LOW_EARTH_ORBIT_APOGEE_KM,
        )

    labels_dir = out_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        lang_data = all_objects.localized_data.get(lang, {})
        lines = []
        named = 0
        minor = 0
        for obj_id in promoted_ids:
            loc = lang_data.get(obj_id)
            glob = all_objects.global_data.get(obj_id, {})
            name, flags = _resolve_label(obj_id, loc, glob, probe_ids)
            if name:
                named += 1
            if flags:
                minor += 1
            lines.append(f"{obj_id}{_US}{name}{_US}{flags}")
        out_file = labels_dir / f"{lang}.gz"
        out_file.write_bytes(gzip.compress("\n".join(lines).encode()))
        logger.info(
            "Wrote %d/%d labels (%d minor) to %s",
            named,
            len(promoted_ids),
            minor,
            out_file,
        )
