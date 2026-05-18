"""Assign probe_id to every probe in research/probe-events/*.json.

Matches against the SPICE-derived cache at spice/probe_ids.json:
1. By wikidata_qid (when present in both) — prefer earliest inception_mjd entry.
2. By (heuristic-mapped mission, naif_id) — uses NAME_TO_MISSION + naif_id from
   the events JSON.
3. Otherwise mints a new entry under mission="EVENTS-DB" with a synthetic naif_id
   in the -90_000_000..-99_999_999 range so it never collides with SPICE.

Re-runnable: stable keys mean re-runs produce identical assignments. New entries
added to probe_ids.json are written with the same schema as existing entries so
the downstream ingest path is unaffected.
"""

import json
from datetime import date, datetime
from pathlib import Path

DOWNLOADS = Path("/var/home/julie/code/git/personal/space-map-downloads")
PROBE_IDS_PATH = DOWNLOADS / "spice" / "probe_ids.json"
EVENTS_DIR = DOWNLOADS / "research" / "probe-events"

MJD_EPOCH = 31412
DEDUPE_BITS = 12
DEDUPE_MASK = (1 << DEDUPE_BITS) - 1
EVENTS_MISSION = "EVENTS-DB"
SYNTH_NAIF_START = -90_000_001  # decrement for each new entry

# Map event-file probe `name` (or substring) → SPICE mission folder name.
# Only entries that disambiguate match-by-naif lookups when SPICE has the probe
# under a different name. Order matters: first matching prefix wins.
NAME_TO_MISSION = [
    ("Cassini", "CASSINI"),
    ("Huygens", "HUYGENS"),
    ("Galileo", "GLL"),
    ("Voyager 1", "VOYAGER"),
    ("Voyager 2", "VOYAGER"),
    ("Pioneer 10", "PIONEER10"),
    ("Pioneer 11", "PIONEER11"),
    ("New Horizons", "NEWHORIZONS"),
    ("Juno", "JUNO"),
    ("JUICE", "JUICE"),
    ("Europa Clipper", "EUROPACLIPPER"),
    ("BepiColombo", "BEPICOLOMBO"),
    ("Mio", "BEPICOLOMBO"),
    ("MESSENGER", "MESSENGER"),
    ("Magellan", "HORIZONS-SYNTH"),
    ("Akatsuki", "HORIZONS-SYNTH"),
    ("Venus Express", "VENUS-EXPRESS"),
    ("Mars Reconnaissance", "MRO"),
    ("Mars Global Surveyor", "MGS"),
    ("Mars Climate Orbiter", "MCO"),
    ("Mars Polar Lander", "MPL"),
    ("Mars Pathfinder", "HORIZONS-SYNTH"),
    ("Mars Express", "MEX"),
    ("MAVEN", "MAVEN"),
    ("2001 Mars Odyssey", "M01"),
    ("InSight", "INSIGHT"),
    ("Phoenix", "PHOENIX"),
    ("Phobos 2", "PHOBOS88"),
    ("Phobos 1", "PHOBOS88"),
    ("Curiosity", "MSL"),
    ("Perseverance", "MARS2020"),
    ("Ingenuity", "MARS2020"),
    ("Spirit", "MER"),
    ("Opportunity", "MER"),
    ("Mariner 10", "M10"),
    ("Mariner 9", "M9"),
    ("Mariner 2", "M2"),
    ("Pioneer Venus Orbiter", "PIONEER12"),
    ("Pioneer 6", "PIONEER6"),
    ("Pioneer 8", "PIONEER8"),
    ("Helios 1", "HELIOS"),
    ("Helios 2", "HELIOS"),
    ("Ulysses", "ULYSSES"),
    ("Solar Orbiter", "SOLAR-ORBITER"),
    ("Parker Solar Probe", "HORIZONS-SYNTH"),
    ("STEREO-A", "STEREO"),
    ("STEREO-B", "STEREO"),
    ("ACE", "HORIZONS-SYNTH"),
    ("WIND", "HORIZONS-SYNTH"),
    ("SOHO", "HORIZONS-SYNTH"),
    ("DSCOVR", "HORIZONS-SYNTH"),
    ("Aditya-L1", "HORIZONS-SYNTH"),
    ("IMAP", "HORIZONS-SYNTH"),
    ("IKAROS", "HORIZONS-SYNTH"),
    ("Rosetta", "HORIZONS-SYNTH"),
    ("Philae", "HORIZONS-SYNTH"),
    ("NEAR", "NEAR"),
    ("Stardust", "HORIZONS-SYNTH"),
    ("Genesis", "HORIZONS-SYNTH"),
    ("Deep Space 1", "HORIZONS-SYNTH"),
    ("Deep Space 2", "HORIZONS-SYNTH"),
    ("Hayabusa2", "HYB2"),
    ("Hayabusa", "HAYABUSA"),
    ("Dawn", "DAWN"),
    ("DART", "DART"),
    ("LICIACube", "HORIZONS-SYNTH"),
    ("Hera", "HERA"),
    ("Lucy", "LUCY"),
    ("OSIRIS-REx", "ORX"),
    ("OSIRIS-APEX", "ORX"),
    ("Psyche", "PSYCHE"),
    ("Giotto", "GIOTTO"),
    ("CONTOUR", "CONTOUR"),
    ("Deep Impact", "DEEPIMPACT"),
    ("EPOXI", "DEEPIMPACT"),
    ("ICE", "HORIZONS-SYNTH"),
    ("ISEE-3", "HORIZONS-SYNTH"),
    ("Sakigake", "HORIZONS-SYNTH"),
    ("Suisei", "HORIZONS-SYNTH"),
    ("Hiten", "HORIZONS-SYNTH"),
    ("SMART-1", "SMART1"),
    ("Kaguya", "SELENE"),
    ("SELENE", "SELENE"),
    ("Chandrayaan-1", "HORIZONS-SYNTH"),
    ("Chandrayaan-2", "HORIZONS-SYNTH"),
    ("Chandrayaan-3", "HORIZONS-SYNTH"),
    ("LRO", "LRO"),
    ("LCROSS", "HORIZONS-SYNTH"),
    ("LADEE", "LADEE"),
    ("GRAIL-A", "GRAIL"),
    ("GRAIL-B", "GRAIL"),
    ("Gaia", "GAIA"),
    ("Euclid", "EUCLID"),
    ("Spektr-RG", "HORIZONS-SYNTH"),
    ("Spektr-R", "HORIZONS-SYNTH"),
    ("Herschel", "HORIZONS-SYNTH"),
    ("Planck", "HORIZONS-SYNTH"),
    ("JWST", "JWST"),
    ("James Webb", "JWST"),
    ("Tesla Roadster", "HORIZONS-SYNTH"),
    ("CAPSTONE", "HORIZONS-SYNTH"),
    ("Hakuto-R Mission 1", "HORIZONS-SYNTH"),
    ("IM-1", "CLPS"),
    ("IM-2", "CLPS"),
    ("Blue Ghost", "CLPS"),
    ("Peregrine", "CLPS"),
    ("ExoMars Trace Gas Orbiter", "EXOMARS2016"),
    ("Schiaparelli", "EXOMARS2016"),
    ("Tianwen-1", "HORIZONS-SYNTH"),
    ("Tianwen-2", "HORIZONS-SYNTH"),
    ("Zhurong", "HORIZONS-SYNTH"),
    ("Yutu", "HORIZONS-SYNTH"),
    ("Mars Orbiter Mission", "HORIZONS-SYNTH"),
    ("Mangalyaan", "HORIZONS-SYNTH"),
    ("Hope", "HORIZONS-SYNTH"),
    ("Nozomi", "NOZOMI"),
    ("Lunar Orbiter", "LUNARORBITER"),
    ("Spitzer", "SIRTF"),
    ("Apollo 8", "APOLLO"),
    ("Apollo 10", "APOLLO"),
    ("Apollo 11", "APOLLO"),
    ("Apollo 12", "APOLLO"),
    ("Apollo 13", "APOLLO"),
    ("Apollo 14", "APOLLO"),
    ("Apollo 15", "APOLLO"),
    ("Apollo 16", "APOLLO"),
    ("Apollo 17", "APOLLO"),
    ("Viking 1", "VIKING"),
    ("Viking 2", "VIKING"),
    ("Vega 1", "VEGA"),
    ("Vega 2", "VEGA"),
    ("Lunar Prospector", "LPM"),
]


