"""Mirror part of a GitHub repository at one commit.

The trees API lists the files of the commit with their git blob hashes. The
raw host serves each file at the commit. Each file is checked against its
blob hash, so a file on disk that still matches is not fetched again.

The anonymous API allows 60 requests an hour. A download uses one request
for each directory level of its prefixes. The raw files use none.
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.files import flush_to_disk

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/repos"
RAW_URL = "https://raw.githubusercontent.com"
WORKERS = 8
ATTEMPTS = 4
RETRY_WAIT_SECONDS = 10.0
# The git mode of a symbolic link.
_LINK_MODE = "120000"


@dataclass(frozen=True)
class TreeFile:
    # From the repository root.
    path: str
    # The git blob hash.
    sha: str
    size: int


def blob_sha(content: bytes) -> str:
    """The git blob hash of `content`."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _tree(client: httpx.Client, repo: str, sha: str, recursive: bool) -> list[dict]:
    url = f"{API_URL}/{repo}/git/trees/{sha}"
    response = client.get(
        url,
        params={"recursive": "1"} if recursive else None,
        headers={"Accept": "application/vnd.github+json"},
    )
    if response.status_code in (403, 429):
        reset = response.headers.get("x-ratelimit-reset")
        when = (
            datetime.fromtimestamp(int(reset), UTC).isoformat() if reset else "unknown"
        )
        raise DownloadError(
            f"GitHub refused {url} (HTTP {response.status_code}); the rate limit"
            f" resets at {when}"
        )
    response.raise_for_status()
    body = response.json()
    if body.get("truncated"):
        raise DownloadError(f"GitHub truncated the listing of {url}")
    return body["tree"]


def list_files(
    client: httpx.Client, repo: str, commit: str, prefix: str
) -> list[TreeFile]:
    """Every file below the directory `prefix` at `commit`.

    An empty prefix is the whole repository.
    """
    parts = [part for part in prefix.split("/") if part]
    tree = commit
    for at, part in enumerate(parts):
        entries = _tree(client, repo, tree, recursive=False)
        found = [e for e in entries if e["path"] == part and e["type"] == "tree"]
        if not found:
            where = "/".join(parts[: at + 1])
            raise DownloadError(f"{repo} has no directory {where} at {commit}")
        tree = found[0]["sha"]
    base = "".join(f"{part}/" for part in parts)
    files = []
    for entry in _tree(client, repo, tree, recursive=True):
        path = base + entry["path"]
        if entry["type"] == "tree":
            continue
        if entry["type"] != "blob" or entry["mode"] == _LINK_MODE:
            logger.warning("%s: %s is a %s, skipped", repo, path, entry["type"])
            continue
        if any(part in ("", ".", "..") for part in path.split("/")):
            raise DownloadError(f"{repo}: unsafe path {path!r}")
        files.append(TreeFile(path, entry["sha"], entry["size"]))
    return files


def write_synced(path: Path, content: bytes) -> None:
    """Replace `path` with `content`, flushed to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as out:
        out.write(content)
        flush_to_disk(out)
    part.replace(path)


class GitHubFilesDownloader(Downloader):
    """Mirror the files below `prefixes` of `repo` at `commit` into `out_dir`.

    A path below `out_dir` is the path in the repository. A file that the
    previous download had and this commit lacks is deleted.
    """

    repo: str
    commit: str
    prefixes: tuple[str, ...]

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        return self._previous().get("commit") == self.commit

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        files = [
            file
            for prefix in self.prefixes
            for file in list_files(self.client, self.repo, self.commit, prefix)
        ]
        if not files:
            raise DownloadError(f"{self.repo}: no files below {self.prefixes}")
        with ThreadPoolExecutor(WORKERS) as pool:
            fetched = sum(pool.map(self._ensure, files))
        logger.info(
            "%s at %s: %d files, %d fetched, %d already on disk",
            self.repo,
            self.commit[:12],
            len(files),
            fetched,
            len(files) - fetched,
        )
        self._prune(files)
        self._save_metadata(
            f"https://github.com/{self.repo}/tree/{self.commit}",
            len(files),
            complete=True,
            repo=self.repo,
            commit=self.commit,
            prefixes=list(self.prefixes),
            bytes=sum(file.size for file in files),
            files={file.path: file.sha for file in files},
        )

    def _previous(self) -> dict:
        if not self.metadata_file.exists():
            return {}
        return json.loads(self.metadata_file.read_text())

    def _ensure(self, file: TreeFile) -> bool:
        """Fetch `file` unless the copy on disk has its hash. True when fetched."""
        dest = self.out_dir / file.path
        if dest.exists() and dest.stat().st_size == file.size:
            if blob_sha(dest.read_bytes()) == file.sha:
                return False
            logger.info("%s: changed on disk, fetching again", file.path)
        content = self._get(file)
        if blob_sha(content) != file.sha:
            raise DownloadError(f"{self.repo}/{file.path}: the blob hash differs")
        write_synced(dest, content)
        return True

    def _get(self, file: TreeFile) -> bytes:
        url = f"{RAW_URL}/{self.repo}/{self.commit}/{quote(file.path)}"
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self.client.get(url, timeout=120.0)
                if response.status_code == 404:
                    raise DownloadError(f"HTTP 404 for {url}")
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as error:
                if attempt == ATTEMPTS:
                    raise DownloadError(f"{url}: {error!r}") from error
                logger.warning("%s: attempt %d/%d: %r", url, attempt, ATTEMPTS, error)
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        raise AssertionError("unreachable")

    def _prune(self, files: list[TreeFile]) -> None:
        kept = {file.path for file in files}
        stale = sorted(set(self._previous().get("files", {})) - kept)
        for path in stale:
            (self.out_dir / path).unlink(missing_ok=True)
        if stale:
            logger.info(
                "%s: removed %d files of the previous commit", self.repo, len(stale)
            )
