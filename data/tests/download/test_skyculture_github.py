"""Tests for mirroring part of a GitHub repository at one commit."""

import json
from urllib.parse import unquote

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.skycultures import github
from space_map_data.download.providers.skycultures.github import (
    GitHubFilesDownloader,
    blob_sha,
    list_files,
)

REPO = "someone/sky"
FILES = {
    "cultures/a/index.json": b'{"id": "a"}',
    "cultures/a/illustrations/x y.png": b"\x89PNG",
    "cultures/b/index.json": b'{"id": "b"}',
    "README.md": b"readme",
}


def _blob(path: str, content: bytes, mode: str = "100644") -> dict:
    return {
        "path": path,
        "mode": mode,
        "type": "blob",
        "sha": blob_sha(content),
        "size": len(content),
    }


def _trees(files: dict[str, bytes]) -> dict[str, list[dict]]:
    """The trees API answers of a repository with `files`, by tree sha."""
    inner = {p.removeprefix("cultures/"): c for p, c in files.items() if "/" in p}
    return {
        "root": [
            {"path": "cultures", "mode": "040000", "type": "tree", "sha": "t-cultures"},
            *[_blob(p, c) for p, c in files.items() if "/" not in p],
        ],
        "t-cultures": [
            {"path": "a", "mode": "040000", "type": "tree", "sha": "t-a"},
            *[_blob(p, c) for p, c in inner.items()],
            _blob("a/link", b"index.json", mode="120000"),
        ],
        "all": [_blob(p, c) for p, c in files.items()],
    }


class Repo:
    """A fake GitHub: the trees API and the raw host for one commit."""

    def __init__(self, files: dict[str, bytes], commit: str = "c1") -> None:
        self.files = dict(files)
        self.commit = commit
        self.raw: list[str] = []
        self.api: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        trees = _trees(self.files)
        if url.startswith(f"{github.API_URL}/{REPO}/git/trees/"):
            self.api.append(url)
            sha = request.url.path.rsplit("/", 1)[1]
            if sha == self.commit:
                sha = "all" if request.url.params.get("recursive") else "root"
            return httpx.Response(200, json={"tree": trees[sha], "truncated": False})
        prefix = f"{github.RAW_URL}/{REPO}/{self.commit}/"
        if url.startswith(prefix):
            path = unquote(url.removeprefix(prefix))
            self.raw.append(path)
            if path in self.files:
                return httpx.Response(200, content=self.files[path])
        return httpx.Response(404)


def _downloader(tmp_path, repo: Repo, prefixes=("cultures",)) -> GitHubFilesDownloader:
    class Mirror(GitHubFilesDownloader):
        name = "mirror"

    Mirror.repo = REPO
    Mirror.commit = repo.commit
    Mirror.prefixes = prefixes
    dl = Mirror(httpx.Client(transport=httpx.MockTransport(repo.handler)))
    dl.out_dir = tmp_path
    return dl


class TestListFiles:
    """The listing walks one tree per directory level of the prefix."""

    def test_prefix_files_keep_their_repository_paths(self):
        repo = Repo(FILES)
        client = httpx.Client(transport=httpx.MockTransport(repo.handler))
        files = list_files(client, REPO, "c1", "cultures")
        assert sorted(f.path for f in files) == sorted(
            p for p in FILES if p.startswith("cultures/")
        )
        assert len(repo.api) == 2

    def test_symbolic_links_are_skipped(self):
        client = httpx.Client(transport=httpx.MockTransport(Repo(FILES).handler))
        paths = {f.path for f in list_files(client, REPO, "c1", "cultures")}
        assert "cultures/a/link" not in paths

    def test_missing_directory_fails(self):
        client = httpx.Client(transport=httpx.MockTransport(Repo(FILES).handler))
        with pytest.raises(DownloadError, match="no directory nowhere"):
            list_files(client, REPO, "c1", "nowhere")

    def test_truncated_listing_fails(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tree": [], "truncated": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(DownloadError, match="truncated"):
            list_files(client, REPO, "c1", "")

    def test_rate_limit_names_the_reset_time(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, headers={"x-ratelimit-reset": "1792864736"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(DownloadError, match="resets at 2026-"):
            list_files(client, REPO, "c1", "")


class TestDownload:
    """Files land at their repository paths, checked against their hashes."""

    def test_writes_files_and_records_the_commit(self, tmp_path):
        dl = _downloader(tmp_path, Repo(FILES))
        dl.download()
        assert (
            tmp_path / "cultures/a/illustrations/x y.png"
        ).read_bytes() == b"\x89PNG"
        assert not (tmp_path / "README.md").exists()
        meta = json.loads(dl.metadata_file.read_text())
        assert meta["commit"] == "c1"
        assert meta["record_count"] == 3
        assert meta["files"]["cultures/b/index.json"] == blob_sha(b'{"id": "b"}')
        assert dl.is_complete(None)

    def test_empty_prefix_takes_the_whole_repository(self, tmp_path):
        dl = _downloader(tmp_path, Repo(FILES), prefixes=("",))
        dl.download()
        assert (tmp_path / "README.md").read_bytes() == b"readme"

    def test_files_on_disk_with_their_hash_are_kept(self, tmp_path):
        repo = Repo(FILES)
        _downloader(tmp_path, repo).download()
        (tmp_path / "cultures/b/index.json").write_bytes(b'{"id": "B"}')
        repo.raw.clear()
        _downloader(tmp_path, repo).download()
        assert repo.raw == ["cultures/b/index.json"]
        assert (tmp_path / "cultures/b/index.json").read_bytes() == b'{"id": "b"}'

    def test_new_commit_is_incomplete_and_prunes_removed_files(self, tmp_path):
        _downloader(tmp_path, Repo(FILES)).download()
        files = {p: c for p, c in FILES.items() if not p.startswith("cultures/b/")}
        newer = _downloader(tmp_path, Repo(files, commit="c2"))
        assert not newer.is_complete(None)
        newer.download()
        assert not (tmp_path / "cultures/b/index.json").exists()
        assert (tmp_path / "cultures/a/index.json").exists()

    def test_content_that_misses_its_hash_fails(self, tmp_path):
        repo = Repo(FILES)

        def handler(request: httpx.Request) -> httpx.Response:
            response = repo.handler(request)
            if str(request.url).startswith(github.RAW_URL):
                return httpx.Response(200, content=b"tampered")
            return response

        dl = _downloader(tmp_path, repo)
        dl.client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(DownloadError, match="blob hash differs"):
            dl.download()
