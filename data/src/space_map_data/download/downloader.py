"""Shared downloader infrastructure."""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """A provider hit an unrecoverable error and should not retry this run."""


class Downloader(ABC):
    """Base class for all data source downloaders.

    Subclasses MUST set ``self.out_dir`` (and mkdir it) in their ``__init__``.
    ``out_dir`` is where ``metadata.json`` lives — used by ``is_complete``
    and ``_save_metadata``; subclasses with multi-rooted output (e.g. SPICE
    splits raw kernels across one tree and derived tables across another)
    point ``out_dir`` at whichever root owns metadata.json.
    """

    name: str
    out_dir: Path
    # Completeness expires after this age, so slowly-changing upstreams get
    # re-pulled. None trusts a complete download forever.
    max_age: timedelta | None = None

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    @abstractmethod
    def download(self, limit: int | None = None, **kwargs: object) -> None: ...

    @property
    def metadata_file(self) -> Path:
        return self.out_dir / "metadata.json"

    def is_complete(self, limit: int | None) -> bool:
        """Check if a previous download already satisfies the requested limit."""
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        if self.max_age is not None and self._metadata_is_stale(meta):
            return False
        if meta.get("complete"):
            return True  # all available data already downloaded
        record_count = meta.get("record_count")
        if record_count is not None and limit is not None and limit <= record_count:
            return True
        return False

    def _metadata_is_stale(self, meta: dict) -> bool:
        downloaded_at = meta.get("downloaded_at")
        if not isinstance(downloaded_at, str):
            logger.warning(
                "%s: metadata has no downloaded_at, treating as stale", self.name
            )
            return True
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(downloaded_at)
        except ValueError:
            logger.warning(
                "%s: unparseable downloaded_at %r, treating as stale",
                self.name,
                downloaded_at,
            )
            return True
        return self.max_age is not None and age >= self.max_age

    def _is_fresh(self, path: Path) -> bool:
        """True if ``path`` exists and was written within ``max_age``.

        Per-file counterpart to the metadata staleness check, for providers
        whose download loop skips already-present files: lets an interrupted
        refresh resume without re-fetching what it already refreshed.
        """
        if not path.exists():
            return False
        if self.max_age is None:
            return True
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - mtime < self.max_age

    def _save_metadata(
        self,
        url: str,
        record_count: int,
        *,
        complete: bool | None = None,
        **extra: object,
    ) -> None:
        data: dict[str, object] = {
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "record_count": record_count,
        }
        # Omitted by downloaders with their own freshness check (e.g. a daily
        # date stamp) that don't rely on the base ``complete``-based skip.
        if complete is not None:
            data["complete"] = complete
        data.update(extra)
        self.metadata_file.write_text(json.dumps(data, indent=2))
        logger.info("Metadata written -> %s", self.metadata_file.name)
