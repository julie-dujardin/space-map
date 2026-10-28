"""Tokovinin's Multiple Star Catalogue as a tree source.

A row of sys.tsv is one pair: its Primary and Secondary labels and the label
of its Parent, the component one level up that the pair makes. `*` is the
root and `t` a trapezium, a group of components with no hierarchy. A pair
with parent `X`, or of type `X`, is refuted or optical, and is left out. A row
of comp.tsv gives the catalogue values of one label, which can be a pair
(Castor A is Aa and Ab).

A zero in a numeric column means "unknown" (Readme note 4), with two
exceptions. An eccentricity of 0 is a circular orbit. One axis of a proper
motion can be 0 when the other axis is not. A position angle of 0 stays
unknown, because most pairs with no measure give 0.

The positions mix the epochs J2000 and J1991.25, so a member joins by its HIP
and HD numbers, its HR number and GCVS name through SIMBAD, and the WDS id,
never by position.
"""

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa

from space_map_data.download.providers.stars import msc
from space_map_data.extrasolar.systems.nodes import (
    ASTROMETRIC,
    ASTROMETRIC_ORBIT,
    ECLIPSING,
    GCVS,
    HD,
    HIP,
    HR,
    MSC,
    MSC_ID,
    OCCULTATION,
    PROPER_MOTION,
    SPECTROSCOPIC,
    SPECTROSCOPIC_ORBIT,
    VISUAL,
    VISUAL_ORBIT,
    NodeList,
)

logger = logging.getLogger(__name__)

# Days per unit of P, and arcsec per unit of Sep.
PERIOD_UNITS = {"d": 1.0, "y": 365.25, "k": 365.25e3, "M": 365.25e6}
SEPARATION_UNITS = {'"': 1.0, "'": 60.0, "m": 1e-3}
# The first letter of a Type code, and how it says the pair is known.
TYPE_CODES = {
    "c": PROPER_MOTION,
    "C": PROPER_MOTION,
    "v": VISUAL,
    "V": VISUAL_ORBIT,
    "a": ASTROMETRIC,
    "A": ASTROMETRIC_ORBIT,
    "s": SPECTROSCOPIC,
    "S": SPECTROSCOPIC_ORBIT,
    "o": OCCULTATION,
    "E": ECLIPSING,
    "e": ECLIPSING,
}
OPTICAL = "X"
_HR = re.compile(r"HR_(\d+)")
_GCVS = re.compile(r"V\*_([A-Za-z0-9]+)_([A-Z][a-z]{2})")


def _known(text: str | None) -> list[str]:
    found = []
    for token in (text or "").split(","):
        token = token.strip().rstrip("?")
        known = TYPE_CODES.get(token[:1])
        if known and known not in found:
            found.append(known)
    return found


def _optical(text: str | None) -> bool:
    return OPTICAL in (text or "")


def _positive(value: float | None) -> float | int | None:
    """None for the zero that stands for "unknown"."""
    return value if value else None


def _motion(comp: dict) -> tuple[float | None, float | None]:
    """The proper motion, or None in both axes when both are zero."""
    pmra, pmdec = comp.get("PMRA"), comp.get("PMDE")
    if not pmra and not pmdec:
        return None, None
    return pmra, pmdec


def _comp_ids(row: dict) -> list[tuple[str, str, str]]:
    ids = []
    if row.get("HIP"):
        ids.append((*HIP, str(row["HIP"])))
    if row.get("HD"):
        ids.append((*HD, str(row["HD"])))
    text = row.get("Id") or ""
    ids += [(*HR, str(int(m[1]))) for m in _HR.finditer(text)]
    ids += [(*GCVS, f"V* {m[1]} {m[2]}") for m in _GCVS.finditer(text)]
    return ids


def refuted_pairs(directory: Path = msc.OUT_DIR) -> frozenset[tuple[str, str, str]]:
    """The (WDS id, primary, secondary) of the pairs that the MSC refutes."""
    return frozenset(
        (row["WDS"], row["Primary"], row["Secondary"])
        for row in msc.read_table(msc.SYS_FILE, directory).to_pylist()
        if row["Parent"] == msc.REFUTED_PARENT or _optical(row["Type"])
    )


def read_msc(directory: Path = msc.OUT_DIR) -> pa.Table:
    """The nodes of the MSC, one tree per WDS id."""
    return msc_nodes(
        msc.read_table(msc.COMP_FILE, directory).to_pylist(),
        msc.read_table(msc.SYS_FILE, directory).to_pylist(),
        msc.read_table(msc.ORB_FILE, directory).to_pylist(),
    )


