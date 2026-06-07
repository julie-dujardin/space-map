"""Atomic reindex via tmp-index + swap.

Strategy: build ``<uid>_tmp`` from scratch (or wipe it if it lingered from a
prior failed run), stream documents in, then swap with ``<uid>``. Clients
see a single cutover; if anything in the build fails, the live index is
untouched.
"""

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

from ..client import MeiliClient
from ..indices import Index

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _batched(it: Iterable[T], n: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in it:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


def push_index(client: MeiliClient, index: Index, export_dir: Path) -> int:
    """Reindex ``index`` from ``export_dir``. Returns the doc count pushed."""
    tmp_uid = f"{index.uid}_tmp"

    logger.info("Resetting tmp index %s", tmp_uid)
    client.delete_index_if_exists(tmp_uid)
    client.create_index(tmp_uid, index.primary_key)
    client.update_settings(tmp_uid, index.settings)

    count = 0
    for batch in _batched(index.build_documents(export_dir), client.config.batch_size):
        client.add_documents(tmp_uid, batch)
        count += len(batch)
        logger.info("Pushed %d docs to %s", count, tmp_uid)

    if count == 0:
        logger.warning(
            "No documents built for %s — dropping tmp without swapping", index.uid
        )
        client.delete_index_if_exists(tmp_uid)
        return 0

    if client.index_exists(index.uid):
        logger.info("Swapping %s ↔ %s", index.uid, tmp_uid)
        client.swap_indexes(index.uid, tmp_uid)
        client.delete_index_if_exists(tmp_uid)
    else:
        # First publish — no live index to swap with, so just promote tmp.
        logger.info("First publish of %s — creating live index", index.uid)
        client.create_index(index.uid, index.primary_key)
        client.update_settings(index.uid, index.settings)
        client.swap_indexes(index.uid, tmp_uid)
        client.delete_index_if_exists(tmp_uid)

    logger.info("Pushed %d documents to %s", count, index.uid)
    return count
