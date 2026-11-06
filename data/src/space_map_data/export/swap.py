"""Replace a served directory with a staged one, and undo a stopped replacement.

The served directory is renamed to `old`, and `staging` takes its place. A stop
between the two renames leaves `old`, and `recover` puts it back.
"""

import fcntl
import json
import logging
import shutil
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path

from space_map_data.export.extrasolar import container
from space_map_data.extrasolar.store import fsync_dir

logger = logging.getLogger(__name__)

LOCK_FILE = ".lock"
METADATA_FILE = "metadata.json"


class ExportRefused(Exception):
    """An export that may not run: another export holds the tree, an input is
    stale, or the root is not allowed."""


@contextmanager
def locked(root: Path) -> Generator[None]:
    """Hold the export tree below `root` against every other export. Each one
    clears what a stopped run left in `root/v1/`, which a live run would lose."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / LOCK_FILE).open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExportRefused(f"another export writes to {root}") from None
        yield


def recover(live: Path, old: Path, leftovers: Iterable[Path] = ()) -> None:
    """Undo what a stopped export left: restore or drop `old`, drop `leftovers`."""
    if old.exists():
        if live.exists():
            logger.warning("removing the replaced export %s", old)
            shutil.rmtree(old)
        else:
            logger.warning("restoring %s, which a stopped swap left", old)
            old.rename(live)
    for path in leftovers:
        if path.exists():
            logger.warning("removing what a failed export left: %s", path)
            shutil.rmtree(path)


def swap(live: Path, staging: Path, old: Path) -> None:
    """Put `staging` in place of `live`. A failed rename puts `live` back."""
    replaced = live.exists()
    if replaced:
        live.rename(old)
    try:
        staging.rename(live)
    except BaseException:
        if replaced:
            old.rename(live)
        raise
    fsync_dir(live.parent)
    if replaced:
        shutil.rmtree(old)


def publish[I, K](
    root: Path,
    name: str,
    read: Callable[[], I],
    write_files: Callable[[Path, I], Mapping[K, container.Written]],
    metadata_of: Callable[[Mapping[K, container.Written], str, I], dict],
) -> dict:
    """Write `root/v1/<name>/` and return its metadata. The caller holds the lock.

    `read` returns the inputs and may refuse: it runs after the recovery of a
    stopped swap and before anything is staged. `write_files` writes the container
    files into the staging directory. The token covers them, and `metadata_of`
    gets it with the written files.
    """
    live = root / "v1" / name
    staging = root / "v1" / f".{name}-staging"
    old = root / "v1" / f".{name}-old"
    recover(live, old, (staging,))
    inputs = read()
    staging.mkdir(parents=True)
    try:
        files = write_files(staging, inputs)
        token = container.token_of(list(files.values()))
        for written in files.values():
            container.patch_token(staging / written.path, token)
        metadata = metadata_of(files, token, inputs)
        (staging / METADATA_FILE).write_text(json.dumps(metadata, indent=1))
        swap(live, staging, old)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return metadata
