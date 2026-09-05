"""Ingest Johnston's Archive per-system pages.

The archive is a census: it lists every asteroid and TNO companion ever
reported, ranks how sure each one is, and carries the component sizes,
rotation, system masses and discovery record that SBDB's satellite payload
has none of. It is not a position source — most companions were found by
lightcurve, which cannot measure an orbit's orientation, and the angles it
does reprint come from the source paper with no frame stated.

Rows attach to the Object rows ``sbdb_moons`` minted. Systems and companions
Johnston knows and SBDB does not are counted and logged, not invented: an
Object needs an SPK-ID we have no way to mint.
"""

import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import delete, insert, select
from tqdm import tqdm

from space_map_data.ingest.providers.objects.sbdb_moons import (
    resolve_parent_object_id,
)
from space_map_data.ingest.providers.objects.johnston_parse import (
    companion_labels,
    flatten,
    parse_companion,
    parse_discoveries,
    parse_system,
)
from space_map_data.models.object import (
    JohnstonConfidence,
    JohnstonMoon,
    JohnstonSystem,
    Object,
    ObjectType,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

INDEX_PAGE = "asteroidmoons.html"
CONFIDENCE_PAGE = "asteroidmoonslist3.html"

# Index entries read `href=astmoons/am-01862.html> <b>(1862) Apollo</b></a>`.
_INDEX_RE = re.compile(r"href=astmoons/(am-[0-9A-Za-z_-]+)\.html>(.*?)</a>", re.S)
# The confidence table's four columns, in the order the page prints them.
_CONFIDENCE_ORDER = (
    JohnstonConfidence.permanent,
    JohnstonConfidence.well_observed,
    JohnstonConfidence.confirmed,
    JohnstonConfidence.probable,
)


def _fold(text: str) -> str:
    """Reduce a name or designation to comparable ASCII alphanumerics."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed.lower() if c.isascii() and c.isalnum())


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _parse_confidence(page: str) -> dict[str, JohnstonConfidence]:
    """Map folded system designation -> Johnston's confidence rank.

    The page is one table, one row per dynamical class, four cells per row in
    ``_CONFIDENCE_ORDER``, each an ``<li>`` list of systems.
    """
    out: dict[str, JohnstonConfidence] = {}
    body = page.partition("<table")[2]
    for row in re.split(r"<tr[^>]*>", body)[1:]:
        cells = re.split(r"<td[^>]*>", row)[1:]
        # First cell is the row's class label; the four ranks follow.
        if len(cells) != len(_CONFIDENCE_ORDER) + 1:
            continue
        for rank, cell in zip(_CONFIDENCE_ORDER, cells[1:]):
            for item in re.split(r"<li>", cell)[1:]:
                text = _strip_tags(item)
                # "(130) Elektra, S/2003 (130) 1, ..." — the system is the head.
                number = re.match(r"\((\d+)\)", text)
                key = number.group(1) if number else _fold(text.split("(")[0])
                if key:
                    out.setdefault(key, rank)
    return out


class JohnstonIngestor:
    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.dir = download_dir / "sources" / "position" / "johnston"
        self.missing_pages = 0
        self.unmatched_systems: list[str] = []
        self.unmatched_companions = 0

    def _clear(self) -> None:
        self.session.execute(delete(JohnstonMoon))
        self.session.execute(delete(JohnstonSystem))
        self.session.commit()

    def _system_index(self) -> dict[str, str]:
        """Map catalogue number / folded designation -> parent Object.id."""
        rows = self.session.execute(
            select(
                Object.id,
                Object.spkid,
                Object.name,
                Object.mpc_designation,
                Object.provisional_designation,
            ).where(Object.spkid.is_not(None))
        ).all()
        index: dict[str, str] = {}
        for oid, spkid, name, mpc, prov in rows:
            if spkid is not None and 20000001 <= spkid <= 21000000:
                index.setdefault(str(spkid - 20000000), oid)
            for token in (mpc, prov, name):
                if token:
                    index.setdefault(_fold(token), oid)
        return index

    def _moons_by_parent(self) -> dict[str, list[tuple[str, str | None, str | None]]]:
        rows = self.session.execute(
            select(
                Object.id,
                Object.parent_id,
                Object.name,
                Object.provisional_designation,
            ).where(
                Object.object_type == ObjectType.moon, Object.parent_id.is_not(None)
            )
        ).all()
        out: dict[str, list[tuple[str, str | None, str | None]]] = {}
        for oid, parent_id, name, prov in rows:
            out.setdefault(parent_id, []).append((oid, name, prov))
        return out

    def _match_companion(
        self,
        label: str,
        discovery: dict | None,
        moons: list[tuple[str, str | None, str | None]],
        taken: set[str],
    ) -> str | None:
        """Resolve one companion block to a moon Object.

        Johnston labels a lone companion "secondary", so its designation and
        permanent name — both only in the discovery paragraph — do most of the
        work; an unambiguous single-moon parent settles the rest.
        """
        candidates = [label]
        if discovery is not None:
            candidates += [
                discovery.get("provisional_designation") or "",
                discovery.get("permanent_name") or "",
            ]
        folded = {_fold(c) for c in candidates if c}
        for oid, name, prov in moons:
            if oid in taken:
                continue
            if folded & {_fold(name or ""), _fold(prov or "")} - {""}:
                return oid
        free = [oid for oid, _, _ in moons if oid not in taken]
        if len(moons) == 1 and free:
            return free[0]
        return None

    def run(self) -> None:
        index_file = self.dir / INDEX_PAGE
        if not index_file.exists():
            logger.warning("%s not found, skipping", index_file)
            return

        self._clear()
        index_html = index_file.read_text(errors="replace")
        entries: dict[str, str] = {}
        for page, label in _INDEX_RE.findall(index_html):
            entries.setdefault(page, _strip_tags(label))

        confidence_file = self.dir / CONFIDENCE_PAGE
        confidence = (
            _parse_confidence(confidence_file.read_text(errors="replace"))
            if confidence_file.exists()
            else {}
        )

        parents = self._system_index()
        moons_by_parent = self._moons_by_parent()
        system_rows: list[dict] = []
        moon_rows: list[dict] = []

        for page, designation in tqdm(
            sorted(entries.items()),
            desc="Johnston ingest",
            unit="page",
            dynamic_ncols=True,
        ):
            path = self.dir / "astmoons" / f"{page}.html"
            if not path.exists():
                self.missing_pages += 1
                continue
            number = re.match(r"\((\d+)\)", designation)
            key = number.group(1) if number else _fold(designation)
            parent_id = parents.get(key)
            if parent_id is None:
                self.unmatched_systems.append(designation)
                continue

            text = flatten(path.read_text(errors="replace"))
            row = parse_system(text)
            row.update(object_id=parent_id, page=page, designation=designation)
            if (rank := confidence.get(key)) is not None:
                row["confidence"] = rank.value
            system_rows.append(row)

            labels = companion_labels(text)
            discoveries = parse_discoveries(text, labels)
            # Horizons parents a moon on its system barycentre, so Pluto's
            # five hang off naif-9 while its archive page is naif-999's.
            moons = moons_by_parent.get(parent_id) or moons_by_parent.get(
                resolve_parent_object_id(parent_id) or "", []
            )
            taken: set[str] = set()
            for position, label in enumerate(labels):
                discovery = _pair_discovery(label, position, discoveries)
                object_id = self._match_companion(label, discovery, moons, taken)
                if object_id is None:
                    self.unmatched_companions += 1
                    continue
                taken.add(object_id)
                companion = parse_companion(text, label)
                companion.update(object_id=object_id, parent_object_id=parent_id)
                if discovery is not None:
                    companion.update(
                        {
                            k: v
                            for k, v in discovery.items()
                            if k not in ("label_hint", "permanent_name") and v
                        }
                    )
                moon_rows.append(companion)

        if system_rows:
            self.session.execute(insert(JohnstonSystem), system_rows)
        if moon_rows:
            self.session.execute(insert(JohnstonMoon), moon_rows)
        self.session.commit()

        logger.info(
            "Johnston: %d systems, %d companions attached",
            len(system_rows),
            len(moon_rows),
        )
        if self.missing_pages:
            logger.warning(
                "  %d system pages listed but not downloaded", self.missing_pages
            )
        if self.unmatched_systems:
            logger.info(
                "  %d systems Johnston lists that we hold no object for: %s",
                len(self.unmatched_systems),
                ", ".join(sorted(self.unmatched_systems)[:20])
                + ("..." if len(self.unmatched_systems) > 20 else ""),
            )
        if self.unmatched_companions:
            logger.info(
                "  %d companion blocks with no moon row to attach to",
                self.unmatched_companions,
            )


def _pair_discovery(label: str, position: int, discoveries: list[dict]) -> dict | None:
    """Pick the discovery paragraph belonging to one companion block.

    Prefer an opener that names the block; fall back to page order, which is
    the same on every page that writes both in the same sequence.
    """
    for record in discoveries:
        if _fold(record.get("label_hint", "")) == _fold(label):
            return record
    if position < len(discoveries):
        return discoveries[position]
    return None


def ingest(download_dir: Path) -> None:
    JohnstonIngestor(download_dir).run()
