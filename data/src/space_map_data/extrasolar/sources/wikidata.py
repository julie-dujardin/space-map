"""The Wikidata items of stars as an ingest source.

The source is not permanent: each ingest links the items again. An item never
mints and never matches by position. It reaches its star by one claim: its
Hipparcos number, else its Gaia DR3 id, else its HD number, each only when the
item gives one value of it. One claim, because an item that lists two Gaia
sources or a whole system is no proof that they are one star. Hipparcos
first, because the Gaia id on the item of a bright star is often a duplicate
or a companion.

When several items reach one star, often a system and one of its stars, the
item with the most articles keeps it, then the lowest QID. Readers look for
that one.

Its English label (else its multilingual one) names the star unless it is a
bare catalogue number or a SIMBAD identifier.
"""

import logging
import re
from collections.abc import Iterable

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from cdshealpix import nested

from space_map_data.download.providers.stars.wikidata_stars import (
    GAIA_PIXEL_LEVEL,
    GAIA_PIXEL_SHIFT,
    StarItem,
)
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.sources.hipparcos import GAIA_DR3, HD
from space_map_data.extrasolar.sources.names import HIP
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

WIKIDATA = Source(
    name="wikidata", catalogue="wikidata", release="qid", home=1, permanent=False
)

# The SIMBAD prefix of a name; the rest is the name.
_SIMBAD_NAME = "NAME "
# Other SIMBAD identifiers, in SIMBAD's own short forms.
_SIMBAD_IDENTIFIER = re.compile(r"^(V\*|\*\*|\*|Cl\*|\[)")
# A catalogue number names nothing that the Hipparcos designation or the Gaia
# id does not. Other catalogues (Gliese, Wolf, Kepler, variable stars) give
# the names that people use.
_CATALOGUE_NUMBER = re.compile(
    r"^(HR|HDE?|HIP|HIC|SAO|PPM|BD|CD|CPD|TYC|UCAC\d|GSC\d?|IRAS|2MASS\w?"
    r"|Gaia E?DR\d)\s*[-+]?[\dJ]"
)


def usable_name(label: str | None) -> str | None:
    """The label as a name, or None for a catalogue number."""
    if label is None:
        return None
    label = label.removeprefix(_SIMBAD_NAME).strip()
    if not label or _SIMBAD_IDENTIFIER.match(label) or _CATALOGUE_NUMBER.match(label):
        return None
    return label


def label_name(item: StarItem) -> str | None:
    """The name that the item gives its star, or None."""
    return usable_name(item.label_en or item.label_mul)


def hd_positions(hipparcos_rows: pa.Table) -> dict[str, tuple[float, float]]:
    """The J2016.0 position of each HD number that a Hipparcos row claims."""
    claims = hipparcos_rows["claims"].combine_chunks()
    flat = pc.list_flatten(claims)
    parent = pc.list_parent_indices(claims).to_numpy()
    is_hd = pc.and_(
        pc.equal(flat.field("catalogue"), HD[0]),
        pc.equal(flat.field("release"), HD[1]),
    ).to_numpy(zero_copy_only=False)
    numbers = flat.field("catalogue_id").filter(pa.array(is_hd)).to_pylist()
    rows = parent[is_hd]
    ra = hipparcos_rows["match_ra"].to_numpy()[rows]
    dec = hipparcos_rows["match_dec"].to_numpy()[rows]
    return dict(zip(numbers, zip(ra.tolist(), dec.tolist())))


def gaia_position(source_id: str) -> tuple[float, float]:
    """The centre of the source's pixel, good to a region for the claim lookup."""
    pixel = np.array([int(source_id) >> GAIA_PIXEL_SHIFT], np.uint64)
    lon, lat = nested.healpix_to_lonlat(pixel, GAIA_PIXEL_LEVEL)
    return float(lon.deg[0]), float(lat.deg[0])


def _claim(
    item: StarItem,
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
) -> tuple[tuple[str, str, str], tuple[float, float]] | None:
    """The one claim of the item and the position of its star."""
    if len(item.hip) == 1 and item.hip[0] in hip_positions:
        return (*HIP, item.hip[0]), hip_positions[item.hip[0]]
    if len(item.gaia_dr3) == 1:
        return (*GAIA_DR3, item.gaia_dr3[0]), gaia_position(item.gaia_dr3[0])
    if len(item.hd) == 1 and item.hd[0] in hd_positions:
        return (*HD, item.hd[0]), hd_positions[item.hd[0]]
    return None


def engine_rows(
    items: Iterable[StarItem],
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
) -> pa.Table:
    """The pass rows of the items with a claim, the most articles first.

    The engine gives a star that several rows claim to the first of them.
    """
    rows = []
    unclaimed = 0
    for item in sorted(items, key=lambda i: (-i.articles, int(i.qid[1:]))):
        found = _claim(item, hip_positions, hd_positions)
        if found is None:
            unclaimed += 1
            logger.debug("%s: no single id of a star", item.qid)
            continue
        claim, (ra, dec) = found
        rows.append(
            {
                "catalogue_id": item.qid,
                "match_ra": ra,
                "match_dec": dec,
                "claims": [dict(zip(CROSS_ID.names, claim))],
                "name": label_name(item),
            }
        )
    logger.info(
        "Wikidata: %d items with a claim, %d with no single id of a star",
        len(rows),
        unclaimed,
    )
    table = pa.Table.from_pylist(
        rows,
        pa.schema(
            [
                ("catalogue_id", pa.string()),
                ("match_ra", pa.float64()),
                ("match_dec", pa.float64()),
                ("claims", pa.list_(CROSS_ID)),
                ("name", pa.string()),
            ]
        ),
    )
    return table.append_column("mint", pa.array(np.zeros(table.num_rows, bool)))
