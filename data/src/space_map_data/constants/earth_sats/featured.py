"""Curated "featured satellites" for Earth's Satellites strip.

Manual MVP pick (ISS, Hubble, Starlink), baked into Earth's object bundle so
the frontend renders them right after the Moon. Starlink is a constellation
group, referenced by slug rather than object id.
"""

from dataclasses import dataclass

# Earth's Object.id — the host whose bundle carries the featured satellites.
EARTH_ID = "naif-399"


@dataclass(frozen=True)
class FeaturedSat:
    """One featured satellite: either an object row or a constellation group."""

    object_id: str | None = None  # an Object.id (ISS, Hubble)
    constellation_slug: str | None = None  # a constellation group slug (Starlink)


FEATURED_EARTH_SATELLITES: tuple[FeaturedSat, ...] = (
    FeaturedSat(object_id="norad_satcat-25544"),  # International Space Station
    FeaturedSat(object_id="norad_satcat-20580"),  # Hubble Space Telescope
    FeaturedSat(constellation_slug="starlink"),  # Starlink
)
