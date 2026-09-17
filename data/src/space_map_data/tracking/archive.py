"""The keep-everything half: a git tree holding every sample, forever.

Nobody publishes a DSN history — the feed is overwritten every few seconds and
the only public copies are a few dozen Wayback captures — so the archive is the
point of the exercise even though the site needs none of it.

Layout, and it deliberately does not stay put::

    data/2026/09/17/dsn/raw.jsonl        a day, while its month is open
    data/2026/09.tar.gz                  the month, once it is complete
    data/2026.tar.gz                     the year, once that is

Days land uncompressed and each rollup compresses everything it absorbs in one
pass: consecutive polls differ by almost nothing, so a month compressed
together is a fraction of the same days compressed apart, and git packs the
open month better than it would pack opaque gzips. Paths moving under readers is the
other half of the point — anything built on a stable URL for one day's file is
hotlinking a git host, and the format is meant to be fetched whole and
processed.

A day is sealed two days after it ends: the log it comes from is only gzipped
once a later day is written, and a contact stays open for half an hour after
its last poll.
"""

import gzip
import json
import logging
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from space_map_data.tracking.dsn.store import DSN_DIR
from space_map_data.tracking.dsnbot.store import BOT_DIR
from space_map_data.tracking.estrack.store import ESTRACK_DIR
from space_map_data.utils.paths import ACTIVITY_ARCHIVE_DIR

logger = logging.getLogger(__name__)

# Days a period has to be over before it is archived. Covers the gzip of the
# day's log, which waits for the first write of a later day, and the contact
# gap, which can close a pass half an hour into the next one.
SETTLE = timedelta(days=2)


def run(
    root: Path = ACTIVITY_ARCHIVE_DIR,
    dsn_dir: Path = DSN_DIR,
    estrack_dir: Path = ESTRACK_DIR,
    bot_dir: Path = BOT_DIR,
    today: date | None = None,
    commit: bool = False,
) -> list[Path]:
    """Seal whatever is now settled. Returns the paths written."""
    today = today or datetime.now(UTC).date()
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    written = [
        path
        for day in _settled_days(dsn_dir, estrack_dir, bot_dir, today)
        for path in _seal_day(data, dsn_dir, estrack_dir, bot_dir, day)
    ]
    written += _roll_up(data, today)
    if written and commit:
        _commit(root, len(written))
    return written


def _settled_days(
    dsn_dir: Path, estrack_dir: Path, bot_dir: Path, today: date
) -> list[date]:
    """Days nothing will be written to again, newest last.

    The bot's days reach back to 2024, long before ours: a backfill puts
    hundreds of past days in at once, each sealed on the same footing.
    """
    days: set[date] = set()
    for directory in (
        dsn_dir / "raw",
        dsn_dir / "observations",
        estrack_dir / "live",
        bot_dir / "events",
    ):
        for path in directory.glob("*.jsonl*"):
            day = _day(path.name.split(".")[0])
            if day is not None and today - day > SETTLE:
                days.add(day)
    return sorted(days)


def _seal_day(
    data: Path, dsn_dir: Path, estrack_dir: Path, bot_dir: Path, day: date
) -> list[Path]:
    """Copy one day out, artifact by artifact.

    Each file is written only if it is not there already, rather than skipping
    a day that exists: a source can arrive months after the others, and a
    backfill has to be able to fill a day already sealed without rewriting it.

    A day whose month or year has been packed is finished for good. The logs it
    came from stay in the downloads tree, so without this every run would seal
    them again and repack the period around them.
    """
    if (data / f"{day:%Y}.tar.gz").exists() or (
        data / f"{day:%Y}" / f"{day:%m}.tar.gz"
    ).exists():
        return []
    out = data / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    before = set(out.rglob("*")) if out.exists() else set()
    out.mkdir(parents=True, exist_ok=True)

    for name in ("raw", "observations"):
        _copy_log(dsn_dir / name, day, out / "dsn" / f"{name}.jsonl")
    _copy_log(estrack_dir / "live", day, out / "estrack" / "live.jsonl")
    _copy_log(bot_dir / "events", day, out / "dsn-bot" / "events.jsonl")
    _copy_contacts(dsn_dir / "contacts.jsonl", day, out / "dsn" / "contacts.jsonl")

    # Dated copies of the two dictionaries, filed under the day they changed:
    # a sighting's name means nothing without the dictionary of the time.
    for source, target in (
        (dsn_dir, out / "dsn"),
        (estrack_dir, out / "estrack"),
    ):
        for path in sorted(source.glob("*-*T*Z.*")):
            if _day(path.name.split("-")[-1][:8]) == day:
                _put(path, target / path.name)
    for snapshot_dir in sorted((dsn_dir / "snapshots").glob("*")):
        for path in sorted(snapshot_dir.glob("*.xml")):
            if _day(path.name[:8]) == day:
                _put(path, out / "dsn" / "snapshots" / snapshot_dir.name / path.name)

    # The month's ESTRACK volumes sit beside the days, not in one of them: they
    # are a single figure per month that keeps being revised while it is open.
    month_file = estrack_dir / "months" / f"{day:%Y-%m}.json"
    if month_file.exists():
        _put(month_file, out.parent / "estrack-volume.json")
    if set(out.rglob("*")) == before:
        if not before:
            out.rmdir()
        return []
    logger.info("Archived %s", day)
    return [out]


