"""Download the launch-vehicle escape-performance curves.

A launcher's interplanetary capability is one curve: payload mass against
characteristic energy C3. NASA's Launch Services Program publishes it per
vehicle, but only through an interactive query page that no longer serves
results, so the curves are taken from Girija's compilation of that site
(arXiv:2310.05994), released as CSVs alongside the AMAT mission-analysis tool.

Each file is ``C3 km²/s², payload kg`` with no header, ascending in C3 and
ending where the vehicle runs out of energy. The digitisation is close: at
C3 = 20 the Vulcan VC6S file reads 7578 kg against the 7600 kg ULA's own
user's guide states, and the SLS Block 1B file sits inside the min/max band
of Table 4-1 of the SLS Mission Planner's Guide across the whole range.

The catalogue only cites a handful of these, but the whole set is pulled: the
kick-stage and reusable variants are the same measurement of the same vehicle
flown differently, and splitting them across two runs would make the
comparison the file set exists for impossible.
"""

import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_LAUNCH_PERFORMANCE_DIR

logger = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/athulpg007/AMAT/master/launcher-data"
SOURCE_PAGE = "https://doi.org/10.48550/arXiv.2310.05994"

# Vehicle configuration → filename. The suffixes are configurations rather than
# vehicles: a Star-48 kick stage buys high-C3 performance the vehicle has no
# other way to reach, and a recovered Falcon Heavy is a different launcher from
# an expended one at these energies.
CURVES: dict[str, str] = {
    "atlas-v401": "atlas-v401.csv",
    "atlas-v551": "atlas-v551.csv",
    "atlas-v551-star-48": "atlas-v551-w-star-48.csv",
    "delta-iv-heavy": "delta-IVH.csv",
    "delta-iv-heavy-star-48": "delta-IVH-w-star-48.csv",
    "falcon-heavy-expendable": "falcon-heavy-expendable.csv",
    "falcon-heavy-expendable-star-48": "falcon-heavy-expendable-w-star-48.csv",
    "falcon-heavy-reusable": "falcon-heavy-reusable.csv",
    "sls-block-1": "sls-block-1.csv",
    "sls-block-1b": "sls-block-1B.csv",
    "sls-block-1b-kick": "sls-block-1B-with-kick.csv",
    "vulcan-vc6": "vulcan-centaur-w-6-solids.csv",
    "vulcan-vc6-star-48": "vulcan-centaur-w-6-solids-w-star-48.csv",
}


def _parse_curve(body: str, config: str) -> list[tuple[float, float]]:
    """Validate a curve file into ascending `(C3, payload kg)` pairs.

    A file that stops making sense — a repeated C3, a payload that climbs with
    energy — is a changed upstream format rather than a rocket, so it fails the
    download instead of reaching the catalogue.
    """
    points: list[tuple[float, float]] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        fields = line.split(",")
        if len(fields) != 2:
            raise DownloadError(f"{config}:{lineno}: expected 2 columns, got {line!r}")
        try:
            c3, payload_kg = float(fields[0]), float(fields[1])
        except ValueError as exc:
            raise DownloadError(f"{config}:{lineno}: unparseable row {line!r}") from exc
        if points and c3 <= points[-1][0]:
            raise DownloadError(f"{config}:{lineno}: C3 not ascending ({c3})")
        if points and payload_kg > points[-1][1]:
            raise DownloadError(
                f"{config}:{lineno}: payload rises with C3 ({payload_kg} kg)"
            )
        points.append((c3, payload_kg))
    if len(points) < 2:
        raise DownloadError(f"{config}: {len(points)} points, need at least 2")
    return points


class LaunchPerformanceDownloader(Downloader):
    name = PROVIDERS.LAUNCH_PERFORMANCE

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_LAUNCH_PERFORMANCE_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        point_counts: dict[str, int] = {}
        for config, filename in CURVES.items():
            url = f"{BASE_URL}/{filename}"
            response = self.client.get(url)
            if response.status_code in (403, 404):
                raise DownloadError(
                    f"HTTP {response.status_code} fetching {filename} — stopping (do not retry)"
                )
            response.raise_for_status()

            points = _parse_curve(response.text, config)
            (self.out_dir / f"{config}.csv").write_text(response.text)
            point_counts[config] = len(points)
            logger.info(
                "%s: %d points, C3 %.1f-%.1f km²/s², payload %.0f-%.0f kg",
                config,
                len(points),
                points[0][0],
                points[-1][0],
                points[-1][1],
                points[0][1],
            )

        self._save_metadata(
            SOURCE_PAGE,
            len(CURVES),
            complete=True,
            point_counts=point_counts,
        )
