"""Per-slug stat-card facts that ride no other channel.

Counts, histograms and largest-members already have their own maps into
``write_group_bundles``; this carries the handful of page-specific numbers the
stat row needs and nothing else consumes. One optional field per fact, so a
producer sets only what its family can answer.
"""

from dataclasses import asdict, dataclass


@dataclass
class GroupExtraStats:
    """Stat-row facts for one group slug. Unset fields stay out of the bundle."""

    # Earth orbit zones: typical perigee of the population, in km.
    median_perigee_km: float | None = None
    # Small-body flags: typical Earth MOID, in AU — how close the population comes.
    median_moid_au: float | None = None
    # Planets / dwarf planets categories: moons hosted across the category.
    moon_total: int | None = None
    # Moons category: distinct planet/dwarf hosts.
    host_count: int | None = None
    # Categories whose page is a list of child groups (Comets → split families,
    # Probes → missions): how many of them there are.
    child_group_count: int | None = None
    # Missions and the Probes category: year of the first launch.
    launch_year: int | None = None
    # Missions: "operating" | "lost" | "ended", from the primary craft.
    mission_status: str | None = None
    # Split-comet families: year the parent comet was first observed.
    # Ring Systems: the year the earliest system was found (Saturn, 1610).
    discovery_year: int | None = None
    # Ring Systems: rows in the ring catalogue across every system — the rings
    # the tiles count plus the gaps, divisions, ringlets, regions and arcs
    # inside them.
    ring_feature_count: int | None = None
    # Ring Systems: the system reaching furthest from its host, as
    # {primary_type, primary_id, name, span_km}; the card links to its Rings tab.
    widest_rings: dict | None = None
    # Ring Systems: the catalogue tables its counts, spans and masses are read
    # off, as {title, url, organisation} — the page's own credit line, since it
    # ships none of the per-body bundles that carry them.
    ring_sources: list[dict] | None = None
    # Split-comet families: parent perihelion distance, in AU.
    perihelion_au: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
