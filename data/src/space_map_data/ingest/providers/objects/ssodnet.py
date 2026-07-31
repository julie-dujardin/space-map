"""Ingest SsODNet best-estimate rows from the Big Flat Table.

Only asteroids carrying a taxonomic class are kept — that is the column the
interior block consumes, and it prunes 1.55 M rows to ~171 k. Albedo, density
and diameter ride along for those objects because they arrive in the same
read and constrain the same question (what is this thing made of).

Numbered asteroids join on `spkid == 20000000 + number`, the SBDB convention
our Object IDs already use. Unnumbered ones join on the provisional
designation, which is looser, so anything that fails to match is counted and
logged rather than dropped silently.
"""

import logging
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import delete, insert, select
from tqdm import tqdm

from space_map_data.models.object import Object, SsODNet
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

BFT_FILE = Path("sources/position/ssodnet/ssoBFT-latest_Asteroid.parquet")

# Numbered minor planets: SBDB SPK-ID is the number plus this offset.
SPKID_OFFSET = 20_000_000

_COLUMNS = [
    "number",
    "name",
    "taxonomy.class",
    "taxonomy.complex",
    "taxonomy.scheme",
    "albedo.value",
    "density.value",
    "diameter.value",
]


def ingest(download_dir: Path) -> None:
    path = download_dir / BFT_FILE
    if not path.exists():
        logger.warning("SsODNet BFT not found at %s — skipping", path)
        return

    table = pq.ParquetFile(path).read(columns=_COLUMNS).to_pydict()
    total = len(table["number"])

    session = get_session()
    with session.begin():
        # Object IDs by the two keys we can match on. Loaded up front: one
        # 1.5 M-row scan beats 171 k point queries.
        by_spkid = {
            spkid: oid
            for oid, spkid in session.execute(
                select(Object.id, Object.spkid).where(Object.spkid.is_not(None))
            )
        }
        by_designation = {
            desig: oid
            for oid, desig in session.execute(
                select(Object.id, Object.provisional_designation).where(
                    Object.provisional_designation.is_not(None)
                )
            )
        }

        rows: list[dict] = []
        classified = unmatched_numbered = unmatched_unnumbered = 0
        for i in tqdm(range(total), desc="SsODNet", unit="row"):
            taxonomy = table["taxonomy.class"][i]
            if taxonomy is None:
                continue
            classified += 1

            number = table["number"][i]
            if number is not None:
                object_id = by_spkid.get(SPKID_OFFSET + int(number))
                if object_id is None:
                    unmatched_numbered += 1
                    continue
            else:
                object_id = by_designation.get(table["name"][i])
                if object_id is None:
                    unmatched_unnumbered += 1
                    continue

            rows.append(
                {
                    "object_id": object_id,
                    "sso_number": int(number) if number is not None else None,
                    "taxonomy_class": taxonomy,
                    "taxonomy_complex": table["taxonomy.complex"][i],
                    "taxonomy_scheme": table["taxonomy.scheme"][i],
                    "albedo": table["albedo.value"][i],
                    "density": table["density.value"][i],
                    "diameter_km": table["diameter.value"][i],
                }
            )

        # Full replace: the BFT is a snapshot, and a class can be revised or
        # withdrawn between releases.
        session.execute(delete(SsODNet))
        for start in range(0, len(rows), 5000):
            session.execute(insert(SsODNet), rows[start : start + 5000])

    logger.info(
        "SsODNet: %d classified of %d rows, %d ingested "
        "(unmatched: %d numbered, %d unnumbered)",
        classified,
        total,
        len(rows),
        unmatched_numbered,
        unmatched_unnumbered,
    )
