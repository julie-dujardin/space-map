"""Each object of a sky culture to its extrasolar ID, or the reason it has none.

A HIP number goes through the registry's hip/2007 claims and a Gaia DR3
source_id through its gaia/dr3 claims. A SIMBAD identifier goes through the
object's HIP number, so that it meets the same star as Stellarium's figures.
Else it goes through its Gaia DR3 number, its HD number (the registry's
hd/1949 claims, from Hipparcos), or the HIP number of the star system that
holds it: SIMBAD often puts the number of a double star on the system and not
on its components. Deep-sky objects and the bodies of the solar system have
no extrasolar ID yet.

A resolved object becomes its ID. An unresolved one becomes
{"ref": <as published>, "reason": <one of REASONS>} with the designation of a
deep-sky object, and for a SIMBAD identifier the object that SIMBAD gives.
"""

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.extrasolar.registry import Registry
from space_map_data.skycultures.refs import Kind, Ref

logger = logging.getLogger(__name__)

HIP, GAIA, HD = ("hip", "2007"), ("gaia", "dr3"), ("hd", "1949")

MATCHED = "matched"
NOT_IN_REGISTRY = "not-in-registry"
COMPONENT = "component"
DEEP_SKY = "deep-sky"
SOLAR_SYSTEM = "solar-system"
NOT_IN_SIMBAD = "not-in-simbad"
NO_STAR_NUMBER = "no-star-number"
UNKNOWN = "unknown-designation"
REASONS = {
    NOT_IN_REGISTRY: "a HIP, Gaia DR3 or HD number with no live ID in the registry",
    COMPONENT: "a component letter after a HIP number other than A",
    DEEP_SKY: "a deep-sky object; the registry has none yet",
    SOLAR_SYSTEM: "the Sun, the Moon or a planet",
    NOT_IN_SIMBAD: "SIMBAD has no object with this identifier",
    NO_STAR_NUMBER: "a SIMBAD star with no HIP, Gaia DR3 or HD number",
    UNKNOWN: "a designation of no known form",
}
# How a SIMBAD identifier reached its ID.
VIA_HIP, VIA_GAIA, VIA_HD, VIA_PARENT = "hip", "gaia", "hd", "parent-hip"

_HIP_ID = re.compile(r"HIP\s+(\d+)")
_GAIA_ID = re.compile(r"Gaia DR3\s+(\d+)")
_HD_ID = re.compile(r"HD\s+(\d+)")


@dataclass(frozen=True)
class SimbadObject:
    oid: str
    main_id: str
    otype: str
    is_star: bool
    gaia: str | None
    hip: str | None
    hd: str | None
    # The HIP numbers of the star systems that hold the object.
    parent_hip: tuple[str, ...] = ()


def _number(ids: list[str], pattern: re.Pattern, oid: str) -> str | None:
    """The one number of `pattern` in `ids`. Several name the system: None."""
    found = sorted({m[1] for i in ids if (m := pattern.fullmatch(i.strip()))})
    if len(found) > 1:
        logger.info(
            "SIMBAD %s has the numbers %s of one catalogue; it uses none", oid, found
        )
        return None
    return found[0] if found else None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


