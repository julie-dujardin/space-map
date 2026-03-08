import csv
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import httpx

URL = "https://celestrak.org/NORAD/elements/gp.php"


def download(client: httpx.Client, out_dir: Path, limit: int | None = None) -> dict:
    out_file = out_dir / "gp-active.csv"
    url = f"{URL}?GROUP=active&FORMAT=csv"

    print("CelesTrak: downloading active GP elements...")
    response = client.get(url)

    if response.status_code in (403, 404):
        print(
            f"CelesTrak: HTTP {response.status_code} — stopping (do not retry)",
            file=sys.stderr,
        )
        sys.exit(1)

    response.raise_for_status()

    if limit is None:
        out_file.write_bytes(response.content)
        record_count = response.text.count("\n") - 1
    else:
        reader = csv.reader(StringIO(response.text))
        rows = list(reader)
        header, data = rows[0], rows[1:]
        data = data[:limit]
        with out_file.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(data)
        record_count = len(data)

    print(
        f"CelesTrak: saved {record_count:,} records → {out_file.relative_to(out_dir)}"
    )
    return {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "record_count": record_count,
    }
