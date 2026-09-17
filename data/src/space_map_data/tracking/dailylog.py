"""Append-only daily log, gzipped once the day it covers is over.

Both networks need the same thing: write every sample somewhere that grows
without bound but stays cheap. A day of DSN polls is ~3 MB of JSON and ~20 KB
once compressed, because consecutive samples repeat almost everything.

A day closes when the first write of a later day arrives, not on a timer — the
process can be restarted or stopped for a week without leaving a day
uncompressed or, worse, half-rotated.
"""

import gzip
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DailyLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def append(self, at: datetime, record: dict) -> None:
        day = at.strftime("%Y-%m-%d")
        path = self.directory / f"{day}.jsonl"
        if not path.exists():
            self.compress_closed_days(day)
        with path.open("a") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()

    def compress_closed_days(self, today: str) -> None:
        for path in sorted(self.directory.glob("*.jsonl")):
            if path.stem == today:
                continue
            raw = path.read_bytes()
            packed = gzip.compress(raw)
            path.with_suffix(".jsonl.gz").write_bytes(packed)
            path.unlink()
            logger.info(
                "Compressed %s: %d -> %d bytes", path.name, len(raw), len(packed)
            )
