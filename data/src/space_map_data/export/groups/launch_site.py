"""GCAT-derived position and pad list for launch-site (``site-``) group pages.

Two catalogues meet here. Membership and the satellite counts come from
CelesTrak SATCAT, whose site codes name whole ranges; the position comes from
GCAT, which names the places inside them. `LaunchSiteSpec.gcat_sites` is the
curated bridge, and every GCAT phase code (a range keeps getting re-chartered
and renamed) resolves through `LaunchSite.ucode` before matching.

A SATCAT range is not one place, so the export does not pretend it is: there
is no range-level coordinate, only the GCAT sites under it, each with its own
point and its own pads. Any single pin for a range would just be one of those
sites picked arbitrarily, and a misleading one — Canaveral's point sits 18 km
from LC39A, Baikonur's 28 km from Gagarin's Start.

Pad launch counts come from the launchlog, deduped by ``launch_tag``: it has
one row per payload, and a rideshare would otherwise make a pad look busier
than it was.

A site or pad carries a ``qid`` only where the curated table names one —
Wikidata has an entity for a few hundred of GCAT's several thousand places,
so most rows legitimately have none.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_SITES,
)
from space_map_data.models.object import LaunchPad, LaunchSite, Launchlog

logger = logging.getLogger(__name__)


def _pad_labels(names: list[str]) -> list[str]:
    """Pad names with the place they sit in trimmed off the tail.

    GCAT trails every pad's name with where it is, which the page holding it
    already says. How many trailing parts that is varies — Canaveral's all end
    ", Cape Canaveral", Baikonur's ", GIK-5, Baykonur, Kazakstan" — so take
    whatever most of the site's pads share rather than assume a depth. Keeping
    only the first part instead would read "PU39" at Baikonur, where GCAT leads
    with the launcher and names the pad second.

    Majority, not unanimity: Baikonur has one oddly punctuated row ("Buran
    runway, GIK-5 Baykonur") that shares no tail with the other 120, and
    requiring agreement would leave the site's name on every row.
    """
    parts = [[piece.strip() for piece in name.split(",")] for name in names]
    shared: tuple[str, ...] = ()
    for depth in range(1, 1 + max((len(p) for p in parts), default=0)):
        counts: Counter[tuple[str, ...]] = Counter(
            # A pad never gives up its whole name, so it stops voting once the
            # tail would consume it.
            tuple(p[len(p) - depth :])
            for p in parts
            if len(p) > depth
        )
        if not counts:
            break
        tail, votes = counts.most_common(1)[0]
        if votes <= len(names) / 2:
            break
        shared = tail
    out = []
    for own in parts:
        strip = (
            shared
            and len(own) > len(shared)
            and tuple(own[len(own) - len(shared) :]) == shared
        )
        out.append(", ".join(own[: len(own) - len(shared)] if strip else own))
    return out


def _certain(code: str | None) -> str | None:
    """Drop GCAT's trailing "?" — the attribution is uncertain, not the code.

    Counting these against the pad GCAT names is better than counting them
    nowhere, which is what an unstripped code amounts to.
    """
    return code.rstrip("?") if code else None


@dataclass
class LaunchSiteStats:
    """Per-site GCAT roll-up consumed by the site- group bundle."""

    # The GCAT sites this range covers, busiest first, each with its own point
    # and its own pads.
    sites: list[dict] = field(default_factory=list)
    # Every pad GCAT lists for the range, including the ones it cannot place.
    pad_count: int = 0
    launch_count: int = 0


def _ucode_index(session: Session) -> tuple[dict[str, str], dict[str, LaunchSite]]:
    """``{site code: ucode}`` and ``{ucode: canonical row}`` over GCAT sites.

    A place has one row per naming phase; the canonical one is the row whose
    own code equals the ucode, falling back to the first located row so a place
    whose canonical row is missing still gets a position.
    """
    ucode_by_code: dict[str, str] = {}
    canonical: dict[str, LaunchSite] = {}
    for row in session.scalars(select(LaunchSite)):
        ucode = row.ucode or row.code
        ucode_by_code[row.code] = ucode
        current = canonical.get(ucode)
        if row.code == ucode:
            canonical[ucode] = row
        elif current is None and row.latitude is not None:
            canonical[ucode] = row
    return ucode_by_code, canonical


def build_launch_site_stats(session: Session) -> dict[str, LaunchSiteStats]:
    """Aggregate GCAT sites/pads into ``{site- group slug: LaunchSiteStats}``."""
    ucode_by_code, canonical = _ucode_index(session)
    if not ucode_by_code:
        logger.warning("No GCAT launch sites in the DB; site- pages get no position")
        return {}

    # Pads keyed by the ucode of the site they hang off, so a pad recorded
    # against an older phase code still lands on the right site.
    pads_by_ucode: dict[str, list[LaunchPad]] = defaultdict(list)
    for pad in session.scalars(select(LaunchPad)):
        pads_by_ucode[ucode_by_code.get(pad.site, pad.site)].append(pad)

    # (site ucode, pad code) → distinct launches.
    pad_launches: dict[tuple[str, str], set[str]] = defaultdict(set)
    site_launches: dict[str, set[str]] = defaultdict(set)
    unknown_sites: set[str] = set()
    for raw_site, raw_pad, tag in session.execute(
        select(Launchlog.launch_site, Launchlog.launch_pad, Launchlog.launch_tag)
    ):
        site_code, pad_code = _certain(raw_site), _certain(raw_pad)
        if not site_code or not tag:
            continue
        ucode = ucode_by_code.get(site_code)
        if ucode is None:
            unknown_sites.add(site_code)
            continue
        site_launches[ucode].add(tag)
        if pad_code:
            pad_launches[(ucode, pad_code)].add(tag)
    if unknown_sites:
        logger.warning(
            "%d launchlog site codes are absent from GCAT sites.tsv (e.g. %s)",
            len(unknown_sites),
            ", ".join(sorted(unknown_sites)[:5]),
        )

    stats: dict[str, LaunchSiteStats] = {}
    for spec in LAUNCH_SITES:
        if not spec.gcat_sites:
            continue
        # Deduped: two curated codes can be phases of one place, which would
        # otherwise count its pads twice.
        ucodes = list(dict.fromkeys(ucode_by_code.get(c, c) for c in spec.gcat_sites))
        entry = LaunchSiteStats()
        entry.launch_count = len({t for u in ucodes for t in site_launches.get(u, ())})

        sites: list[dict] = []
        for ucode in ucodes:
            row = canonical.get(ucode)
            pads: list[dict] = []
            for pad in pads_by_ucode.get(ucode, ()):
                entry.pad_count += 1
                if pad.latitude is None or pad.longitude is None:
                    continue
                pad_entry = {
                    "code": pad.code,
                    "name": pad.name or pad.short_name or pad.code,
                    "lat": pad.latitude,
                    "lon": pad.longitude,
                    "launches": len(pad_launches.get((ucode, pad.code), ())),
                }
                if pad.wikidata_qid:
                    pad_entry["qid"] = pad.wikidata_qid
                pads.append(pad_entry)
            if row is None and not pads:
                continue
            # Every located pad ships, busiest first — the biggest site has
            # ~120, which costs a few kB, and the disused ones are the
            # interesting half of a cosmodrome's history.
            # The label a reader sees: trimmed per site, before the sites are
            # pooled, since each trails its own location and a range spanning
            # several has no tail in common.
            for pad_entry, label in zip(pads, _pad_labels([p["name"] for p in pads])):
                if label and label != pad_entry["name"]:
                    pad_entry["label"] = label
            pads.sort(key=lambda p: (-p["launches"], p["code"]))
            site: dict = {"code": ucode, "launches": len(site_launches.get(ucode, ()))}
            if row is not None:
                site["name"] = row.name or row.short_name or ucode
                if row.wikidata_qid:
                    site["qid"] = row.wikidata_qid
                if row.latitude is not None and row.longitude is not None:
                    site["lat"] = row.latitude
                    site["lon"] = row.longitude
                    if row.error_deg:
                        site["error_deg"] = row.error_deg
            if pads:
                site["pads"] = pads
            sites.append(site)
        sites.sort(key=lambda s: (-s["launches"], s["code"]))
        entry.sites = sites

        if entry.sites:
            stats[f"{LAUNCH_SITE_SLUG_PREFIX}{spec.slug}"] = entry

    unplaced = [
        s.slug
        for s in LAUNCH_SITES
        if f"{LAUNCH_SITE_SLUG_PREFIX}{s.slug}" not in stats
    ]
    logger.info(
        "Launch sites: positioned %d of %d (%d unplaced: %s)",
        len(stats),
        len(LAUNCH_SITES),
        len(unplaced),
        ", ".join(unplaced),
    )
    return stats
