"""The places where a sky culture names an object, and what each name is.

Stellarium's index.json and Bucur's files keep objects in the same places:
- the chains of `lines` (and `lines1`) of each constellation and asterism
- `hull_extension` of a figure, and `group` of a Bucur figure
- `image.anchors[].hip` of an illustration
- `defining_stars` of the lunar system, and `link.star` of the lunar system
  and of the zodiac
- the keys of `common_names`

A chain point is an object or, in Stellarium only, an [RA h, Dec °] position.
`map_objects` rebuilds a culture with each object replaced, and keeps every
other field as published.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    HIP = "hip"
    GAIA = "gaia"
    SIMBAD = "simbad"
    DEEP_SKY = "deep-sky"
    SOLAR_SYSTEM = "solar-system"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Ref:
    # As published.
    text: str
    kind: Kind
    # The HIP number, Gaia source_id, SIMBAD identifier or designation.
    value: str
    # The component letter after a HIP number.
    component: str = ""


# Places, as the report counts them.
LINES, FIGURE, ANCHORS, CALENDAR, NAMES = (
    "lines",
    "figure",
    "anchors",
    "calendar",
    "names",
)

SOLAR_SYSTEM = frozenset(
    {"Sun", "Moon", "Mercury", "Venus", "Earth", "Mars"}
    | {"Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"}
)
# Catalogue prefixes of the deep-sky designations in Stellarium's names.
DEEP_SKY_PREFIXES = (
    "ACO",
    "ACOS",
    "B",
    "C",
    "CR",
    "Cr",
    "ESO",
    "IC",
    "LDN",
    "M",
    "Mel",
    "NGC",
    "PGC",
    "PK",
    "PNG",
    "SH",
    "ST",
    "UGC",
)
_HIP = re.compile(r"HIP\s+(\d+)\s*([A-Z]?)")
_GAIA = re.compile(r"Gaia DR3\s+(\d+)")
_DIGITS = re.compile(r"\d+")
_NAME = re.compile(r"(?:COMMENTED )?NAME (.+)")
_DEEP_SKY = re.compile(
    rf"(?:{'|'.join(sorted(DEEP_SKY_PREFIXES, key=len, reverse=True))})\s*\d.*"
)
_LINE_KEY = re.compile(r"lines\d*")
_POINT_LISTS = ("hull_extension", "group")


def _solar_system(text: str) -> Ref | None:
    name = _NAME.fullmatch(text)
    if name and name[1] in SOLAR_SYSTEM:
        return Ref(text, Kind.SOLAR_SYSTEM, name[1])
    return None


def stellarium_point(item: object) -> Ref:
    """What a Stellarium line point or anchor names."""
    if isinstance(item, int) and not isinstance(item, bool):
        return Ref(str(item), Kind.HIP, str(item))
    text = str(item).strip()
    if _DIGITS.fullmatch(text):
        return Ref(str(item), Kind.GAIA, text)
    if text.startswith("DSO:"):
        return Ref(str(item), Kind.DEEP_SKY, text.removeprefix("DSO:").strip())
    return Ref(str(item), Kind.UNKNOWN, text)


def stellarium_name(key: str) -> Ref:
    """What a key of Stellarium's `common_names` names."""
    text = key.strip()
    if hip := _HIP.fullmatch(text):
        return Ref(key, Kind.HIP, hip[1], hip[2])
    if gaia := _GAIA.fullmatch(text):
        return Ref(key, Kind.GAIA, gaia[1])
    if solar := _solar_system(text):
        return solar
    if _DEEP_SKY.fullmatch(text):
        return Ref(key, Kind.DEEP_SKY, text)
    return Ref(key, Kind.UNKNOWN, text)


def bucur_ref(item: object) -> Ref:
    """What a star of Bucur's dataset names: a SIMBAD identifier."""
    text = str(item)
    return _solar_system(text.strip()) or Ref(text, Kind.SIMBAD, text.strip())


Resolve = Callable[[Ref, str], object]


def map_objects(
    culture: dict,
    point: Callable[[object], Ref],
    name: Callable[[str], Ref],
    resolve: Resolve,
) -> dict:
    """A copy of `culture` with each object replaced by `resolve(ref, place)`.

    `point` parses a line point, a list member or an anchor, and `name` a key
    of `common_names`. A position in a chain stays as published. The anchor
    `hip` becomes `object`, and so does the `star` of a calendar link.
    `common_names` becomes a list of {"object": …, "names": […]}.
    """
    out = dict(culture)
    for kind in ("constellations", "asterisms"):
        if kind in culture:
            out[kind] = [_figure(figure, point, resolve) for figure in culture[kind]]
    for key in ("lunar_system", "zodiac"):
        if key in culture:
            out[key] = _calendar(culture[key], point, resolve)
    if "common_names" in culture:
        out["common_names"] = [
            {"object": resolve(name(key), NAMES), "names": names}
            for key, names in culture["common_names"].items()
        ]
    return out


def _figure(figure: dict, point: Callable[[object], Ref], resolve: Resolve) -> dict:
    out = dict(figure)
    for key, value in figure.items():
        if _LINE_KEY.fullmatch(key):
            out[key] = [
                [
                    item if isinstance(item, list) else resolve(point(item), LINES)
                    for item in chain
                ]
                for chain in value
            ]
        elif key in _POINT_LISTS:
            out[key] = [resolve(point(item), FIGURE) for item in value]
    image = figure.get("image")
    if isinstance(image, dict) and "anchors" in image:
        anchors = []
        for anchor in image["anchors"]:
            entry = {k: v for k, v in anchor.items() if k != "hip"}
            entry["object"] = resolve(point(anchor["hip"]), ANCHORS)
            anchors.append(entry)
        out["image"] = {**image, "anchors": anchors}
    return out


def _calendar(calendar: dict, point: Callable[[object], Ref], resolve: Resolve) -> dict:
    out = dict(calendar)
    if "defining_stars" in calendar:
        out["defining_stars"] = [
            resolve(point(item), CALENDAR) for item in calendar["defining_stars"]
        ]
    link = calendar.get("link")
    if isinstance(link, dict) and "star" in link:
        entry = {k: v for k, v in link.items() if k != "star"}
        entry["object"] = resolve(point(link["star"]), CALENDAR)
        out["link"] = entry
    return out


def collect(
    culture: dict, point: Callable[[object], Ref], name: Callable[[str], Ref]
) -> list[tuple[Ref, str]]:
    """Every object of `culture` with its place, in file order."""
    found: list[tuple[Ref, str]] = []

    def keep(ref: Ref, place: str) -> None:
        found.append((ref, place))

    map_objects(culture, point, name, keep)
    return found
