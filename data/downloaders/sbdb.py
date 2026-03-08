import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from tqdm import tqdm

URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
PAGE_SIZE = 500


def _fetch_all_fields(client: httpx.Client) -> list[str]:
    """Discover all available field names via the info endpoint."""
    response = client.get(URL, params={"info": "field"})
    response.raise_for_status()
    # Structure: payload["info"]["field"] -> {category: {"list": [{name, ...}, ...]}}
    categories = response.json()["info"]["field"]
    return [f["name"] for cat in categories.values() for f in cat["list"]]


def download(client: httpx.Client, out_dir: Path, limit: int | None = None) -> dict:
    out_file = out_dir / "small-bodies.csv"
    total_written = 0
    total_available = None

    print("SBDB: fetching available fields...")
    all_fields = _fetch_all_fields(client)
    print(f"SBDB: {len(all_fields)} fields available")

    with out_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(all_fields)
        bar = tqdm(total=None, unit="obj", desc="SBDB", dynamic_ncols=True)

        offset = 0
        while True:
            remaining = None if limit is None else limit - total_written
            if remaining is not None and remaining <= 0:
                break

            params = {
                "fields": ",".join(all_fields),
                "limit": min(PAGE_SIZE, remaining) if remaining is not None else PAGE_SIZE,
                "limit-from": offset,
                "full-prec": "true",
            }

            response = client.get(URL, params=params)
            response.raise_for_status()
            payload = response.json()

            if total_available is None:
                total_available = payload["count"]
                bar.total = min(total_available, limit) if limit else total_available
                bar.refresh()

            rows = payload.get("data") or []  # may be null if no results match
            if not rows:
                break

            writer.writerows(rows)
            total_written += len(rows)
            offset += len(rows)
            bar.update(len(rows))

            if len(rows) < PAGE_SIZE:
                break

            time.sleep(0.5)

        bar.close()
    print(f"SBDB: saved {total_written:,} records → {out_file.relative_to(out_dir)}")
    return {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": URL,
        "record_count": total_written,
    }
