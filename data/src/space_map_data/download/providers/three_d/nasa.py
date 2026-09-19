"""Mirror the NASA 3D Resources repository via git clone/pull.

The repo (https://github.com/nasa/NASA-3D-Resources) is a ~10 GB collection of
3D models, textures, and printable assets. We keep a working tree at
``TARGET_DIR`` and re-sync it on each invocation.
"""

import logging
import subprocess

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_MODELS_SPACECRAFT_DIR

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/nasa/NASA-3D-Resources.git"
TARGET_DIR = SOURCES_MODELS_SPACECRAFT_DIR / "NASA-3D-Resources"


class NASA3DResourcesDownloader(Downloader):
    """Mirror github.com/nasa/NASA-3D-Resources to the spacecraft models dir."""

    name = PROVIDERS.NASA_3D

    def __init__(self, client: httpx.Client) -> None:
        # Skip base mkdir — we manage our own path under sources/models/spacecraft/, and
        # the metadata file lives alongside the checkout rather than inside it
        # (so it doesn't show up as an untracked file in `git status`).
        self.client = client
        self.out_dir = TARGET_DIR.parent
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run; git fetch is a no-op when up-to-date.
        return False

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        if (TARGET_DIR / ".git").is_dir():
            logger.info("Pulling %s", TARGET_DIR)
            self._git(["-C", str(TARGET_DIR), "pull", "--ff-only"])
        else:
            logger.info("Cloning %s -> %s", REPO_URL, TARGET_DIR)
            self._git(["clone", REPO_URL, str(TARGET_DIR)])

        self._save_metadata(
            url=REPO_URL,
            record_count=self._tracked_files(),
            complete=True,
            commit=self._head_commit(),
        )

    def _tracked_files(self) -> int:
        return len(self._git_output(["ls-files"]).splitlines())

    def _head_commit(self) -> str:
        return self._git_output(["rev-parse", "HEAD"]).strip()

    @staticmethod
    def _git(args: list[str]) -> None:
        """Run git with output streamed to the terminal (progress visible)."""
        try:
            subprocess.run(["git", *args], check=True)
        except subprocess.CalledProcessError as e:
            raise DownloadError(
                f"git {' '.join(args)} failed: rc={e.returncode}"
            ) from e

    @staticmethod
    def _git_output(args: list[str]) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(TARGET_DIR), *args],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except subprocess.CalledProcessError as e:
            raise DownloadError(
                f"git {' '.join(args)} failed: rc={e.returncode}"
            ) from e
