"""Backfill historical Earth-cloud textures from GitHub Releases.

Pulls ``clouds_alpha_*.png`` assets from
https://github.com/joshuabinswanger/matteason_live-cloud-maps_downloader
into the same ``yyyy/mm/dd/HH.png`` slot layout the live downloader uses,
so future scheduler runs naturally skip slots already on disk.

Run from data/:

    uv run python scripts/backfill_earth_clouds.py            # dry-run
    uv run python scripts/backfill_earth_clouds.py --apply
    uv run python scripts/backfill_earth_clouds.py --apply --limit 10

Set ``GITHUB_TOKEN`` in the environment to raise the unauth API rate limit
(60/hr) — only the release listing hits the API; asset downloads don't.
"""

import argparse
import logging
import os
import re
import sys
import time
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

import httpx  # noqa: E402
from tqdm import tqdm  # noqa: E402

from space_map_data.utils.paths import CONFIG_FILE, DOWNLOAD_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OUT_DIR = DOWNLOAD_DIR / "textures" / "earth_clouds"
RELEASES_URL = (
    "https://api.github.com/repos/"
    "joshuabinswanger/matteason_live-cloud-maps_downloader/releases"
)
TAG_RE = re.compile(r"^maps-(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})$")
ASSET_SLEEP_S = 0.3
MAX_RETRIES = 5


def _slot_path(year: int, month: int, day: int, hour: int) -> Path:
    return OUT_DIR / f"{year:04d}" / f"{month:02d}" / f"{day:02d}" / f"{hour:02d}.png"


def _request(
    client: httpx.Client, url: str, *, params: dict | None = None
) -> httpx.Response:
    """GET with rate-limit + transient-error handling.

    - 429/403 with ``Retry-After``: sleep that long and retry.
    - 5xx: exponential backoff (capped at 60s) and retry.
    - On success, if ``x-ratelimit-remaining`` is 0, sleep until
      ``x-ratelimit-reset`` *before* returning so the next call has budget.
    """
    backoff = 1.0
    last: httpx.Response | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        last = client.get(url, params=params)
        retry_after = last.headers.get("retry-after")
        if last.status_code in (429, 403) and retry_after is not None:
            wait = max(int(retry_after), 1)
            logger.warning(
                "HTTP %d on %s — Retry-After=%ds, sleeping",
                last.status_code,
                url,
                wait,
            )
            time.sleep(wait)
            continue
        if 500 <= last.status_code < 600:
            logger.warning(
                "HTTP %d on %s — sleeping %.1fs before retry (%d/%d)",
                last.status_code,
                url,
                backoff,
                attempt,
                MAX_RETRIES,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        # Honor proactive rate-limit signal: only api.github.com sets these.
        if last.headers.get("x-ratelimit-remaining") == "0":
            reset = last.headers.get("x-ratelimit-reset")
            if reset is not None:
                wait = max(int(reset) - int(time.time()), 1)
                logger.warning(
                    "x-ratelimit-remaining=0; sleeping %ds until reset", wait
                )
                time.sleep(wait)
        return last
    assert last is not None
    last.raise_for_status()
    return last


def _list_releases(client: httpx.Client) -> list[dict]:
    """Page through all releases. GitHub returns 100/page until empty."""
    releases: list[dict] = []
    page = 1
    while True:
        r = _request(client, RELEASES_URL, params={"per_page": 100, "page": page})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return releases
        releases.extend(batch)
        page += 1


def _find_asset(release: dict) -> dict | None:
    """Return the clouds_alpha PNG asset for a release, or None if missing."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("clouds_alpha_") and name.endswith(".png"):
            return asset
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Actually download (default: dry-run)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after N downloads"
    )
    args = parser.parse_args()

    with CONFIG_FILE.open("rb") as f:
        user_agent = tomllib.load(f)["download"]["user_agent"]

    headers = {"User-Agent": user_agent, "Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
        logger.info("Using GITHUB_TOKEN for GitHub API")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=headers, follow_redirects=True, timeout=120.0) as client:
        logger.info("Listing releases...")
        releases = _list_releases(client)
        logger.info("Found %d releases", len(releases))

        # Decide what to do for each release.
        plan: list[tuple[Path, str]] = []  # (target_path, asset_url)
        skipped_existing = 0
        skipped_no_asset = 0
        skipped_bad_tag = 0
        for release in releases:
            tag = release.get("tag_name", "")
            m = TAG_RE.match(tag)
            if not m:
                logger.warning("Unparseable tag %r — skipping", tag)
                skipped_bad_tag += 1
                continue
            year, month, day, hour, _minute = (int(g) for g in m.groups())
            target = _slot_path(year, month, day, hour)
            if target.exists():
                skipped_existing += 1
                continue
            asset = _find_asset(release)
            if asset is None:
                logger.warning("No clouds_alpha asset on %s — skipping", tag)
                skipped_no_asset += 1
                continue
            plan.append((target, asset["browser_download_url"]))

        logger.info(
            "Plan: %d to download, %d already on disk, %d missing asset, %d bad tag",
            len(plan),
            skipped_existing,
            skipped_no_asset,
            skipped_bad_tag,
        )
        if args.limit is not None:
            plan = plan[: args.limit]
            logger.info("Limited to %d downloads", len(plan))
        if not args.apply:
            logger.info("Dry-run; pass --apply to download")
            for target, url in plan[:5]:
                logger.info("  would download %s -> %s", url, target)
            if len(plan) > 5:
                logger.info("  ... and %d more", len(plan) - 5)
            return

        failed = 0
        for i, (target, url) in enumerate(tqdm(plan, desc="Backfill", unit="img")):
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                resp = _request(client, url)
                resp.raise_for_status()
            except Exception as e:
                logger.error("Failed %s: %s", url, e)
                failed += 1
                continue
            target.write_bytes(resp.content)
            if i < len(plan) - 1:
                time.sleep(ASSET_SLEEP_S)

        logger.info("Backfill done: %d ok, %d failed", len(plan) - failed, failed)


if __name__ == "__main__":
    main()
