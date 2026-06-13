"""Curated "featured satellites" for Earth's Satellites strip.

A manual MVP pick (ISS, Hubble, Starlink): the export bakes each one's name +
thumbnail into Earth's object bundle so the frontend can render them right after
the Moon, with a "+N more" tile linking to the Satellites browse page. ISS and
Hubble are object rows (route to the object); Starlink is a constellation group
(routes to its group page), so it's referenced by slug, not an object id.
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
