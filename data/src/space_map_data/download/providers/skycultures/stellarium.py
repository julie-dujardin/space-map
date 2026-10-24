"""Download the sky cultures of Stellarium desktop.

Each culture is a directory below `skycultures/`:
- index.json: the constellations and asterisms with their lines, the names of
  stars and other objects, the illustrations with their anchor stars, and for
  some cultures the boundaries and the lunar stations
- description.md: the text, with the authors, the sources and the licence
- territory.geojson: where the culture lived, for most cultures
- illustrations/: the images of the figures
The translations are two gettext catalogues for all cultures, one for the
names and one for the descriptions.

A line point is a HIP number, a Gaia DR3 source_id as a string, "DSO:" and a
deep-sky designation, or an [RA in hours, Dec in degrees] position.

Writes, below sources/skycultures/stellarium/, the files at their paths in the
repository, and metadata.json with the commit and the hash of each file.

Licence: each culture states its own in description.md.
"""

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.skycultures.github import (
    GitHubFilesDownloader,
)
from space_map_data.utils.paths import SOURCES_SKYCULTURES_DIR

OUT_DIR = SOURCES_SKYCULTURES_DIR / "stellarium"
REPO = "Stellarium/stellarium"
# master on 2026-10-24.
COMMIT = "0d956aacee305c29a92498860bc394ed21e0e731"
CULTURES_DIR = "skycultures"
PREFIXES = (
    CULTURES_DIR,
    "po/stellarium-skycultures",
    "po/stellarium-skycultures-descriptions",
)


class StellariumSkyculturesDownloader(GitHubFilesDownloader):
    name = PROVIDERS.STELLARIUM_SKYCULTURES
    repo = REPO
    commit = COMMIT
    prefixes = PREFIXES

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
