"""Per-system moon discovery timelines.

The Moons collection page charts every moon ever found against the year it was
found. A planetary system page asks the same question of one system, which is
the story of that system's exploration: four moons in 1610 and then nothing for
Jupiter until 1892, or Saturn's two hundred faint outer captures after 2000.

Written as its own small file, keyed by the moon's host, rather than onto each
planet's bundle: the system pages are the only reader, and the objects tier has
no ``--only`` path to rebuild, while the groups tier does.
"""

import gzip
import logging
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.export.groups.categories import moon_discovery_rows

logger = logging.getLogger(__name__)


def build_moon_discovery(session: Session) -> dict[str, dict[int, int]]:
    """Moon discoveries per year, split by host object id.

    The host is the moon's parent, which for a planetary moon is its system
    barycenter (``naif-5``) and for an asteroid's moon is the asteroid.
    """
    by_host: dict[str, dict[int, int]] = {}
    for host_id, year in moon_discovery_rows(session):
        histogram = by_host.setdefault(host_id, {})
        histogram[year] = histogram.get(year, 0) + 1
    return by_host


def write_moon_discovery(out_dir: Path, by_host: dict[str, dict[int, int]]) -> None:
    """Write groups/__moon_discovery__.json.gz — host id → year → count."""
    payload = {
        host: {str(year): n for year, n in sorted(histogram.items())}
        for host, histogram in sorted(by_host.items())
    }
    path = out_dir / "groups" / "__moon_discovery__.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(payload)))
    logger.info(
        "Wrote moon discovery timelines: %d hosts, %d moons → %s",
        len(payload),
        sum(sum(h.values()) for h in by_host.values()),
        path.name,
    )