def date_to_mjd(date_str: str) -> int | None:
    """ISO 8601 date string → MJD (integer day)."""
    if not date_str:
        return None
    s = date_str.split("T")[0]
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        try:
            d = datetime.strptime(s[:7], "%Y-%m").date()
        except ValueError:
            try:
                d = datetime.strptime(s[:4], "%Y").date()
            except ValueError:
                return None
    # MJD: days since 1858-11-17.
    return (d - date(1858, 11, 17)).days


def encode(inception_mjd: int, dedupe: int) -> int:
    offset = inception_mjd - MJD_EPOCH
    if offset < 0:
        raise ValueError(f"MJD {inception_mjd} predates epoch")
    return (offset << DEDUPE_BITS) | dedupe


def mission_for(probe_name: str) -> str | None:
    for prefix, mission in NAME_TO_MISSION:
        if prefix in probe_name:
            return mission
    return None


def load_cache() -> dict:
    return json.loads(PROBE_IDS_PATH.read_text())


def build_qid_index(cache: dict) -> dict[str, list[dict]]:
    """QID → list of cache entries (sorted by inception_mjd ascending)."""
    idx: dict[str, list[dict]] = {}
    for key, rec in cache.items():
        qid = rec.get("wikidata_qid")
        if not qid:
            continue
        idx.setdefault(qid, []).append({**rec, "_key": key})
    for qid in idx:
        idx[qid].sort(key=lambda r: (r["inception_mjd"], r["naif_id"]))
    return idx


