import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class Downloader(ABC):
    """Base class for all data source downloaders."""

    name: str

    def __init__(self, client: httpx.Client, out_dir: Path) -> None:
        self.client = client
        self.out_dir = out_dir
        out_dir.mkdir(exist_ok=True)

    @abstractmethod
    def download(self, limit: int | None = None) -> None: ...

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
