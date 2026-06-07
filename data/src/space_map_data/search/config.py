"""Connection config for the Meilisearch indexer.

Values come from environment variables so the same code runs against a
throwaway local Meili (``docker run``) and the production VPS instance.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MeiliConfig:
    url: str
    master_key: str
    batch_size: int = 10_000

    @classmethod
    def from_env(cls) -> "MeiliConfig":
        url = os.environ.get("MEILI_URL", "http://127.0.0.1:7700")
        key = os.environ.get("MEILI_MASTER_KEY", "")
        if not key:
            raise RuntimeError(
                "MEILI_MASTER_KEY is required (export it before running the indexer)"
            )
        return cls(url=url.rstrip("/"), master_key=key)