def _copy_log(directory: Path, day: date, target: Path) -> None:
    """Copy one day of a DailyLog, decompressed — the rollup compresses again."""
    if target.exists():
        return
    packed = directory / f"{day:%Y-%m-%d}.jsonl.gz"
    plain = directory / f"{day:%Y-%m-%d}.jsonl"
    if packed.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.decompress(packed.read_bytes()))
    elif plain.exists():
        _put(plain, target)


def _copy_contacts(source: Path, day: date, target: Path) -> None:
    """The passes that ended this day, split out of the running file."""
    if target.exists() or not source.exists():
        return
    lines = [
        line
        for line in source.read_text().splitlines()
        if line and json.loads(line).get("end", "").startswith(f"{day:%Y-%m-%d}")
    ]
    if not lines:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")


def _put(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _roll_up(data: Path, today: date) -> list[Path]:
    """Fold complete months into one archive, then complete years into one."""
    written: list[Path] = []
    for year_dir in sorted(p for p in data.glob("[0-9][0-9][0-9][0-9]") if p.is_dir()):
        year = int(year_dir.name)
        for month_dir in sorted(p for p in year_dir.glob("[0-9][0-9]") if p.is_dir()):
            if _settled(_month_end(year, int(month_dir.name)), today):
                written.append(_pack(month_dir, year_dir / f"{month_dir.name}.tar.gz"))
        if _settled(date(year, 12, 31), today) and not any(year_dir.glob("[0-9][0-9]")):
            written.append(_pack_year(year_dir, data / f"{year}.tar.gz"))
    return written


def _pack(source: Path, target: Path) -> Path:
    """Replace a directory with one gzip covering all of it.

    Members are named relative to the directory the archive stands in for, so
    ``2026.tar.gz`` holds ``10/25/...`` and extracting it rebuilds the tree.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / target.name
        with tarfile.open(staged, "w:gz", compresslevel=9) as tar:
            for path in sorted(p for p in source.rglob("*") if p.is_file()):
                tar.add(path, arcname=str(path.relative_to(source)))
        shutil.move(staged, target)
    shutil.rmtree(source)
    logger.info("Packed %s (%d bytes)", target.name, target.stat().st_size)
    return target


def _pack_year(year_dir: Path, target: Path) -> Path:
    """Same for a year, unpacking its months so the whole year compresses as one."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / year_dir.name
        staged.mkdir()
        for month in sorted(year_dir.glob("*.tar.gz")):
            with tarfile.open(month) as tar:
                tar.extractall(
                    staged / month.name.removesuffix(".tar.gz"), filter="data"
                )
        packed = _pack(staged, Path(tmp) / target.name)
        shutil.move(packed, target)
    shutil.rmtree(year_dir)
    return target


def _settled(end: date, today: date) -> bool:
    return today - end > SETTLE


def _month_end(year: int, month: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def _day(stamp: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(stamp, fmt).date()
        except ValueError:
            continue
    return None


def _commit(root: Path, count: int) -> None:
    """Commit the tree, if it is a git repository. Pushing stays manual."""
    if not (root / ".git").exists():
        logger.warning("%s is not a git repository; archive left uncommitted", root)
        return
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", f"archive: {count} path(s)"],
        check=True,
    )