def msc_nodes(comp: list[dict], pairs: list[dict], orbits: list[dict]) -> pa.Table:
    """The nodes from the rows of comp.tsv, sys.tsv and orb.tsv."""
    by_system: dict[str, list[dict]] = defaultdict(list)
    for row in pairs:
        by_system[row["WDS"]].append(row)
    values: dict[tuple[str, str], dict] = {}
    for row in comp:
        if row["WDS"] and row["Comp"]:
            values.setdefault((row["WDS"], row["Comp"]), row)
    elements: dict[tuple[str, str], dict] = {}
    for row in orbits:
        labels = re.split(r"[,.]", row["System"] or "")
        if len(labels) == 2:
            elements.setdefault((row["WDS"], labels[1]), row)

    out = NodeList(MSC)
    counts: Counter = Counter()
    for system in sorted(by_system):
        _add_system(out, system, by_system[system], values, elements, counts)
    counts["systems"] = len(by_system)
    logger.info("MSC: %d nodes; %s", len(out), dict(counts))
    return out.table()


def _add_system(
    out: NodeList,
    system: str,
    rows: list[dict],
    values: dict[tuple[str, str], dict],
    elements: dict[tuple[str, str], dict],
    counts: Counter,
) -> None:
    kept = []
    for row in rows:
        if row["Parent"] == msc.REFUTED_PARENT:
            counts["refuted pairs"] += 1
        elif _optical(row["Type"]):
            counts["optical pairs"] += 1
        elif row["Primary"] and row["Secondary"]:
            kept.append(row)
    if not kept:
        counts["systems with no pair left"] += 1
        return
    # The children of each label, and the pair row of each secondary.
    children: dict[str, list[str]] = defaultdict(list)
    orbit_of: dict[str, dict] = {}
    root_rows = []
    for row in kept:
        parent = row["Parent"]
        if parent == msc.ROOT_PARENT:
            parent = f"{row['Primary']},{row['Secondary']}"
            root_rows.append(parent)
        for label in (row["Primary"], row["Secondary"]):
            if label not in children[parent]:
                children[parent].append(label)
        orbit_of.setdefault(row["Secondary"], row)
    labels = set(children) | {c for kids in children.values() for c in kids}
    has_parent = {c for kids in children.values() for c in kids}
    roots = sorted(labels - has_parent)
    if len(roots) != 1:
        counts["systems with several roots, joined in one group"] += 1
        logger.debug("MSC %s: roots %s, joined in one flat group", system, roots)
        children[system] = roots
        roots = [system]
    primary_value: dict[str, dict] = {}
    for row in kept:
        primary_value.setdefault(row["Primary"], row)
    added: set[str] = set()

    def add(label: str, parent: int) -> None:
        if label in added:
            counts["labels in a loop, left out"] += 1
            logger.debug("MSC %s: %s is its own ancestor", system, label)
            return
        added.add(label)
        comp = values.get((system, label), {})
        pair = orbit_of.get(label)
        first = primary_value.get(label)
        orbit = elements.get((system, label), {})
        separation = _positive(pair["Sep"]) if pair else None
        period = _positive(pair["P"]) if pair else None
        mass = None
        if pair:
            mass = _positive(pair["Mass2"])
        elif first:
            mass = _positive(first["Mass1"])
        pmra, pmdec = _motion(comp)
        node = out.add(
            system,
            parent,
            label,
            [*_comp_ids(comp), (*MSC_ID, f"{system} {label}")],
            flat=label == msc.TRAPEZIUM_PARENT,
            ra=comp.get("RAdeg"),
            dec=comp.get("DEdeg"),
            pmra=pmra,
            pmdec=pmdec,
            parallax=_positive(comp.get("plx")),
            v_mag=_positive(comp.get("Vmag"))
            or _positive((pair or {}).get("Vmag2"))
            or _positive((first or {}).get("Vmag1")),
            g_mag=_positive(comp.get("Gmag")),
            spectral_type=comp.get("Sp")
            or (pair or {}).get("SP2")
            or (first or {}).get("SP1"),
            mass=mass,
            separation=separation * SEPARATION_UNITS.get(pair["Sunit"], 1.0)
            if separation and pair and pair["Sunit"] in SEPARATION_UNITS
            else None,
            position_angle=_positive(pair["PA"]) if pair else None,
            period=period * PERIOD_UNITS[pair["Punit"]]
            if period and pair and pair["Punit"] in PERIOD_UNITS
            else None,
            eccentricity=orbit.get("e"),
            semi_major_axis=_positive(orbit.get("a")),
            known=_known(pair["Type"]) if pair else None,
        )
        for child in children.get(label, []):
            add(child, node)

    add(roots[0], -1)
    counts["pairs"] += len(kept)
