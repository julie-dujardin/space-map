"""Fakes for the star-system tests: source rows."""

from collections import Counter
from collections.abc import Sequence

from space_map_data.extrasolar.sources.simbad import SimbadList, SimbadObject
from space_map_data.extrasolar.systems import wds as wds_source
from space_map_data.extrasolar.systems.simbad import SimbadIndex
from space_map_data.extrasolar.systems.wds import WdsCatalogue


def simbad_object(
    oid: int,
    main_id: str,
    ra: float,
    dec: float,
    otype: str = "*",
    v: float | None = None,
    gaia: str | None = None,
    hip: str | None = None,
    hd: str | None = None,
    identifiers: tuple[str, ...] = (),
    sp_type: str = "",
) -> SimbadObject:
    row = {
        "otype": otype,
        "G": "",
        "pmra": "",
        "pmdec": "",
        "plx_value": "",
        "sp_type": sp_type,
    }
    return SimbadObject(
        oid,
        main_id,
        ra,
        dec,
        [main_id, *identifiers],
        gaia,
        hip,
        hd,
        v,
        row,
    )


def simbad_index(
    objects: list[SimbadObject], links: Sequence[tuple[int, int]] = ()
) -> SimbadIndex:
    """`links` are (parent, child)."""
    children: dict[int, list[int]] = {}
    for parent, child in links:
        children.setdefault(parent, []).append(child)
    stars = SimbadList({o.oid: o for o in objects}, children, {})
    return SimbadIndex.build(stars)


MSC_COMP = [
    "WDS",
    "RAdeg",
    "DEdeg",
    "plx",
    "refpar",
    "PMRA",
    "PMDE",
    "RV",
    "Comp",
    "Sep",
    "Sp",
    "HIP",
    "HD",
    "Bmag",
    "Vmag",
    "Gmag",
    "Jmag",
    "Hmag",
    "Kmag",
    "Ncomp",
    "Gr",
    "Id",
]
MSC_SYS = [
    "WDS",
    "Primary",
    "Secondary",
    "Parent",
    "Type",
    "P",
    "Punit",
    "Sep",
    "Sunit",
    "PA",
    "Vmag1",
    "SP1",
    "Vmag2",
    "SP2",
    "Mass1",
    "MCode1",
    "Mass2",
    "MCode2",
    "Comment",
]


def msc_comp(wds: str, comp: str, **values) -> dict:
    row = dict.fromkeys(MSC_COMP)
    row |= {"WDS": wds, "Comp": comp, "HIP": 0, "HD": 0, "Vmag": 0.0}
    return row | values


def msc_pair(wds: str, primary: str, secondary: str, parent: str, **values) -> dict:
    row = dict.fromkeys(MSC_SYS)
    row |= {
        "WDS": wds,
        "Primary": primary,
        "Secondary": secondary,
        "Parent": parent,
        "Type": "C",
    }
    return row | values


def wds_pair(
    primary: str,
    secondary: str,
    separation: float,
    notes: str = "NO",
    mag1: float | None = None,
    mag2: float | None = None,
    pm1: tuple[float | None, float | None] = (None, None),
    pm2: tuple[float | None, float | None] = (None, None),
) -> dict:
    found, known = wds_source.evidence(notes, pm1, pm2)
    return {
        "primary": primary,
        "secondary": secondary,
        "discoverer": "TST   1",
        "separation": separation,
        "position_angle": None,
        "mag1": mag1,
        "mag2": mag2,
        "v_band": True,
        "spectral_type": None,
        "evidence": found,
        "known": known,
    }


def wds_catalogue(
    pairs: dict[str, list[dict]],
    components: dict[tuple[str, str], dict] | None = None,
) -> WdsCatalogue:
    return WdsCatalogue(pairs, components or {}, Counter())


def wds_component(
    source_id: int | None = None,
    ra: float | None = None,
    dec: float | None = None,
) -> dict:
    return {
        "primary": True,
        "ra": ra,
        "dec": dec,
        "pmra": None,
        "pmdec": None,
        "source_id": source_id,
    }
