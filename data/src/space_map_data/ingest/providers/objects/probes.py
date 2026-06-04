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

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.models.object import Object, ObjectType, OrbitalSource, Satcat
from space_map_data.export.position.probes.time_grid import PROBE_EXPORT_END_YEAR
from space_map_data.probes.landing_events import probe_ids_with_phases
from space_map_data.probes.probe_id import (
    ProbeIdRecord,
    record_from_entry,
    assign_many,
    et_to_mjd,
    load_registry,
)
from space_map_data.probes.trace import inception_et
from space_map_data.utils.db import get_session
from space_map_data.utils.time import jd_to_et, year_to_jd

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


def _is_instrument_naif(naif: int, all_targets: set[int]) -> bool:
    """SPK-convention instrument NAIFs are `-spacecraft × 1000 - k` for some
    small `k`. MSL's surface kernels expose rover-arm joints -76501..-76620
    as targets alongside the rover body -76; we don't want Object rows for
    those joints. Returns True iff `naif`'s magnitude is `> 1000` and the
    high-order "spacecraft" half is in `all_targets`."""
    if naif >= 0:
        return False
    n = -naif
    if n <= 1000:
        return False
    parent_code = n // 1000
    if n % 1000 == 0:
        return False
    return -parent_code in all_targets


def _collect_probes(missions_dir: Path, landed_missions_dir: Path) -> list[dict]:
    """Walk `missions/*/_index.json` and `landed_missions/*/_index.json` and
    return one record per spacecraft.

    Each record carries `(mission, naif_id, inception_mjd, name_hint?)`.
    `name_hint` (currently emitted by HorizonsSyntheticDownloader as
    `files[].name_horizons`) lets us name synthesized rows after the actual
    spacecraft rather than the umbrella mission folder.

    For probes covered in both buckets (MSL has cruise in missions/ and
    surface in landed_missions/), the union of kernels feeds `inception_et`
    so the inception MJD picks up the earliest real-data start.

    Landed-only probes (Viking landers, future Soviet/Chinese stuff) get
    rows from `landed_missions/` alone — the binary export will emit just
    a trailing METHOD_LANDED record for each chunk they occupy.

    Cross-mission merging: when the registry declares multiple
    `kernel_sources` for a probe (e.g. Cassini lives in both CASSINI/-82
    and HUYGENS/-82), kernels from every declared source contribute to the
    canonical bucket — keyed on the entry's *first* kernel_source. So one
    probe row gets the union of kernels rather than minting parallel rows.
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
                if not hint:
                    continue
                for t in f.get("targets", []):
                    try:
                        name_hints.setdefault((mdir.name, int(t)), hint)
                    except (TypeError, ValueError):
                        logger.warning(
                            "skipping non-int NAIF target %r in %s",
                            t,
                            idx_path,
                        )
            # Any negative NAIF ID is a spacecraft per SPICE convention.
            # Modern commercial missions exceed the legacy -1..-999 range
            # (Blue Ghost 1 -2711, IM-1 -370011, Tianwen-1 -9901491, etc.).
            # Two exclusions:
            #   * Landing-site NAIFs (`-X900` from `spacecraft × 1000 - 900`)
            #     are per-body fixed points the SPK chains through, not probes.
            #   * Instrument NAIFs (`-X * 1000 - k` for small k, when -X is
            #     itself a target) — MSL surface kernels expose rover-arm
            #     joints -76501..-76620 alongside the rover body -76.
            raw_targets = {int(s) for s in idx.get("targets", {})}
            spacecraft_ids = sorted(
                t
                for t in raw_targets
                if t < 0
                and (-t) % 1000 != 900
                and not _is_instrument_naif(t, raw_targets)
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
            }
        )
    # Deterministic dedupe order: (inception, naif_id, mission).
    out.sort(key=lambda r: (r["inception_mjd"], r["naif_id"], r["mission"]))
    return out


class ProbesIngestor:
    BATCH = 500

    def __init__(self, download_dir: Path) -> None:
        self.session = get_session()
        self.missions_dir = download_dir / PROVIDERS.SPICE / "kernels" / "missions"
        self.landed_missions_dir = (
            download_dir / PROVIDERS.SPICE / "kernels" / "landed_missions"
        )
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

    def _events_only_records(
        self, spk_keys: set[tuple[str, int]]
    ) -> list[tuple[dict, ProbeIdRecord]]:
        """Synthesise ingest records for registry entries whose only
        ``kernel_sources`` is ``EVENTS-DB`` and which have at least one
        landed phase in the events JSONs. Skips entries already covered by
        an SPK-walk record (``spk_keys``)."""
        registry = load_registry()
        end_et = jd_to_et(year_to_jd(PROBE_EXPORT_END_YEAR))
        pids_with_phases = probe_ids_with_phases(end_et)
        out: list[tuple[dict, ProbeIdRecord]] = []
        for entry in registry:
            sources = entry["kernel_sources"]
            if not all(s["mission"] == "EVENTS-DB" for s in sources):
                continue
            if int(entry["probe_id"]) not in pids_with_phases:
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
            }
            out.append((record, record_from_entry(entry)))
        return out

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
            [(r["mission"], r["naif_id"], r["inception_mjd"]) for r in records]
        )

        # Events-only probes (Apollo descent stages, Veneras, Pathfinder, …)
        # have registry entries but no SPK kernels, so `_collect_probes`
        # doesn't see them. Add Object rows for any whose `landing_events`
        # yields a resolvable phase; without a row the position writer
        # would skip them at fit time.
        spk_keys = {(r["mission"], r["naif_id"]) for r in records}
        events_records = self._events_only_records(spk_keys)

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
