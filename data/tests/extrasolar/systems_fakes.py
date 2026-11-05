"""Fakes for the star-system tests: a resolver, facts and source rows."""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.stars import msc, orb6, sbx
from space_map_data.extrasolar.sources.simbad import SimbadList, SimbadObject
from space_map_data.extrasolar.systems import orbits
from space_map_data.extrasolar.systems import wds as wds_source
from space_map_data.extrasolar.systems.resolve import FACTS, OTHER, PARALLAX
from space_map_data.extrasolar.systems.simbad import SimbadIndex
from space_map_data.extrasolar.systems.wds import WdsCatalogue
from tests.download.orbit_catalogue_files import (
    MSC_LINES,
    MSC_ORB_README,
    ORB6_LINES,
    SBX_ALIAS,
    SBX_ORBITS,
    SBX_SYSTEMS,
)


class FakeResolver:
    """Ids, positions and facts from dicts."""

    def __init__(
        self,
        ids: dict[tuple[str, str, str], int],
        facts: list[dict],
        positions: dict[str, int] | None = None,
    ) -> None:
        self.ids = ids
        self.rows = facts
        self.positions = positions or {}
        self.matched: list[str] = []
        self.excluded: list[list[int] | None] = []

    def keys(self, catalogue: str, release: str, ids: pa.Array) -> np.ndarray:
        return np.array(
            [self.ids.get((catalogue, release, i), 0) for i in ids.to_pylist()],
            np.int64,
        )

    def listed_keys(self, ids: pa.Array) -> np.ndarray:
        return self.keys("gaia", "dr3", ids)

    def match(self, rows: pa.Table, kind: tuple[str, str]) -> np.ndarray:
        texts = rows["catalogue_id"].to_pylist()
        self.matched += texts
        excluded = rows["match_exclude"].to_pylist()
        self.excluded += excluded
        keys = [self.positions.get(t, 0) for t in texts]
        return np.array(
            [0 if key in (out or []) else key for key, out in zip(keys, excluded)],
            np.int64,
        )

    def facts(self, keys: np.ndarray) -> pa.Table:
        wanted = set(np.asarray(keys).tolist())
        return pa.Table.from_pylist(
            [row for row in self.rows if row["key"] in wanted], schema=FACTS
        )


def fact(
    key: int,
    ra: float,
    dec: float,
    mag: float,
    astrometry: str = "gaia-dr3",
    parallax: float | None = None,
    distance: float | None = None,
    **values,
) -> dict:
    row = {name: None for name in FACTS.names}
    error = None if parallax is None else parallax / 100
    if distance is None and parallax is not None:
        distance = 1000 / parallax
    row |= {
        "key": key,
        "ra": ra,
        "dec": dec,
        "mag": mag,
        "astrometry": astrometry,
        "parallax": parallax,
        "parallax_error": error,
        "distance": distance,
    }
    if distance is not None:
        vote = 1000 / distance
        row |= {
            "vote": vote,
            "vote_error": vote if error is None else error,
            "vote_rank": OTHER if error is None else PARALLAX,
        }
    row |= values
    return row


# Types of the objects that `h_link` holds that SIMBAD's type tree has off `*`.
NOT_STELLAR = frozenset({"GlC", "Cl*", "mul", "err"})


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
    stars = SimbadList(
        {o.oid: o for o in objects},
        children,
        {},
        frozenset({"**"}),
        frozenset(),
        frozenset(o.row["otype"] for o in objects) - NOT_STELLAR,
    )
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
        "Type": "Cmp",
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
    position_angle: float | None = None,
    first_separation: float | None = None,
) -> dict:
    found, known = wds_source.evidence(notes, pm1, pm2)
    return {
        "primary": primary,
        "secondary": secondary,
        "discoverer": "TST   1",
        "separation": separation,
        "first_separation": first_separation,
        "position_angle": position_angle,
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


KEPLER_16 = ("gaia", "dr3", "2133476355197071616")
# The Gaia DR3 AstroSpectroSB1 orbit of Kepler-16 and its masses.
KEPLER_16_GAIA: dict[str, Any] = {
    "solution_id": 4338096422163308546,
    "nss_solution_type": "AstroSpectroSB1",
    "period": 41.101635778608454,
    "t_periastron": 19.559,
    "eccentricity": 0.22660081,
    "arg_periastron": None,
    "inclination": None,
    "a_thiele_innes": -0.08021833,
    "b_thiele_innes": -0.05619175,
    "f_thiele_innes": 0.60016268,
    "g_thiele_innes": 0.08003139,
    "c_thiele_innes": -0.04790195,
    "h_thiele_innes": -0.00602591,
    "parallax_nss": 13.19352913,
    "semi_amplitude_primary": None,
    "semi_amplitude_secondary": None,
    "m1": 0.6708555,
    "m2": 0.18759406,
    "fluxratio": 0.00931033,
}
ALPHA_CEN_DISTANCE = 1.3384


def msc_orbit_rows(folder: Path, *lines: str) -> pa.Table:
    """ORBITS of these lines of the MSC's orb.tsv."""
    (folder / msc.README_FILE).write_text(MSC_ORB_README, encoding="latin-1")
    (folder / msc.ORB_FILE).write_text("\n".join(lines) + "\n", encoding="latin-1")
    return orbits.msc_orbits(folder)


def catalogue_orbits(folder: Path) -> pa.Table:
    """ORBITS of α Cen in the MSC, ORB6 and SBX, and the paper table."""
    (folder / msc.README_FILE).write_text(MSC_ORB_README, encoding="latin-1")
    (folder / msc.ORB_FILE).write_text("\n".join(MSC_LINES) + "\n", encoding="latin-1")
    path = folder / orb6.ORBITS_FILE
    path.write_text("\n".join(ORB6_LINES) + "\n", encoding="latin-1")
    for name, text in (
        (sbx.ORBITS, SBX_ORBITS),
        (sbx.SYSTEMS, SBX_SYSTEMS),
        (sbx.ALIAS, SBX_ALIAS),
    ):
        (folder / f"{name}.csv").write_text(text)
    literature, _ = orbits.read_literature()
    return pa.concat_tables(
        [
            literature,
            orbits.msc_orbits(folder),
            orbits.orb6_orbits(path),
            orbits.sbx_orbits(folder),
        ]
    )
