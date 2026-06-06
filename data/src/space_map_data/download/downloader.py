"""Shared downloader infrastructure."""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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
        if meta.get("complete"):
            return True  # all available data already downloaded
        record_count = meta.get("record_count")
        if record_count is not None and limit is not None and limit <= record_count:
            return True
        return False

    def _save_metadata(
        self, url: str, record_count: int, *, complete: bool, **extra: object
    ) -> None:
        data = {
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "record_count": record_count,
            "complete": complete,
            **extra,
        }
        self.metadata_file.write_text(json.dumps(data, indent=2))
        logger.info("Metadata written -> %s", self.metadata_file.name)
