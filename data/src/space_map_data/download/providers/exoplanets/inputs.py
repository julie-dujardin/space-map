"""Base for a provider that reads the files of other providers."""

from pathlib import Path

from space_map_data.download.downloader import DownloadError, Downloader


class InputReader(Downloader):
    """A provider whose queries come from the files in `inputs`.

    It runs again when an input is newer than its own record. Its own
    `max_age` alone would let it lag one cycle behind a late input.
    """

    inputs: tuple[Path, ...]

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        recorded = self.metadata_file.stat().st_mtime
        return all(
            path.exists() and path.stat().st_mtime <= recorded for path in self.inputs
        )

    def require_inputs(self) -> None:
        for path in self.inputs:
            if not path.exists():
                raise DownloadError(f"{path} is missing, run its provider first")
