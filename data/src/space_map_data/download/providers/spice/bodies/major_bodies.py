"""Fetch Horizons' major_bodies.txt list.

Used by SpiceDownloader to enrich SPICE body names + IAU aliases, by the
synth downloader to enumerate spacecraft NAIFs, and by probes ingest to
backfill (name, COSPAR) onto agency-SPK spacecraft Object rows.

Fetch is sha256-cached: the on-disk file's mtime tracks actual upstream
changes, not the most-recent download attempt.
"""

import hashlib
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
MB_FILENAME = "major_bodies.txt"


def fetch_major_bodies(client: httpx.Client, out_dir: Path) -> Path:
    """Fetch the MB list to ``out_dir/major_bodies.txt``. Returns the path."""
    cache_file = out_dir / MB_FILENAME
    response = client.get(
        URL,
        params={
            "format": "json",
            "COMMAND": "'MB'",
            "OBJ_DATA": "YES",
            "MAKE_EPHEM": "NO",
        },
    )
    response.raise_for_status()
    text: str = response.json()["result"]
    new_hash = hashlib.sha256(text.encode()).hexdigest()

    prev_hash: str | None = None
    if cache_file.exists():
        prev_hash = hashlib.sha256(cache_file.read_bytes()).hexdigest()

    if prev_hash == new_hash:
        logger.info("Body list unchanged (sha256=%s)", new_hash[:12])
    else:
        cache_file.write_text(text)
        if prev_hash is None:
            logger.info(
                "Fetched body list -> %s (sha256=%s)",
                cache_file.name,
                new_hash[:12],
            )
        else:
            logger.info(
                "Body list changed -> %s (sha256 %s -> %s)",
                cache_file.name,
                prev_hash[:12],
                new_hash[:12],
            )
    return cache_file
