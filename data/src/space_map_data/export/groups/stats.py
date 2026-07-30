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
    discovery_year: int | None = None
    # Split-comet families: parent perihelion distance, in AU.
    perihelion_au: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
