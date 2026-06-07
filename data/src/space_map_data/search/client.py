"""Thin wrapper around the ``meilisearch`` Python client.

Centralises task-waiting so callers don't sprinkle ``wait_for_task`` everywhere.
"""

import logging
import time
from typing import Any

from meilisearch import Client
from meilisearch.errors import MeilisearchApiError
from meilisearch.models.task import TaskInfo

from .config import MeiliConfig

logger = logging.getLogger(__name__)


class MeiliClient:
    def __init__(self, config: MeiliConfig) -> None:
        self.config = config
        self.raw = Client(config.url, config.master_key)

    def wait(self, task: TaskInfo, *, timeout_s: float = 600.0) -> None:
        """Block until ``task`` settles. Raises on failure or timeout."""
        deadline = time.monotonic() + timeout_s
        while True:
            status = self.raw.get_task(task.task_uid)
            if status.status == "succeeded":
                return
            if status.status == "failed":
                raise RuntimeError(f"Meili task {task.task_uid} failed: {status.error}")
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Meili task {task.task_uid} did not settle in {timeout_s}s"
                )
            time.sleep(0.25)

    def index_exists(self, uid: str) -> bool:
        try:
            self.raw.get_index(uid)
            return True
        except MeilisearchApiError as exc:
            if exc.code == "index_not_found":
                return False
            raise

    def delete_index_if_exists(self, uid: str) -> None:
        if self.index_exists(uid):
            self.wait(self.raw.delete_index(uid))

    def create_index(self, uid: str, primary_key: str) -> None:
        self.wait(self.raw.create_index(uid, {"primaryKey": primary_key}))

    def update_settings(self, uid: str, settings: dict[str, Any]) -> None:
        self.wait(self.raw.index(uid).update_settings(settings))

    def add_documents(self, uid: str, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        self.wait(self.raw.index(uid).add_documents(docs))

    def swap_indexes(self, a: str, b: str) -> None:
        """Atomically swap two indexes — clients see the cutover at one instant."""
        self.wait(self.raw.swap_indexes([{"indexes": [a, b]}]))
