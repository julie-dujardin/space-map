"""The exoplanet catalogues as ingest sources of host stars.

The names and the (catalogue, release) keys are permanent registry keys. A
host row of the first catalogue that has no Gaia DR3 id or HIP number matches
a registry star by position and G magnitude, as the IAU names do.
"""

from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.match import PositionMatcher

MATCHER = PositionMatcher(
    n_sigma=5.0,
    near_sigma=3.0,
    min_error=0.1,
    reach=0.1,
    max_mag_diff=1.0,
    mag_sigma=0.3,
)
ARCHIVE_SOURCE = Source(
    name=ARCHIVE, catalogue=ARCHIVE, release="pscomppars", home=1, matcher=MATCHER
)
EU_SOURCE = Source(name=EU, catalogue=EU, release="catalog", home=1, matcher=MATCHER)
OEC_SOURCE = Source(name=OEC, catalogue=OEC, release="systems", home=1, matcher=MATCHER)
SOURCES = (ARCHIVE_SOURCE, EU_SOURCE, OEC_SOURCE)
BY_NAME = {source.name: source for source in SOURCES}