def build_mission_naif_index(cache: dict) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    for key, rec in cache.items():
        out[(rec["mission"], rec["naif_id"])] = {**rec, "_key": key}
    return out


def main():
    cache = load_cache()
    qid_idx = build_qid_index(cache)
    mn_idx = build_mission_naif_index(cache)

    # Lowest synthetic naif_id already in cache (for stable re-runs).
    existing_synth = [
        rec["naif_id"]
        for rec in cache.values()
        if rec["mission"] == EVENTS_MISSION and rec["naif_id"] <= SYNTH_NAIF_START
    ]
    next_synth = (min(existing_synth) if existing_synth else SYNTH_NAIF_START + 1) - 1

    # Track new dedupe slot usage per inception_mjd (seeded from cache).
    dedupe_used: dict[int, set[int]] = {}
    for rec in cache.values():
        dedupe_used.setdefault(rec["inception_mjd"], set()).add(rec["dedupe"])

    files = sorted(EVENTS_DIR.glob("*.json"))
    stats = {
        "matched_qid": 0,
        "matched_mn": 0,
        "minted": 0,
        "skipped": 0,
        "mint_after_collision": 0,
    }

    # Probe_ids already assigned in this run — used to detect collisions where
    # two events-DB probes would otherwise share an ID due to bad QIDs or NAIF
    # recycling.
    assigned_ids: set[int] = set()

    for f in files:
        d = json.loads(f.read_text())
        changed = False
        for probe in d.get("probes", []):
            qid = probe.get("wikidata_qid")
            naif = probe.get("naif_id")
            name = probe.get("name", "")

            # 1. wikidata_qid match — prefer earliest inception entry.
            match = None
            match_kind = None
            if qid and qid in qid_idx:
                match = qid_idx[qid][0]
                match_kind = "qid"
            # 2. (mission, naif_id) match.
            elif naif is not None:
                mission = mission_for(name)
                if mission and (mission, naif) in mn_idx:
                    match = mn_idx[(mission, naif)]
                    match_kind = "mn"

            if match and match["probe_id"] not in assigned_ids:
                probe["probe_id"] = match["probe_id"]
                assigned_ids.add(match["probe_id"])
                stats[f"matched_{match_kind}"] += 1
                changed = True
                continue
            if match:
                # Match would collide with an already-assigned probe; mint a
                # fresh EVENTS-DB entry instead. Likely cause: wrong wikidata
                # QID in the source file or NAIF-ID recycling (e.g. SPICE -47
                # was Suisei then later Genesis).
                stats["mint_after_collision"] += 1

            # 3. Mint new entry. Use launch_date (or first event date).
            launch = probe.get("launch_date") or _first_event_date(probe)
            mjd = date_to_mjd(launch) if launch else None
            if mjd is None or mjd < MJD_EPOCH:
                stats["skipped"] += 1
                continue

            # Try to find a stable existing mint by (name, launch_date).
            stable_key = _find_stable_mint(cache, name, mjd)
            if stable_key and cache[stable_key]["probe_id"] not in assigned_ids:
                probe["probe_id"] = cache[stable_key]["probe_id"]
                assigned_ids.add(cache[stable_key]["probe_id"])
                changed = True
                continue

            used = dedupe_used.setdefault(mjd, set())
            dedupe = next(i for i in range(1 << DEDUPE_BITS) if i not in used)
            used.add(dedupe)
            probe_id = encode(mjd, dedupe)
            cache_key = f"{EVENTS_MISSION}/{next_synth}"
            new_rec = {
                "dedupe": dedupe,
                "inception_mjd": mjd,
                "mission": EVENTS_MISSION,
                "naif_id": next_synth,
                "probe_id": probe_id,
                "wikidata_qid": qid,
                "source": "events-db",
                "events_name": name,
            }
            cache[cache_key] = new_rec
            mn_idx[(EVENTS_MISSION, next_synth)] = {**new_rec, "_key": cache_key}
            # Don't insert minted entries into qid_idx — we want future QID
            # matches to find the canonical SPICE entry, not our own mints.
            probe["probe_id"] = probe_id
            assigned_ids.add(probe_id)
            stats["minted"] += 1
            changed = True
            next_synth -= 1

        if changed:
            f.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")

    # Stable-sort the cache by key for diff-friendly output.
    sorted_cache = dict(sorted(cache.items()))
    PROBE_IDS_PATH.write_text(json.dumps(sorted_cache, indent=2, sort_keys=True) + "\n")

    print("Probe-event ID assignment complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def _first_event_date(probe: dict) -> str | None:
    for ev in probe.get("events", []):
        if "date" in ev:
            return ev["date"]
    return None


def _find_stable_mint(cache: dict, name: str, mjd: int) -> str | None:
    """Re-find a previously-minted EVENTS-DB entry for the same (name, mjd)."""
    for key, rec in cache.items():
        if rec.get("mission") != EVENTS_MISSION:
            continue
        if rec.get("events_name") == name and rec.get("inception_mjd") == mjd:
            return key
    return None


if __name__ == "__main__":
    main()
