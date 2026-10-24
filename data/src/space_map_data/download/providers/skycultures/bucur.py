"""Download Doina Bucur's dataset of constellation line figures.

The dataset has 40 sky cultures, one JSON file each, in the format of
Stellarium's index.json. A star is a SIMBAD identifier such as "* alf Ori"
instead of a HIP number. Each culture also gives its region, period, place,
licence and the keys of its sources in sources.bib.

Writes, below sources/skycultures/bucur/, the whole repository at its paths
(json/, sources.bib, README.md and the sky charts as PDF), and metadata.json
with the commit and the hash of each file.

Licence: each culture states its own, CC BY-SA for all 40.
https://github.com/doinab/constellation-lines
"""

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.skycultures.github import (
    GitHubFilesDownloader,
)
from space_map_data.utils.paths import SOURCES_SKYCULTURES_DIR

OUT_DIR = SOURCES_SKYCULTURES_DIR / "bucur"
REPO = "doinab/constellation-lines"
# main on 2026-10-24, the last change of 2024-01-04.
COMMIT = "711e06943f342e9340807885016b4ea14e2fe45e"
CULTURES_DIR = OUT_DIR / "json"
SOURCES_FILE = OUT_DIR / "sources.bib"


class BucurConstellationsDownloader(GitHubFilesDownloader):
    name = PROVIDERS.BUCUR_CONSTELLATIONS
    repo = REPO
    commit = COMMIT
    prefixes = ("",)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
