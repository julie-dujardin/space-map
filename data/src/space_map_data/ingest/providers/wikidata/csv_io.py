"""Shared CSV readers for Wikidata ingest providers."""

import csv
import io
from pathlib import Path


def read_ids_csv(csv_path: Path) -> dict[str, list[str]]:
    """Read a property CSV into a {search_term: [qids]} mapping."""
    mapping: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(csv_path.read_text())):
        if not row:
            continue
        search_term = row[0]
        qids = row[1].split() if len(row) > 1 and row[1] else []
        mapping[search_term] = qids
    return mapping
