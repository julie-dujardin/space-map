import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from tqdm import tqdm

URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

# J2000 — standard reference epoch for solar system elements
EPOCH = "2451545.0"

_SKIP_NAME_FRAGMENTS = ("Barycenter", "L1", "L2", "L3", "L4", "L5", "Lagrange")

_BASE_PARAMS = {
    "format": "json",
    "OBJ_DATA": "NO",
    "MAKE_EPHEM": "YES",
    "EPHEM_TYPE": "ELEMENTS",
    "CENTER": "500@10",  # heliocentric (Sun-centered)
    "TLIST": EPOCH,
    "CSV_FORMAT": "YES",
    "OUT_UNITS": "AU-D",
    "REF_PLANE": "ECLIPTIC",
    "REF_SYSTEM": "J2000",
}


def fetch_body_list(client: httpx.Client) -> list[tuple[str, str]]:
    """Return (name, naif_id) for all natural solar system bodies in Horizons."""
    response = client.get(
        URL,
        params={
            "format": "json",
            "COMMAND": "'MB'",
            "OBJ_DATA": "YES",
            "MAKE_EPHEM": "NO",
        },
    )
    response.raise_for_status()
    text = response.json()["result"]

    bodies = []
    for line in text.splitlines():
        m = re.match(r"^\s*(-?\d+)\s{2,}(\S.*?)(?:\s{3,}.*)?$", line)
        if not m:
            continue
        naif_id, name = m.group(1), m.group(2).strip()
        if int(naif_id) < 100:  # skip barycenters (0–9) and Sun (10)
            continue
        if any(frag in name for frag in _SKIP_NAME_FRAGMENTS):
            continue
        bodies.append((name, naif_id))

    return bodies


def _parse_elements(result_text: str, name: str, naif_id: str) -> dict:
    """Extract one row of osculating elements from a Horizons text response."""
    header_match = re.search(r"^\s*(JDTDB,.+)$", result_text, re.MULTILINE)
    data_match = re.search(r"\$\$SOE\n(.*?)\$\$EOE", result_text, re.DOTALL)

    if not header_match or not data_match:
        raise ValueError(f"Unexpected Horizons response for {name} ({naif_id})")

    cols = [c.strip() for c in header_match.group(1).split(",") if c.strip()]
    data_lines = [line for line in data_match.group(1).splitlines() if line.strip()]

    if not data_lines:
        raise ValueError(f"No element data for {name} ({naif_id})")

    vals = [v.strip() for v in data_lines[0].split(",")]
    row = dict(zip(cols, vals))
    row["name"] = name
    row["naif_id"] = naif_id
    return row


def download(client: httpx.Client, out_dir: Path, limit: int | None = None) -> dict:
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "bodies.csv"

    print("Horizons: fetching body list...")
    bodies = fetch_body_list(client)
    print(f"Horizons: {len(bodies)} natural bodies found")

    if limit is not None:
        bodies = bodies[:limit]
        print(f"Horizons: limiting to {limit} bodies")

    rows = []
    fieldnames: list[str] | None = None

    for name, naif_id in tqdm(bodies, desc="Horizons", unit="body", dynamic_ncols=True):
        response = client.get(URL, params={**_BASE_PARAMS, "COMMAND": f"'{naif_id}'"})
        response.raise_for_status()
        row = _parse_elements(response.json()["result"], name, naif_id)

        if fieldnames is None:
            fieldnames = ["name", "naif_id"] + [
                k for k in row if k not in ("name", "naif_id")
            ]

        rows.append(row)
        time.sleep(0.5)

    if fieldnames and rows:
        with out_file.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    print(f"Horizons: saved {len(rows)} bodies → {out_file.relative_to(out_dir)}")
    return {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": URL,
        "epoch_jd": EPOCH,
        "record_count": len(rows),
    }