class SimbadCrosswalk:
    """Bucur's identifiers in SIMBAD, from the skyculture_simbad files."""

    def __init__(self, oid_of: dict[str, str], objects: dict[str, SimbadObject]):
        self.oid_of = oid_of
        self.objects = objects

    @classmethod
    def read(cls, directory: Path) -> SimbadCrosswalk:
        oid_of = {r["name"]: r["oid"] for r in _rows(directory / "names.csv")}
        star_types = {
            r["otype"]
            for r in _rows(directory / "otypedef.csv")
            if r["path"].strip().startswith("*")
        }
        ids = {r["oidref"]: r["ids"].split("|") for r in _rows(directory / "ids.csv")}
        basic = {r["oid"]: r for r in _rows(directory / "basic.csv")}
        parents: dict[str, list[str]] = {}
        for link in _rows(directory / "h_link.csv"):
            parents.setdefault(link["child"], []).append(link["parent"])

        def make(oid: str, parent_hip: tuple[str, ...] = ()) -> SimbadObject:
            row = basic[oid]
            return SimbadObject(
                oid=oid,
                main_id=row["main_id"],
                otype=row["otype"],
                is_star=row["otype"] in star_types,
                gaia=_number(ids[oid], _GAIA_ID, oid),
                hip=_number(ids[oid], _HIP_ID, oid),
                hd=_number(ids[oid], _HD_ID, oid),
                parent_hip=parent_hip,
            )

        objects = {}
        for oid in sorted({oid for oid in oid_of.values() if oid}):
            systems = [make(p) for p in parents.get(oid, [])]
            hips = tuple(sorted({s.hip for s in systems if s.is_star and s.hip}))
            objects[oid] = make(oid, hips)
        return cls(oid_of, objects)

    def get(self, name: str) -> SimbadObject | None:
        oid = self.oid_of.get(name)
        return self.objects[oid] if oid else None


def wanted(
    refs: list[Ref], simbad: SimbadCrosswalk | None
) -> tuple[set[str], set[str], set[str]]:
    """The HIP, Gaia DR3 and HD numbers that `refs` can resolve to."""
    hips: set[str] = set()
    gaias: set[str] = set()
    hds: set[str] = set()
    for ref in refs:
        if ref.kind == Kind.HIP and ref.component in ("", "A"):
            hips.add(ref.value)
        elif ref.kind == Kind.GAIA:
            gaias.add(ref.value)
        elif ref.kind == Kind.SIMBAD and simbad is not None:
            found = simbad.get(ref.value)
            if found is not None and found.is_star:
                gaias.update([found.gaia] if found.gaia else [])
                hips.update([found.hip] if found.hip else [])
                hds.update([found.hd] if found.hd else [])
                hips.update(found.parent_hip)
    return hips, gaias, hds


def registry_ids(
    registry: Registry, catalogue: tuple[str, str], values: set[str]
) -> dict[str, int]:
    """The live ID of each catalogue number that has one.

    The lookup goes one region at a time: over all regions at once, its
    status check holds the IDs of every region in memory.
    """
    ordered = sorted(values)
    found: dict[str, int] = {}
    if not ordered:
        return found
    for region in registry.part_regions("xids"):
        ids = registry.lookup(*catalogue, ordered, regions=[region])
        for value, id_ in zip(ordered, ids.tolist()):
            if not id_:
                continue
            if found.setdefault(value, id_) != id_:
                logger.warning(
                    "%s %s has the IDs %d and %d; it takes none",
                    "/".join(catalogue),
                    value,
                    found[value],
                    id_,
                )
                found[value] = 0
    return {value: id_ for value, id_ in found.items() if id_}


