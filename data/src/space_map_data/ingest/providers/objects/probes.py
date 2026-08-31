"""Ingest spacecraft Object rows from `missions/*/_index.json` and
`landed_missions/*/_index.json`.

Walks every per-mission index file written by `ProbesDownloader` (both the
trajectory and the landed-bucket tree), computes the inception MJD of each
spacecraft NAIF ID's longest contiguous SPK interval across the union of
buckets, and persists one Object row per `(mission, naif_id)` with
`id_type=PROBE`. Landed-only probes (Viking landers, etc.) get rows the
same way as trajectory-only ones — the renderer dispatches between flying
sub-chunks and landed records via the per-chunk binary.

The primary key is `probe-<probe_id>` so the row survives NAIF-ID recycling
(e.g. -76 was Mariner 10 and is MSL today — two separate rows with distinct
probe_ids). `naif_id` is still stored on the row but as an attribute, not
the primary key.

Identity fields (`name`, `cospar_id`, `norad_cat_id`, `wikidata_qid`) come
from the probe registry at `spice/probe_ids.json` — never from MB-by-NAIF,
which would give every recycled-NAIF entry the *current* tenant's identity.
Hand-edit the registry to fill gaps for new entries before they ingest.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select
from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.models.object import Object, ObjectType, OrbitalSource, Satcat
from space_map_data.probes.probe_id import (
    ProbeIdRecord,
    record_from_entry,
    assign_many,
    et_to_mjd,
    is_spacecraft_naif,
    load_registry,
)
from space_map_data.probes.trace import inception_et
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

_SUN_OBJECT_ID = "naif-10"

# Kernels we never want to feed `_coverage()`: they park a destroyed/landed
# probe at fixed coords for decades and would push the longest-coverage
# interval past mission end.
_STATIONARY_PATTERNS = ("_imp_", "_crashsite_")


def _mission_kernels(mission_dir: Path) -> list[Path]:
    return [
        k
        for k in (sorted(mission_dir.glob("*.bsp")) + sorted(mission_dir.glob("*.BSP")))
        if not any(p in k.name for p in _STATIONARY_PATTERNS)
    ]


def _collect_probes(missions_dir: Path, landed_missions_dir: Path) -> list[dict]:
    """One record per spacecraft: `(mission, naif_id, inception_mjd, name_hint?)`.

    `name_hint` (from HorizonsSyntheticDownloader's `files[].name_horizons`)
    names synthesized rows after the actual spacecraft, not the umbrella
    mission folder. Probes covered in both buckets (MSL: cruise in
    `missions/`, surface in `landed_missions/`) feed the union of kernels to
    `inception_et`. Landed-only probes (Viking landers, ...) come from
    `landed_missions/` alone — export emits just a trailing METHOD_LANDED
    record for them. Cross-mission merging: when the registry declares
    multiple `kernel_sources` for a probe (e.g. Cassini in both CASSINI/-82
    and HUYGENS/-82), all declared sources' kernels feed the canonical
    bucket, keyed on the first — one row, not parallel ones.
    """
    registry = load_registry()
    source_to_canonical: dict[tuple[str, int], tuple[str, int]] = {}
    for entry in registry:
        sources = entry["kernel_sources"]
        canonical = (sources[0]["mission"], int(sources[0]["naif_id"]))
        for src in sources:
            source_to_canonical[(src["mission"], int(src["naif_id"]))] = canonical

    per_mission_naifs: dict[tuple[str, int], dict] = {}
    name_hints: dict[tuple[str, int], str] = {}
    cospar_hints: dict[tuple[str, int], str] = {}

    def _ingest_bucket(base: Path) -> None:
        if not base.exists():
            return
        for mdir in sorted(base.iterdir()):
            if not mdir.is_dir():
                continue
            idx_path = mdir / "_index.json"
            if not idx_path.exists():
                continue
            kernels = _mission_kernels(mdir)
            if not kernels:
                continue
            idx = json.loads(idx_path.read_text())
            for f in idx.get("files", []):
                hint = f.get("name_horizons")
                cospar = f.get("cospar")
                if not hint and not cospar:
                    continue
                for t in f.get("targets", []):
                    try:
                        key = (mdir.name, int(t))
                    except TypeError, ValueError:
                        logger.warning(
                            "skipping non-int NAIF target %r in %s",
                            t,
                            idx_path,
                        )
                        continue
                    if hint:
                        name_hints.setdefault(key, hint)
                    if cospar:
                        cospar_hints.setdefault(key, cospar)
            # Negatives are spacecraft per SPICE convention (modern commercial
            # missions exceed -1..-999: Blue Ghost 1 -2711, IM-1 -370011), minus
            # landing-site/instrument sub-NAIFs — see is_spacecraft_naif.
            raw_targets = {int(s) for s in idx.get("targets", {})}
            spacecraft_ids = sorted(
                t for t in raw_targets if is_spacecraft_naif(t, raw_targets)
            )
            if not spacecraft_ids:
                continue
            targets = idx.get("targets", {})
            all_kpaths = [str(k) for k in kernels]
            for naif_id in spacecraft_ids:
                naif_files = targets.get(str(naif_id), [])
                kpaths = (
                    [str(mdir / fn) for fn in naif_files if (mdir / fn).exists()]
                    if naif_files
                    else all_kpaths
                )
                if not kpaths:
                    continue
                bucket_key = source_to_canonical.get(
                    (mdir.name, naif_id), (mdir.name, naif_id)
                )
                rec = per_mission_naifs.setdefault(
                    bucket_key,
                    {
                        "mission": bucket_key[0],
                        "naif_id": bucket_key[1],
                        "kpaths": [],
                    },
                )
                rec["kpaths"].extend(kpaths)

    _ingest_bucket(missions_dir)
    _ingest_bucket(landed_missions_dir)

    out: list[dict] = []
    for (mission, naif_id), rec in per_mission_naifs.items():
        # Dedupe kernel paths (a probe present in both buckets shouldn't
        # double-count its coverage in inception_et).
        kpaths = sorted(set(rec["kpaths"]))
        t0 = inception_et(naif_id, kpaths)
        if t0 is None:
            logger.warning("no coverage for %s/%d", mission, naif_id)
            continue
        out.append(
            {
                "mission": mission,
                "naif_id": naif_id,
                "inception_mjd": et_to_mjd(t0),
                "name_hint": name_hints.get((mission, naif_id)),
                "cospar_hint": cospar_hints.get((mission, naif_id)),
            }
        )
    # Deterministic dedupe order: (inception, naif_id, mission).
    out.sort(key=lambda r: (r["inception_mjd"], r["naif_id"], r["mission"]))
    return out


def _events_only_records(
    spk_keys: set[tuple[str, int]],
) -> list[tuple[dict, ProbeIdRecord]]:
    """Synthesise ingest records for registry entries whose only
    ``kernel_sources`` is ``EVENTS-DB``. Skips entries already covered by
    an SPK-walk record (``spk_keys``).

    Placement is not a condition. Some of these probes do reach the map —
    a landed phase pins them to a surface, an attachment rides them on a
    carrier — and the rest never do, but every one of them is a mission
    the events name and bodies link to, so all of them need a page. The
    export drops the unplaced ones from the labels file instead.
    """
    registry = load_registry()
    out: list[tuple[dict, ProbeIdRecord]] = []
    for entry in registry:
        sources = entry["kernel_sources"]
        if not all(s["mission"] == "EVENTS-DB" for s in sources):
            continue
        mission = sources[0]["mission"]
        naif_id = int(sources[0]["naif_id"])
        if (mission, naif_id) in spk_keys:
            continue
        record = {
            "mission": mission,
            "naif_id": naif_id,
            "inception_mjd": int(entry["inception_mjd"]),
            "name_hint": None,
            "cospar_hint": None,
        }
        out.append((record, record_from_entry(entry)))
    return out


class ProbesIngestor:
    BATCH = 500

    def __init__(self, download_dir: Path) -> None:
        self.session = get_session()
        kernels_dir = download_dir / "sources" / "position" / "spice-kernels"
        self.missions_dir = kernels_dir / "missions"
        self.landed_missions_dir = kernels_dir / "landed-missions"
        # Pre-loaded set of satcat NORADs; consulted in `_build_row` to decide
        # whether to set the satcat FK. Without this guard, probes whose
        # registry NORAD doesn't exist in satcat would trip the FK constraint.
        self.satcat_norads: set[int] = set()

    def _load_satcat_norads(self) -> None:
        self.satcat_norads = {
            n for (n,) in self.session.execute(select(Satcat.NORAD_CAT_ID)).all()
        }

    def _clear(self) -> None:
        """Drop previously-ingested probe rows. Safe: probes live under their
        own orbital_source enum and don't get takeovers from other providers."""
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.spice_probe)
        )
        self.session.commit()

    def _build_row(self, record: dict, rec: ProbeIdRecord) -> dict:
        object_pk = make_object_id(ID_TYPES.PROBE, rec.probe_id)
        # Identity fields come from the registry, not MB. MB is keyed by NAIF
        # only — under NAIF recycling it gives the *current* tenant's name to
        # every entry sharing that NAIF, so M10/-76 ends up labelled MSL etc.
        # The registry's `name` field is the human-curated answer.
        name = (
            rec.name
            or record.get("name_hint")
            or f"{record['mission']}/{record['naif_id']}"
        )
        if rec.name is None and not record.get("name_hint"):
            logger.warning(
                "probe %s has no name in registry — falling back to %s; hand-edit "
                "spice/probe_ids.json to set a name",
                object_pk,
                name,
            )
        norad = rec.norad_cat_id
        satcat_fk = norad if norad is not None and norad in self.satcat_norads else None
        return {
            "id": object_pk,
            "name": name,
            "object_type": ObjectType.spacecraft,
            "naif_id": record["naif_id"],
            "cospar_id": rec.cospar_id,
            "norad_cat_id": norad,
            "probe_id": rec.probe_id,
            # Claim the satcat row when the registry knows the NORAD and the
            # satcat table has a matching row. Joint-launch siblings can both
            # claim the same NORAD (Cassini + Huygens both at 25008); the FK
            # column is non-unique on the probe side and the partial-unique
            # index applies only to `norad_satcat-%` rows.
            "satcat_norad_cat_id": satcat_fk,
            # Parent_id is decoration for probe rows — the frontend reads the
            # actual parent from the position file at render time. Probes
            # always heliocenter; satellite-class objects (HST, ISS) live as
            # `norad_satcat-N` rows in the sat namespace instead.
            "parent_id": _SUN_OBJECT_ID,
            "orbital_source": OrbitalSource.spice_probe,
            "wikidata_qid": rec.wikidata_qid,
            # Probes ride the probes/ zone (chunk binaries) which reads
            # kernels directly, so the elements writer doesn't ship them.
            "has_position": False,
        }

    def run(self) -> None:
        if not self.missions_dir.exists() and not self.landed_missions_dir.exists():
            logger.warning(
                "No probe missions or landed_missions dir at %s — skipping",
                self.missions_dir,
            )
            return
        records = _collect_probes(self.missions_dir, self.landed_missions_dir)
        if not records:
            logger.info("No probes found under %s", self.missions_dir)
            return

        # Pin every (mission, naif_id) to a stable probe_id via the on-disk cache.
        assignments = assign_many(
            [(r["mission"], r["naif_id"], r["inception_mjd"]) for r in records],
            cospars={
                (r["mission"], r["naif_id"]): r.get("cospar_hint") for r in records
            },
        )

        # Events-only probes (Apollo CSMs, Veneras, Magellan, Stardust, …)
        # have registry entries but no SPK kernels, so `_collect_probes`
        # doesn't see them. Without a row the position writer skips the
        # placeable ones at fit time and the rest have no page at all, while
        # bodies still link to them from their event targets.
        spk_keys = {(r["mission"], r["naif_id"]) for r in records}
        events_records = _events_only_records(spk_keys)

        self._clear()
        self._load_satcat_norads()

        rows: list[dict] = []
        for r in tqdm(records, desc="Probes ingest"):
            rec = assignments[(r["mission"], r["naif_id"])]
            rows.append(self._build_row(r, rec))
            if len(rows) >= self.BATCH:
                self.session.execute(insert(Object), rows)
                rows = []
        for r, rec in events_records:
            rows.append(self._build_row(r, rec))
            if len(rows) >= self.BATCH:
                self.session.execute(insert(Object), rows)
                rows = []
        if rows:
            self.session.execute(insert(Object), rows)
        self.session.commit()
        logger.info(
            "Ingested %d probe Objects (%d SPK-driven + %d events-only)",
            len(records) + len(events_records),
            len(records),
            len(events_records),
        )


def ingest(download_dir: Path) -> None:
    ProbesIngestor(download_dir).run()
