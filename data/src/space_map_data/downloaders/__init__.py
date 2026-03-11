from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import httpx


class Downloader(ABC):
    """Base class for all data source downloaders."""

    name: str

    def __init__(self, client: httpx.Client, out_dir: Path) -> None:
        self.client = client
        self.out_dir = out_dir
        out_dir.mkdir(exist_ok=True)

    @abstractmethod
    def download(self, limit: int | None = None) -> dict: ...

    def _metadata(self, url: str, record_count: int, **extra: object) -> dict:
        return {
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "record_count": record_count,
            **extra,
        }
