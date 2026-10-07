"""Shared downloader infrastructure."""

import json
import logging
import re
import ssl
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Intermediate certificates that some hosts fail to send with their own. Each
# chains to a root the system already trusts, so loading it restores the
# verification a browser does by fetching it; the alternative is to turn
# verification off for that host.
_INTERMEDIATES_DIR = Path(__file__).parent / "certs"


def tls_context() -> ssl.SSLContext:
    """httpx's own trust store plus the bundled intermediates."""
    context = httpx.create_ssl_context()
    for pem in sorted(_INTERMEDIATES_DIR.glob("*.pem")):
        context.load_verify_locations(cafile=str(pem))
    return context


class DownloadError(Exception):
    """A provider hit an unrecoverable error and should not retry this run."""


# The "bot" that ends the product name, which is the text before the version.
_BOT_TOKEN = re.compile(r"^([^/\s]*?)[-_]?bot(?=[/\s]|$)", re.IGNORECASE)
FALLBACK_USER_AGENT = "space-map/0.1"


def user_agent_without_bot(client: httpx.Client) -> str:
    """The shared User-Agent without the "bot" of its product name.

    Some servers refuse every User-Agent that contains "bot". The version and
    the contact details stay as they are.
    """
    shared = str(client.headers.get("User-Agent", ""))
    return _BOT_TOKEN.sub(r"\1", shared).strip() or FALLBACK_USER_AGENT


class Downloader(ABC):
    """Base class for all data source downloaders.

    Subclasses MUST set ``self.out_dir`` (and mkdir it) in ``__init__`` — it's
    where ``metadata.json`` lives, used by ``is_complete``/``_save_metadata``.
    For multi-rooted output (e.g. SPICE splits kernels and derived tables
    across trees), point it at whichever root owns metadata.json.
    """

    name: str
    out_dir: Path
    # Overridden where two providers share one out_dir and would otherwise
    # clobber each other's record.
    metadata_name: str = "metadata.json"
    # Completeness expires after this age, so slowly-changing upstreams get
    # re-pulled. None trusts a complete download forever.
    max_age: timedelta | None = None

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    @abstractmethod
    def download(self, limit: int | None = None, **kwargs: object) -> None: ...

    @property
    def metadata_file(self) -> Path:
        return self.out_dir / self.metadata_name

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
