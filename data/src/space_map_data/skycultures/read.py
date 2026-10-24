"""The sky cultures of each downloaded dataset, as published.

- Stellarium desktop: a directory per culture with index.json,
  description.md and, for most, territory.geojson. The top directory adds
  the international star names that a culture can fall back to.
- Bucur: a JSON file per culture, with the keys of its sources in
  sources.bib.

The files are untrusted data. They are only parsed, never run.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from space_map_data.download.providers.skycultures import bucur, stellarium
from space_map_data.skycultures.licences import (
    Licence,
    licence_section,
    read_licence,
)
from space_map_data.skycultures.refs import (
    Ref,
    bucur_ref,
    stellarium_name,
    stellarium_point,
)

logger = logging.getLogger(__name__)

STELLARIUM, BUCUR = "stellarium", "bucur"
COMMON_NAMES_FILE = "common_star_names.fab"
BUILD_FILE = "CMakeLists.txt"

_TITLE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_SUBDIRECTORY = re.compile(r"^[ \t]*ADD_SUBDIRECTORY\(\s*(\S+)\s*\)", re.MULTILINE)
_ITEM = re.compile(r"^[ \t]*[-*][ \t]+(?:\[#(\d+)\]:?[ \t]*)?(.*)$")
_COMMON_NAME = re.compile(r'\s*(\d+)\|_\("(.*?)"\)\s*(.*?)\s*')
_BIB_ENTRY = re.compile(r"^@\w+\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)


@dataclass
class Culture:
    dataset: str
    key: str
    # index.json or the Bucur file, as published.
    data: dict
    # The culture's file or directory below the dataset's download directory.
    path: str
    name: str | None
    licence: Licence
    sources: list[dict]
    point: Callable[[object], Ref]
    name_ref: Callable[[str], Ref]
    description: str | None = None
    authors: str | None = None
    territory: dict | None = None
    # False when Stellarium leaves the culture out of its standard package.
    packaged: bool = True


def section(markdown: str, heading: str) -> str | None:
    """The text under the level-2 `heading` of a description, or None."""
    found = re.search(
        rf"^##[ \t]*{re.escape(heading)}[ \t]*\n(.*?)(?=^##[ \t]|\Z)",
        markdown,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return found[1].strip() if found else None


def references(text: str | None) -> list[dict]:
    """The list items of a References section, with their numbers.

    A line that does not start an item continues the item before it.
    """
    items: list[dict] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if item := _ITEM.match(line):
            number = int(item[1]) if item[1] else None
            items.append({"number": number, "text": item[2].strip()})
        elif items:
            items[-1]["text"] += " " + line.strip()
        else:
            items.append({"number": None, "text": line.strip()})
    return items


def packaged_cultures(build_file: Path) -> set[str]:
    """The cultures that Stellarium's build installs; others are left out."""
    return set(_SUBDIRECTORY.findall(build_file.read_text()))


def read_stellarium_culture(directory: Path, packaged: set[str]) -> Culture:
    data = json.loads((directory / "index.json").read_text())
    description_file = directory / "description.md"
    description = description_file.read_text() if description_file.exists() else None
    if description is None:
        logger.warning("%s: no description.md, so no licence", directory.name)
    territory_file = directory / "territory.geojson"
    territory = (
        json.loads(territory_file.read_text()) if territory_file.exists() else None
    )
    title = _TITLE.search(description or "")
    if data.get("id") != directory.name:
        logger.warning("%s: index.json gives the id %r", directory.name, data.get("id"))
    return Culture(
        dataset=STELLARIUM,
        key=directory.name,
        data=data,
        path=f"{stellarium.CULTURES_DIR}/{directory.name}",
        name=title[1] if title else None,
        licence=read_licence(licence_section(description or "")),
        sources=references(section(description or "", "References")),
        point=stellarium_point,
        name_ref=stellarium_name,
        description=description,
        authors=section(description or "", "Authors"),
        territory=territory,
        packaged=directory.name in packaged,
    )


def read_stellarium(root: Path = stellarium.OUT_DIR) -> list[Culture]:
    """Every culture of Stellarium desktop, by key."""
    cultures_dir = root / stellarium.CULTURES_DIR
    packaged = packaged_cultures(cultures_dir / BUILD_FILE)
    cultures = [
        read_stellarium_culture(path.parent, packaged)
        for path in sorted(cultures_dir.glob("*/index.json"))
    ]
    for culture in cultures:
        if not culture.packaged:
            logger.info("%s: not in Stellarium's standard package", culture.key)
    return cultures


def read_common_names(root: Path = stellarium.OUT_DIR) -> dict:
    """Stellarium's international star names as a `common_names` table.

    Each name keeps the reference numbers that the file gives it.
    """
    path = root / stellarium.CULTURES_DIR / COMMON_NAMES_FILE
    names: dict[str, list[dict]] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = _COMMON_NAME.fullmatch(line)
        if entry is None:
            logger.warning("%s:%d: not a name line: %r", path.name, number, line)
            continue
        refs = [int(r) for r in re.split(r"[\s,]+", entry[3]) if r]
        names.setdefault(f"HIP {entry[1]}", []).append(
            {"english": entry[2], "references": refs}
        )
    return {"common_names": names}


def bib_entries(text: str) -> dict[str, str]:
    """Each BibTeX entry of `text` by its key, as published."""
    starts = list(_BIB_ENTRY.finditer(text))
    entries = {}
    for at, start in enumerate(starts):
        end = starts[at + 1].start() if at + 1 < len(starts) else len(text)
        entries[start[1]] = text[start.start() : end].strip()
    return entries


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def read_bucur(root: Path = bucur.OUT_DIR) -> list[Culture]:
    """Every culture of Bucur's dataset, by file name."""
    entries = bib_entries((root / "sources.bib").read_text())
    cultures = []
    for path in sorted((root / "json").glob("*.json")):
        data = json.loads(path.read_text())
        sources = []
        for key in data.get("source", []):
            if key not in entries:
                logger.warning("%s: source %r is not in sources.bib", path.stem, key)
            sources.append({"key": key, "bibtex": entries.get(key)})
        cultures.append(
            Culture(
                dataset=BUCUR,
                key=slug(path.stem),
                data=data,
                path=f"json/{path.name}",
                name=data.get("name"),
                licence=read_licence(data.get("licence")),
                sources=sources,
                point=bucur_ref,
                name_ref=bucur_ref,
            )
        )
    return cultures