@dataclass
class Lookup:
    hip: dict[str, int]
    gaia: dict[str, int]
    hd: dict[str, int] = field(default_factory=dict)
    simbad: SimbadCrosswalk | None = None

    def resolve(self, ref: Ref) -> tuple[int | None, str, dict]:
        """(ID, MATCHED or a reason, fields to keep) of `ref`."""
        if ref.kind == Kind.HIP:
            if ref.component not in ("", "A"):
                return None, COMPONENT, {}
            id_ = self.hip.get(ref.value)
            return (id_, MATCHED, {}) if id_ else (None, NOT_IN_REGISTRY, {})
        if ref.kind == Kind.GAIA:
            id_ = self.gaia.get(ref.value)
            return (id_, MATCHED, {}) if id_ else (None, NOT_IN_REGISTRY, {})
        if ref.kind == Kind.DEEP_SKY:
            return None, DEEP_SKY, {"designation": ref.value}
        if ref.kind == Kind.SOLAR_SYSTEM:
            return None, SOLAR_SYSTEM, {"designation": ref.value}
        if ref.kind == Kind.SIMBAD:
            return self._simbad(ref)
        return None, UNKNOWN, {}

    def disagreements(self) -> list[str]:
        """The SIMBAD stars whose numbers give the registry different IDs.

        Each one is a star with two IDs in the registry, or a component that
        takes the ID of its system.
        """
        found = []
        for name, oid in sorted(self.simbad.oid_of.items() if self.simbad else []):
            star = self.simbad.objects[oid] if oid and self.simbad else None
            if star is None or not star.is_star:
                continue
            ids = {}
            if star.hip in self.hip:
                ids[f"HIP {star.hip}"] = self.hip[star.hip]
            if star.gaia in self.gaia:
                ids[f"Gaia DR3 {star.gaia}"] = self.gaia[star.gaia]
            if star.hd in self.hd:
                ids[f"HD {star.hd}"] = self.hd[star.hd]
            for hip in star.parent_hip:
                if hip in self.hip:
                    ids[f"system HIP {hip}"] = self.hip[hip]
            if len(set(ids.values())) > 1:
                found.append(
                    f"{name}: " + ", ".join(f"{k} is {v}" for k, v in ids.items())
                )
        return found

    def _simbad(self, ref: Ref) -> tuple[int | None, str, dict]:
        found = self.simbad.get(ref.value) if self.simbad else None
        if found is None:
            return None, NOT_IN_SIMBAD, {}
        seen = {"simbad": {"main_id": found.main_id, "otype": found.otype}}
        if not found.is_star:
            return None, DEEP_SKY, {"designation": found.main_id, **seen}
        by_hip = self.hip.get(found.hip) if found.hip else None
        by_gaia = self.gaia.get(found.gaia) if found.gaia else None
        by_hd = self.hd.get(found.hd) if found.hd else None
        by_parent = {self.hip[h] for h in found.parent_hip if h in self.hip}
        if by_hip:
            return by_hip, MATCHED, {"via": VIA_HIP}
        if by_gaia:
            return by_gaia, MATCHED, {"via": VIA_GAIA}
        if by_hd:
            return by_hd, MATCHED, {"via": VIA_HD}
        if len(by_parent) == 1:
            return by_parent.pop(), MATCHED, {"via": VIA_PARENT}
        if found.gaia or found.hip or found.hd or found.parent_hip:
            return None, NOT_IN_REGISTRY, seen
        return None, NO_STAR_NUMBER, seen


@dataclass
class Matcher:
    """Resolves the objects of one culture and counts the outcomes."""

    lookup: Lookup
    # (place, outcome) → count
    counts: Counter = field(default_factory=Counter)
    # The SIMBAD route of each match → count.
    routes: Counter = field(default_factory=Counter)
    unresolved: list[dict] = field(default_factory=list)

    def __call__(self, ref: Ref, place: str) -> object:
        id_, outcome, kept = self.lookup.resolve(ref)
        self.counts[place, outcome] += 1
        if id_ is not None:
            if "via" in kept:
                self.routes[kept["via"]] += 1
            return id_
        point = {"ref": ref.text, "reason": outcome, **kept}
        self.unresolved.append({"place": place, **point})
        return point

    def summary(self) -> dict:
        places: dict[str, dict[str, int]] = {}
        for (place, outcome), count in sorted(self.counts.items()):
            places.setdefault(place, {})[outcome] = count
        total = sum(self.counts.values())
        matched = sum(c for (_, o), c in self.counts.items() if o == MATCHED)
        reasons = Counter()
        for (_, outcome), count in self.counts.items():
            if outcome != MATCHED:
                reasons[outcome] += count
        return {
            "refs": total,
            "matched": matched,
            "unresolved": dict(sorted(reasons.items())),
            "places": places,
            "simbad_routes": dict(sorted(self.routes.items())),
        }
