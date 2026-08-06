"""Download the Smithsonian Global Volcanism Program's eruption catalogue.

Earth is the one body in ``constants/activity`` whose volcanism is a database
rather than a literature value, and GVP publishes that database over an
unauthenticated WFS: every Holocene volcano and every eruption anyone has
recorded, with start and end dates and an explosivity index. Pulling it means
the counts in ``constants/activity/volcanism.py`` are checkable against the
catalogue instead of transcribed off a web page that changes every six weeks.

Everything the constants quote is rederived from the catalogue and lands within
a percent of GVP's own published summary — 79.2 eruptions a year against 79,
72.9 volcanoes active a year against 73, 34.7 new eruptions a year against 35,
9,918 confirmed Holocene eruptions against 9,910. That agreement is what makes
this worth downloading rather than transcribing: it says the roll-up below
matches theirs, so the numbers stay right when the database moves.

One figure is not derivable and stays cited to the summary page: "volcanoes
with continuing eruptions". Continuing is a judgement about the last three
months of field reports, not a property of a row — the WFS layer carries a
closed end date for every recent eruption.

The volcano layer holds 1,196 rows against the ~1,220 the site quotes, the two
being different cuts of the same table; the derived file records what it
actually counted so the drift is visible rather than silent.

On-disk layout::

    sources/activity/gvp/holocene_volcanoes.json
    sources/activity/gvp/holocene_eruptions.json
    sources/activity/gvp/statistics.json
    sources/activity/gvp/metadata.json
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_DIR

logger = logging.getLogger(__name__)

WFS_URL = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
SOURCE_PAGE = "https://volcano.si.edu/"
# The catalogue is versioned and citable; `constants/activity/references.py`
# credits this DOI, and the version actually fetched is recorded in metadata.
CITATION = "https://doi.org/10.5479/si.GVP.VOTW5-2025.5.3"

LAYERS: dict[str, str] = {
    "holocene_volcanoes": "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes",
    "holocene_eruptions": "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions",
}

# Below these the fetch is a failure rather than a thin release — GVP has
# carried an order of magnitude more than this since the 1990s, so a short
# response means a truncated or errored WFS reply, not a shrinking Earth.
MIN_VOLCANOES = 1000
MIN_ERUPTIONS = 9000

# Window for the per-year averages. Ends before the current year because the
# most recent one is always still filling in, and starts late enough that
# reporting completeness is roughly flat across it.
STATS_FIRST_YEAR = 2010
STATS_LAST_YEAR = 2024

CONFIRMED = "Confirmed Eruption"


class GVPDownloader(Downloader):
    """Download the GVP Holocene volcano and eruption layers."""

    name = PROVIDERS.GVP
    # GVP does a full data update roughly every 6-8 weeks.
    max_age = timedelta(days=45)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = SOURCES_DIR / "activity" / "gvp"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        features: dict[str, list[dict]] = {}
        for stem, type_name in LAYERS.items():
            features[stem] = self._fetch_layer(stem, type_name)

        volcanoes = features["holocene_volcanoes"]
        eruptions = features["holocene_eruptions"]
        if len(volcanoes) < MIN_VOLCANOES or len(eruptions) < MIN_ERUPTIONS:
            raise DownloadError(
                f"GVP returned {len(volcanoes)} volcanoes and {len(eruptions)} "
                f"eruptions, below the {MIN_VOLCANOES}/{MIN_ERUPTIONS} floor — "
                "treating as a truncated response rather than a data update"
            )

        stats = derive_statistics(volcanoes, eruptions)
        (self.out_dir / "statistics.json").write_text(json.dumps(stats, indent=2))
        logger.info(
            "GVP: %s volcanoes, %s eruptions, %.1f new eruptions/yr %d-%d",
            f"{len(volcanoes):,}",
            f"{len(eruptions):,}",
            stats["mean_new_eruptions_per_year"],
            STATS_FIRST_YEAR,
            STATS_LAST_YEAR,
        )
        self._save_metadata(
            WFS_URL,
            len(volcanoes) + len(eruptions),
            complete=True,
            citation=CITATION,
            source_page=SOURCE_PAGE,
            layers=LAYERS,
        )

    def _fetch_layer(self, stem: str, type_name: str) -> list[dict]:
        target = self.out_dir / f"{stem}.json"
        if self._is_fresh(target):
            logger.debug("skip %s (fresh)", target.name)
            return _properties(json.loads(target.read_text()))

        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "outputFormat": "application/json",
            "typeName": type_name,
        }
        logger.info("Fetching %s", type_name)
        try:
            resp = self.client.get(WFS_URL, params=params, timeout=180.0)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            raise DownloadError(f"Failed to fetch {type_name}: {e}") from e

        if "features" not in payload:
            # A WFS error comes back as 200 with an XML or JSON exception body;
            # writing it would poison every later run's freshness check.
            raise DownloadError(
                f"{type_name}: response has no 'features' key "
                f"(keys: {sorted(payload)[:5]})"
            )
        target.write_text(json.dumps(payload))
        return _properties(payload)


def _properties(payload: dict) -> list[dict]:
    return [f.get("properties", {}) for f in payload.get("features", [])]


def derive_statistics(volcanoes: list[dict], eruptions: list[dict]) -> dict:
    """Roll the catalogue up into the figures the activity constants quote.

    Kept a module function rather than a method so the constants test can run
    it against the downloaded files without standing up a downloader.

    Eruptions with no end year are the trap: nearly five thousand of them
    predate 1900, where a missing end date means nobody wrote one down rather
    than that the eruption is still running. Carrying those forward to the
    present inflates the per-year counts by 60%. Anything undated is therefore
    counted in its start year only, which is the reading that reproduces GVP's
    own published averages.
    """
    confirmed = [
        e
        for e in eruptions
        if e.get("Activity_Type") == CONFIRMED and e.get("StartDateYear")
    ]
    years = range(STATS_FIRST_YEAR, STATS_LAST_YEAR + 1)
    new: Counter[int] = Counter()
    active_volcanoes: defaultdict[int, set[int]] = defaultdict(set)
    active_eruptions: Counter[int] = Counter()

    for eruption in confirmed:
        start = eruption["StartDateYear"]
        end = eruption.get("EndDateYear") or start
        for year in range(max(start, STATS_FIRST_YEAR), min(end, STATS_LAST_YEAR) + 1):
            active_eruptions[year] += 1
            active_volcanoes[year].add(eruption["Volcano_Number"])
        if STATS_FIRST_YEAR <= start <= STATS_LAST_YEAR:
            new[start] += 1

    span = len(years)
    return {
        "window": [STATS_FIRST_YEAR, STATS_LAST_YEAR],
        "holocene_volcanoes": len(volcanoes),
        "confirmed_holocene_eruptions": sum(
            1 for e in eruptions if e.get("Activity_Type") == CONFIRMED
        ),
        "uncertain_holocene_eruptions": sum(
            1 for e in eruptions if e.get("Activity_Type") != CONFIRMED
        ),
        "mean_new_eruptions_per_year": sum(new[y] for y in years) / span,
        "mean_eruptions_active_per_year": sum(active_eruptions[y] for y in years)
        / span,
        "mean_volcanoes_active_per_year": sum(len(active_volcanoes[y]) for y in years)
        / span,
    }
