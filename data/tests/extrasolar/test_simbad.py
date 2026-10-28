"""Tests for the SIMBAD source, the named Gaia rows and their ingest."""

import csv
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.download.providers.stars import simbad_stars
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.exoplanets.names import WgsnName
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import gaia, hipparcos, names, simbad
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    BestNeighbours,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS, HIPPARCOS_1997
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.simbad import (
    SIMBAD,
    SIMBAD_HIP,
    IauRow,
    SimbadList,
)
from tests.extrasolar.conftest import offset, table_rows
from tests.extrasolar.test_stars import (
    DEC,
    NO_ORBITS,
    RA,
    at,
    dms,
    fidelity,
    gaia_star,
    gaia_stars,
    hip_stars,
    hms,
    iau_entry,
    write_names,
)

BASIC = (
    "oid",
    "main_id",
    "otype",
    "ra",
    "dec",
    "coo_err_maj",
    "coo_err_min",
    "coo_qual",
    "pmra",
    "pmdec",
    "pm_err_maj",
    "pm_err_min",
    "plx_value",
    "plx_err",
    "sp_type",
    "nbref",
)
NO_BEST = BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))


def named_rows(named: pa.Table, joined: tuple[gaia.SourceTable, ...] = ()) -> pa.Table:
    """The pass rows of `read_named` rows, with no best neighbours or orbits."""
    reader = gaia.GaiaReader(NO_BEST, joined=joined, orbits=NO_ORBITS)
    return reader.named_rows(named)


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(["" if v is None else v for v in row] for row in rows)


def write_simbad(
    directory: Path,
    objects: list[dict],
    links: Sequence[tuple[int, int]] = (),
    iau: Sequence[tuple[str, int]] = (),
) -> Path:
    """The files of simbad_stars. An object is a dict of basic columns, plus
    "ids" and the fluxes "B", "V" and "G"."""
    directory.mkdir(parents=True, exist_ok=True)
    _write(
        directory / simbad_stars.BASIC_FILE,
        list(BASIC),
        [[o.get(name, "") for name in BASIC] for o in objects],
    )
    _write(
        directory / simbad_stars.FLUXES_FILE,
        ["oidref", "B", "V", "G"],
        [
            [o["oid"], o.get("B"), o.get("V"), o.get("G")]
            for o in objects
            if {"B", "V", "G"} & set(o)
        ],
    )
    _write(
        directory / simbad_stars.IDENT_FILE,
        ["oidref", "id"],
        [[o["oid"], text] for o in objects for text in o.get("ids", [])],
    )
    _write(
        directory / simbad_stars.LINKS_FILE,
        ["child", "parent"],
        [[child, parent] for parent, child in links],
    )
    _write(
        directory / simbad_stars.IAU_FILE,
        ["name", "identifier", "oid"],
        [[name, "x", oid] for name, oid in iau],
    )
    return directory


def star(oid: int, ra: float, dec: float, *ids: str, **more: object) -> dict:
    return {
        "oid": oid,
        "main_id": ids[0] if ids else f"TYC {oid}",
        "otype": "*",
        "ra": ra,
        "dec": dec,
        "coo_err_maj": 10,
        "ids": list(ids),
    } | more


def claims_of(rows: pa.Table) -> list[list[str]]:
    return [
        [f"{c['catalogue']}/{c['release']}/{c['catalogue_id']}" for c in found or []]
        for found in rows["claims"].to_pylist()
    ]


class TestNames:
    """Designations spelled as XHIP spells them, in the name order."""

    @pytest.mark.parametrize(
        ("ids", "expected"),
        [
            (["* alf Ori"], "Alpha Orionis"),
            (["*  98 Tau", "* k Tau"], "98 Tauri"),
            (["* k Tau"], "k Tauri"),
            (["*   9 Lib", "* alf02 Lib"], "Alpha2 Librae"),
            (["* mu. Cep", "V* mu. Cep"], "Mu Cephei"),
            (["* ksi UMa A"], "Xi Ursae Majoris A"),
            (["* iot UMa BC"], "Iota Ursae Majoris BC"),
            (["* zet UMa Aa"], "Zeta Ursae Majoris Aa"),
            (["V* V354 Cep"], "V354 Cephei"),
            (["V* RS CVn"], "RS Canum Venaticorum"),
            (["V* eta Car"], "Eta Carinae"),
            (["* alf Xyz"], None),
            (["WR 104", "NAME Pistol Star"], None),
        ],
    )
    def test_designation(self, ids, expected):
        assert simbad.designation(ids) == expected

    def test_name_order(self):
        assert simbad.star_name(["V* S Dor", "HD  35343"], "V* S Dor") == "S Doradus"
        assert simbad.star_name(["HIP 5", "HD  93129A"], "x") == "HD 93129A"
        assert simbad.star_name(["HIP 55203A"], "x") == "HIP 55203A"
        assert simbad.star_name(["Gaia DR3 1"], "NAME Luhman 16") == "Luhman 16"
        assert simbad.star_name(["V* V5097 Sgr", "WR 104"], "MR 80") == "WR 104"
        assert simbad.star_name(["V* V5097 Sgr"], "MR 80") == "V5097 Sagittarii"
        # A SIMBAD NAME comes after HD and before a survey designation.
        assert simbad.star_name(["NAME Innes' star", "HD 304043"], "x") == "HD 304043"
        frosty = ["NAME Frosty Leo Nebula", "NAME Frosty Leo"]
        assert simbad.star_name(frosty, "IRAS 09371+1212") == "Frosty Leo"
        assert simbad.star_name(["NAME Foo"], "NAME Luhman 16") == "Luhman 16"
        assert simbad.star_name([], "UCAC4 154-126202") == "UCAC4 154-126202"
        assert simbad.star_name(["* gam02 Vel", "V* V5097 Sgr"], "WR 11") == (
            "Gamma2 Velorum"
        )

    def test_cluster_member_name(self):
        w26 = ["Cl* Westerlund 1 BKS AS", "Cl* Westerlund  1  W  26"]
        assert simbad.star_name(w26, "2MASS J16470540-4550367") == "Westerlund 1 W 26"
        assert simbad.star_name(w26 + ["HD 1"], "2MASS J1") == "HD 1"
        assert simbad.star_name(w26 + ["NAME Foo"], "2MASS J1") == "Foo"
        # A classical main identifier stays.
        assert simbad.star_name(["Cl* Melotte 22 MT 14"], "Wolf 204") == "Wolf 204"
        assert simbad.star_name([], "Cl* NGC 2632 JC 278") == "NGC 2632 JC 278"

    def test_prefixes(self):
        assert simbad.star_name(["NAME * f Pup AB"], "NAME * f Pup AB") == (
            "f Puppis AB"
        )
        assert simbad.star_name(["NAME HD 193702AB"], "x") == "HD 193702AB"
        assert simbad.star_name([], "SV* HV  2700") == "HV 2700"
        assert simbad.star_name([], "EM* LkHA  245") == "LkHA 245"
        assert simbad.star_name([], "** HDP    1A") == "HDP 1A"
        assert simbad.star_name(["NAME V* FV Tau/c"], "x") == "FV Tau/c"
        # The type is the whole acronym: the Gaia row names a Gaia star.
        assert simbad.star_name(["Gaia DR3 9"], "GR*   9") is None
        assert simbad.star_name(["NAME GR* 15A"], "NAME GR* 15A") == "GR* 15A"
        assert simbad.star_name([], "C* 2905") == "C* 2905"

    def test_survey_main_id_of_a_gaia_star(self):
        assert simbad.star_name(["Gaia DR3 5"], "TYC 4279-1148-1") is None
        assert simbad.star_name(["Gaia DR3 5"], "BD+12 345") == "BD+12 345"
        assert simbad.star_name(["Gaia DR3 5", "Gaia DR3 6"], "TYC 1-2-1") == (
            "TYC 1-2-1"
        )

    def test_what_the_system_gives(self):
        main = "2MASS J21021878+3641412"
        given = {"designation": "V1610 Cygni", "hip": "7"}
        assert simbad.star_name(["Gaia DR3 5"], main, given) == "V1610 Cygni"
        assert simbad.star_name(["Gaia DR3 5"], main, {"hip": "7"}) == "HIP 7"
        # The row's own names come first.
        assert simbad.star_name(["V* V1611 Cyg"], main, given) == "V1611 Cygni"
        assert simbad.star_name(["HD 1A"], main, {"hd": "1"}) == "HD 1A"

    def test_a_system_names_its_only_point(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(1, RA, DEC, "V* V1610 Cyg", "HIP  100"),
                star(2, RA, DEC, "2MASS J1", "Gaia DR3 21", G=8.0),
                # Inside the Gaia point of its parent.
                star(3, RA, DEC, "2MASS J2", G=9.0),
            ],
            links=[(1, 2), (2, 3)],
        )
        stars = SimbadList.read(directory)
        assert stars.handed() == {2: {"hip": "100", "designation": "V1610 Cygni"}}

    def test_a_system_of_two_points_keeps_its_designation(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(1, RA, DEC, "V* V1610 Cyg", "HIP  100"),
                star(2, RA, DEC, "2MASS J1", "Gaia DR3 21", G=8.0),
                star(3, RA, DEC, "2MASS J2", "Gaia DR3 22", G=12.0),
            ],
            links=[(1, 2), (1, 3)],
        )
        stars = SimbadList.read(directory)
        # The designation names the system node.
        assert stars.handed() == {2: {"hip": "100"}}
        rows, _ = simbad.engine_rows(stars, stars.handed(), set(), {}, {})
        # The faint component has only a survey id, so its Gaia row names it.
        assert rows["name"].to_pylist() == ["HIP 100", None]
        assert rows["simbad_otype"].to_pylist() == ["*", "*"]

    def test_a_catalogued_system_keeps_its_designation(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(1, RA, DEC, "* a Lup", "HIP 71500", "HD 128266"),
                star(2, RA, DEC, "HD 128267", "HIP 71502", "Gaia DR3 21", G=8.0),
            ],
            links=[(1, 2)],
        )
        stars = SimbadList.read(directory)
        assert stars.handed() == {}
        rows, _ = simbad.engine_rows(stars, stars.handed(), set(), {}, {})
        assert rows["name"].to_pylist() == ["HD 128267"]


class TestSimbadList:
    """Systems, their primary component and the numbers they hand down."""

    @pytest.fixture
    def stars(self, tmp_path) -> SimbadList:
        directory = write_simbad(
            tmp_path / "simbad",
            [
                # A system without a Gaia id and its two components.
                star(1, RA, DEC, "* kap CrA", "HIP  100", "HD 200"),
                star(2, RA, DEC, "* kap01 CrA", "Gaia DR3 21", V=6.0),
                star(3, RA, DEC, "* kap02 CrA", "Gaia DR3 22", V=5.0),
                # A Gaia point with components that Gaia does not resolve.
                star(4, RA, DEC, "NAME Luhman 16", "Gaia DR3 40", G=16.9),
                star(5, RA, DEC, "NAME Luhman 16A", G=17.5),
                # Too faint to add to the light of the point.
                star(11, RA, DEC, "NAME Luhman 16C"),
                # Two HIP numbers name a system: neither is used.
                star(6, RA, DEC, "HIP 1", "HIP 2"),
                star(7, RA, DEC, "HIP 55203A", "HD 300"),
                # Gaia pairs HIP 800 with another source.
                star(8, RA, DEC, "Gaia DR3 80", "HIP 800"),
                # Gaia pairs HIP 900 with the Gaia source of star 2.
                star(9, RA, DEC, "HIP 900"),
                # Gaia pairs HIP 1000 with a source that SIMBAD does not list.
                star(10, RA, DEC, "HIP 1000"),
                # Its Hipparcos star is far.
                star(12, RA, DEC, "HIP 1200"),
            ],
            links=[(1, 2), (1, 3), (4, 5), (4, 11)],
            iau=[("Kappa", 1), ("Luhman", 5)],
        )
        return SimbadList.read(directory)

    def test_rows_and_systems(self, stars):
        # The system, and the component inside a Gaia point.
        assert [oid for oid in sorted(stars.objects) if not stars.is_row(oid)] == [
            1,
            5,
        ]
        assert stars.primary(1) == 3
        assert stars.primary(5) == 4
        assert stars.handed() == {3: {"hip": "100", "hd": "200"}}
        assert stars.objects[6].hip is None
        assert stars.objects[7].hip is None and stars.objects[7].hd == "300"
        assert stars.iau == {"Kappa": 1, "Luhman": 5}

    def test_engine_rows(self, stars):
        best = {"100": "22", "800": "81", "900": "21", "1000": "77"}
        positions = {"100": (RA, DEC), "1200": at(400)}
        rows, hip_rows = simbad.engine_rows(
            stars,
            stars.handed(),
            hipparcos_hd={"200"},
            best=best,
            hip_positions=positions,
        )
        assert rows["catalogue_id"].to_pylist() == [
            "2",
            "3",
            "4",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
        ]
        assert claims_of(rows) == [
            ["gaia/dr3/21"],
            # The HD number of the system is on a Hipparcos star.
            ["gaia/dr3/22"],
            ["gaia/dr3/40"],
            [],
            ["hd/1949/300"],
            ["gaia/dr3/80"],
            [],
            ["hip/2007/1000"],
            [],
            [],
        ]
        # The second pass: a star with a Gaia id and the HIP of its system.
        assert hip_rows["catalogue_id"].to_pylist() == ["3"]
        assert claims_of(hip_rows) == [["hip/2007/100"]]
        assert rows["name"].to_pylist()[:5] == [
            "Kappa1 Coronae Australis",
            "Kappa2 Coronae Australis",
            "Luhman 16",
            "HIP 1",
            "HD 300",
        ]
        assert rows["mint"].to_pylist() == [True] * 10
        assert rows["simbad_v_mag"].to_pylist()[:2] == [6.0, 5.0]

        found = simbad.iau_rows(stars, stars.handed(), rows)
        # The system hands its HIP number to its brightest component.
        kappa, luhman = found["Kappa"], found["Luhman"]
        assert (kappa.oid, kappa.own, kappa.hip) == ("3", False, "100")
        assert (luhman.oid, luhman.own, luhman.hip) == ("4", False, None)
        # A star with a Gaia id disputes its own HIP number, or the one its
        # system hands it, where Gaia pairs that number with another source.
        # SIMBAD gives the best neighbour of HIP 900 to star 2, which does not
        # take that number.
        assert simbad.disputed_hip(stars, stars.handed(), best) == {800, 900}
        assert simbad.disputed_hip(stars, stars.handed(), best | {"100": "21"}) == {
            100,
            800,
            900,
        }

    def test_positions_errors_and_magnitudes(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(
                    1,
                    RA,
                    DEC,
                    "* alf Ori",
                    pmra=0.0,
                    pmdec=1000.0,
                    pm_err_maj=1.0,
                    plx_value=6.5,
                    plx_err=0.8,
                    sp_type="M1-2Ia-Iab",
                    V=0.42,
                    B=2.27,
                ),
                star(2, RA, DEC, G=12.0, V=11.0, B=11.5, coo_err_maj=""),
            ],
        )
        listed = SimbadList.read(directory)
        rows, _ = simbad.engine_rows(listed, listed.handed(), set(), {}, {})
        moved = (rows["match_dec"][0].as_py() - DEC) * 3600
        assert moved == pytest.approx(16.0, rel=1e-3)
        assert rows["match_ra"][1].as_py() == pytest.approx(RA)
        assert rows["match_error"].to_pylist() == pytest.approx(
            [np.hypot(10, 16) / 1000, 1.0]
        )
        expected = hipparcos.g_estimate(
            np.array([0.42]), np.array([1.85]), np.array([np.nan])
        )
        assert rows["match_mag"].to_pylist() == pytest.approx([expected[0], 12.0])
        assert rows["epoch"].to_pylist() == [2000.0] * 2
        assert rows["parallax"].to_pylist()[0] == pytest.approx(6.5)
        assert rows["simbad_sp_type"].to_pylist() == ["M1-2Ia-Iab", None]


class TestNamedGaiaRows:
    """The named rows never mint."""

    def test_mint(self):
        named = gaia.join_fidelity(
            gaia_stars([gaia_star(11, RA, DEC, 5.4), gaia_star(13, *at(100), 7.0)]),
            fidelity([(11, 0.9)]),
        )
        rows = named_rows(named)
        assert rows["catalogue_id"].to_pylist() == ["11", "13"]
        assert rows["mint"].to_pylist() == [False, False]
        assert rows["fidelity_v2"].to_pylist() == pytest.approx([0.9, None])


class TestIauNames:
    """A name without a HIP claim claims its SIMBAD row, one name per row."""

    def test_simbad_claims_and_positions(self, tmp_path):
        path = write_names(
            tmp_path / "names.json",
            [
                iau_entry("Izar", HIP="72105", mag="2.45", RA="1", DEC="2"),
                iau_entry("Dilmun", Designation="WASP-121"),
                iau_entry("Stella", Designation="HD 116798", RA="3", DEC="4"),
            ],
        )
        simbad_rows = {
            "Izar": IauRow("9", 1.5, 2.5, True, "72105"),
            "Dilmun": IauRow("7", 10.0, 20.0, True, None, "21"),
            "Stella": IauRow("8", 3.0, 4.0001, False, None),
        }
        rows = names.engine_rows({"72105": (1.0, 2.0)}, path, simbad=simbad_rows)
        assert claims_of(rows) == [
            ["hip/2007/72105"],
            ["simbad/oid/7"],
            ["simbad/oid/8", "hd/1949/116798"],
        ]
        assert rows["match_ra"].to_pylist() == [1.0, 10.0, 3.0]
        assert rows["match_dec"].to_pylist() == pytest.approx([2.0, 20.0, 4.0001])
        # The exoplanet ingest compares these ids with those of a host.
        assert names.claimed(rows, simbad_rows, path) == [
            WgsnName("Izar", "", hip=72105),
            WgsnName("Dilmun", "WASP-121", oid="7", gaia_dr3=21),
            WgsnName("Stella", "HD 116798", oid="8"),
        ]

    def test_components_and_shared_rows(self, tmp_path):
        position = {"RA": "5", "DEC": "6"}
        path = write_names(
            tmp_path / "names.json",
            [
                iau_entry("Prime", HIP="500", mag="1.0", **position),
                # Fainter components of HIP 500.
                iau_entry("Own", HIP="500", mag="3.0", **position),
                iau_entry("Inside", HIP="500", mag="4.0", **position),
                iau_entry("Numbered", HIP="500", mag="5.0", **position),
                # Two names whose objects have one row.
                iau_entry("System", mag="2.0", **position),
                iau_entry("Point", mag="6.0", **position),
                # Its row is the star of HIP 500.
                iau_entry("Twin", **position),
            ],
        )
        simbad_rows = {
            "Prime": IauRow("10", 7.0, 8.0, True, "500"),
            "Own": IauRow("11", 7.0, 8.0, True, None),
            "Inside": IauRow("10", 7.0, 8.0, False, "500"),
            "Numbered": IauRow("13", 7.0, 8.0, True, "500"),
            "System": IauRow("14", 7.0, 8.0, False, None),
            "Point": IauRow("14", 7.0, 8.0, True, None),
            "Twin": IauRow("10", 7.0, 8.0, True, "500"),
        }
        rows = names.engine_rows({"500": (5.0, 6.0)}, path, simbad=simbad_rows)
        assert claims_of(rows) == [
            ["hip/2007/500"],
            ["simbad/oid/11"],
            [],
            [],
            [],
            ["simbad/oid/14"],
            [],
        ]
        assert rows["match_ra"].to_pylist() == [5.0, 7.0, 5.0, 5.0, 5.0, 7.0, 5.0]


class TestSimbadIngest:
    """SIMBAD links, mints, joins and names through the engine."""

    def test_ingest(self, tmp_path):
        root = tmp_path / "root"
        p = {key: at(60 * key) for key in range(1, 10)}
        stored = gaia_stars(
            [
                gaia_star(1, *p[1], 5.0),
                gaia_star(2, *p[2], 6.0),
                gaia_star(3, *p[3], 7.0),
                gaia_star(4, *p[4], 8.0),
                gaia_star(6, *p[8], 2.6),
            ]
        )
        gaia_rows = gaia.engine_rows(
            gaia.join_fidelity(stored, fidelity([(2, 0.2)])), NO_BEST
        )
        named = gaia.join_fidelity(
            gaia_stars(
                [
                    # No 5σ parallax.
                    gaia_star(11, *p[5], 3.0) | {"parallax": None},
                    # No SIMBAD star claims it.
                    gaia_star(12, *p[7], 9.0) | {"parallax": 0.1},
                    # The companion of Gaia 6, and the best neighbour of HIP 60.
                    gaia_star(16, *offset(*p[8], 0.6, 0), 7.8) | {"parallax": None},
                ]
            ),
            fidelity([]),
        )
        rows_named = named_rows(named)
        hip, rough = hipparcos.engine_rows(
            hip_stars(
                [
                    {"hip": 10, "ra": p[1][0], "dec": p[1][1], "v_mag": 5.0},
                    {
                        "hip": 60,
                        "ra": p[8][0],
                        "dec": p[8][1],
                        "v_mag": 2.6,
                        "b_v": 0.0,
                    },
                    # Rough, with a magnitude that matches no Gaia star.
                    {
                        "hip": 70,
                        "ra_hms": hms(p[4][0]),
                        "dec_dms": dms(p[4][1]),
                        "v_mag": 4.0,
                        "b_v": 0.0,
                    },
                ]
            ),
            BestNeighbours(np.array([1, 16]), np.array([10, 60])).without(
                frozenset({60})
            ),
        )
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(101, *p[1], "* alf Tau", "HIP 10", "Gaia DR3 1"),
                # Gaia flags it as spurious.
                star(102, *p[2], "V* V354 Cep", "Gaia DR3 2"),
                # Its Gaia id is not in Gaia DR3.
                star(103, *offset(*p[3], 0.2, 0), "HD 5", "Gaia DR3 13", G=7.05),
                # SIMBAD knows HIP 70 is this Gaia star.
                star(104, *p[4], "* 94 Aqr", "HIP 70", "Gaia DR3 4"),
                star(105, *p[5], "* eta Car", "Gaia DR3 11"),
                # Not in Gaia: a new star.
                star(106, *p[6], "WR 104", V=13.0),
                star(107, *p[8], "* bet Lep", "HIP 60", "Gaia DR3 6"),
                star(108, *offset(*p[8], 0.6, 0), "* bet Lep B", "Gaia DR3 16"),
            ],
            iau=[("Dilmun", 105)],
        )
        stars = SimbadList.read(directory)
        assert simbad.disputed_hip(stars, stars.handed(), {"10": "1", "60": "16"}) == {
            60
        }
        simbad_rows, simbad_hip_rows = simbad.engine_rows(
            stars, stars.handed(), set(), {"10": "1"}, {}
        )
        name_rows = names.engine_rows(
            {},
            write_names(tmp_path / "names.json", [iau_entry("Dilmun")]),
            simbad=simbad.iau_rows(stars, stars.handed(), simbad_rows),
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [gaia_rows])
            run.add(GAIA_DR3_NAMED, [rows_named])
            run.add(HIPPARCOS, [hip])
            run.add(HIPPARCOS_1997, [rough])
            run.add(SIMBAD, [simbad_rows])
            run.add(SIMBAD_HIP, [simbad_hip_rows])
            run.add(IAU_WGSN, [name_rows])
            result = run.commit()

        counts = result.entry["counts"]
        assert counts["conflicts"] == 0
        assert counts["joined"] == 1
        assert "joins: 1\n  simbad/oid/104" in result.report
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        def gaia_id(value: int) -> int:
            return id_of("gaia", "dr3", value)

        assert id_of("simbad", "oid", 101) == gaia_id(1) == id_of("hip", "2007", 10)
        # A SIMBAD star mints the Gaia star that the fidelity cut held back.
        assert id_of("simbad", "oid", 102) == gaia_id(2) != 0
        # An unknown Gaia id does not stop a match by position.
        assert id_of("simbad", "oid", 103) == gaia_id(3) == gaia_id(13) != 0
        assert gaia_id(12) == 0
        assert id_of("simbad", "oid", 104) == gaia_id(4) == id_of("hip", "2007", 70)
        assert id_of("simbad", "oid", 105) == gaia_id(11) != 0
        assert id_of("iau", "wgsn", "Dilmun") == gaia_id(11)
        # SIMBAD and the magnitude put HIP 60 on Gaia 6, not on its best
        # neighbour.
        assert id_of("hip", "2007", 60) == gaia_id(6) == id_of("simbad", "oid", 107)
        assert gaia_id(16) == id_of("simbad", "oid", 108) not in {0, gaia_id(6)}
        alone = id_of("simbad", "oid", 106)
        assert alone not in {0, *(gaia_id(n) for n in (1, 2, 3, 4, 11))}

        meta = {row["id"]: row for row in table_rows(root, "metadata").to_pylist()}
        point = {row["id"]: row for row in table_rows(root, "point-source").to_pylist()}
        assert meta[gaia_id(1)]["name"] == "Alpha Tauri"
        assert meta[gaia_id(2)]["name"] == "V354 Cephei"
        assert meta[gaia_id(4)]["name"] == "94 Aquarii"
        assert meta[gaia_id(11)]["name"] == "Dilmun"
        assert meta[alone]["name"] == "WR 104"
        assert point[gaia_id(11)]["astrometry_source"] == "gaia-dr3-named"
        assert point[gaia_id(11)]["gaia_photometry_source"] == "gaia-dr3-named"
        assert point[gaia_id(4)]["astrometry_source"] == "gaia-dr3"
        assert point[alone]["astrometry_source"] == "simbad"
        assert point[alone]["epoch"] == 2000.0
        assert point[alone]["simbad_v_mag"] == 13.0
        assert point[alone]["simbad_photometry_source"] == "simbad"
        # SIMBAD gives Alpha Tauri no photometry, but its object type marks it.
        assert point[gaia_id(1)]["simbad_v_mag"] is None
        assert point[gaia_id(1)]["simbad_otype"] == "*"
        assert point[gaia_id(1)]["simbad_photometry_source"] == "simbad"
        assert result.entry["sources"][1]["rows"] == 3
        assert counts["unminted"] == 1

    def test_a_hip_claim_never_takes_another_rows_star(self, tmp_path):
        root = tmp_path / "root"
        a, b = at(60), offset(*at(60), 3, 90)
        stored = gaia_stars([gaia_star(1, *a, 6.0), gaia_star(2, *b, 6.2)])
        gaia_rows = gaia.engine_rows(gaia.join_fidelity(stored, fidelity([])), NO_BEST)
        # No best neighbour: HIP 50 matches Gaia 2 by position.
        hip, _ = hipparcos.engine_rows(
            hip_stars([{"hip": 50, "ra": b[0], "dec": b[1], "v_mag": 6.2}]), NO_BEST
        )
        # SIMBAD gives HIP 50 to the star of Gaia 1. The lower oid goes first.
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(1, *a, "HD 1A", "HIP 50", "Gaia DR3 1"),
                star(2, *b, "HD 1B", "Gaia DR3 2"),
            ],
        )
        listed = SimbadList.read(directory)
        simbad_rows, simbad_hip_rows = simbad.engine_rows(
            listed, listed.handed(), set(), {}, {}
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [gaia_rows])
            run.add(HIPPARCOS, [hip])
            run.add(SIMBAD, [simbad_rows])
            run.add(SIMBAD_HIP, [simbad_hip_rows])
            result = run.commit()
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        assert result.entry["counts"]["minted"] == 2
        assert result.entry["counts"]["joined"] == 0
        assert id_of("simbad", "oid", 1) == id_of("gaia", "dr3", 1)
        assert id_of("simbad", "oid", 2) == id_of("gaia", "dr3", 2)
        assert id_of("hip", "2007", 50) == id_of("gaia", "dr3", 2)
        assert "already holds an id of simbad oid" in result.report


class TestStarsWithoutMagnitude:
    """A SIMBAD star without an optical magnitude and a Gaia star beside it."""

    def test_a_close_gcvs_star_matches(self, tmp_path):
        p = {key: at(60 * key) for key in range(1, 4)}
        stored = gaia_stars(
            [
                gaia_star(1, *p[1], 13.0),
                gaia_star(2, *p[2], 11.2),
                gaia_star(3, *p[3], 14.0),
            ]
        )
        gaia_rows = gaia.engine_rows(gaia.join_fidelity(stored, fidelity([])), NO_BEST)
        directory = write_simbad(
            tmp_path / "simbad",
            [
                # An eclipsing binary that SIMBAD gives no magnitude.
                star(101, *offset(*p[1], 0.1, 0), "V* V575 CrA", otype="EB*"),
                # A companion at the position of its primary.
                star(102, *offset(*p[2], 0.1, 0), "NAME TOI-2543B", otype="BD?"),
                # Too far for a match without magnitudes.
                star(103, *offset(*p[3], 0.5, 0), "V* V762 Sco", otype="RR*"),
            ],
        )
        listed = SimbadList.read(directory)
        rows, _ = simbad.engine_rows(listed, listed.handed(), set(), {}, {})
        assert rows["match_kind"].to_pylist() == ["star", simbad.UNSEEN, "star"]
        root = tmp_path / "root"
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [gaia_rows])
            run.add(SIMBAD, [rows])
            run.commit()
        registry = Registry(root)

        def lookup(catalogue: str, release: str, value: int) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        assert lookup("simbad", "oid", 101) == lookup("gaia", "dr3", 1)
        assert lookup("simbad", "oid", 102) != lookup("gaia", "dr3", 2)
        assert lookup("simbad", "oid", 103) != lookup("gaia", "dr3", 3)


class TestSystemsOfSimbad:
    """Components by designation, Hipparcos points, swapped best neighbours."""

    def stars(self, tmp_path: Path, objects: list[dict]) -> SimbadList:
        return SimbadList.read(write_simbad(tmp_path / "simbad", objects))

    def test_a_designation_names_the_components_of_a_system(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(1, RA, DEC, "* alf Gem", "HIP 36850", otype="**", V=1.6),
                star(2, RA, DEC, "* alf Gem A", "HIP 36850A", V=1.9),
                star(3, RA, DEC + 0.001, "* alf Gem B", "Gaia DR3 892", V=3.0),
                # Without its A listed, the object is the primary star itself.
                star(4, 10.0, 10.0, "* alf CMa", "HIP 32349", otype="SB*"),
                star(5, 10.0, 10.001, "* alf CMa B", "Gaia DR3 294", otype="WD*"),
                star(6, 20.0, 20.0, "* alf Cru", "HIP 60718", otype="SB*"),
                star(7, 20.0, 20.0, "* alf01 Cru", V=1.3),
                star(8, 20.0, 20.001, "* alf02 Cru", V=1.6),
            ],
        )
        assert stars.children == {1: [2, 3], 6: [7, 8]}
        assert stars.is_row(4) and not stars.is_row(1) and not stars.is_row(6)
        # The system hands its HIP number to its brightest component.
        assert stars.primary(1) == 2 and stars.primary(6) == 7
        assert stars.handed() == {2: {"hip": "36850"}, 7: {"hip": "60718"}}

    def test_a_hipparcos_point_holds_its_close_components(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(6, 20.0, 20.0, "* alf Cru", "HIP 60718", otype="SB*"),
                star(7, 20.0, 20.0, "* alf01 Cru", V=1.3),
                # 3.6″ away: inside the Hipparcos point.
                star(8, 20.0, 20.001, "* alf02 Cru", V=1.6),
                # Too far, and too faint.
                star(9, 20.0, 20.01, "* alf Cru C", V=4.0),
                star(10, 20.0, 20.0005, "* alf Cru D", V=9.0),
            ],
        )
        assert sorted(stars.children[6]) == [7, 8, 9, 10]
        stars.hold({"60718": 0.8})
        assert stars.inside == {8: 7}
        assert not stars.is_row(8) and stars.primary(8) == 7
        rows, _ = simbad.engine_rows(
            stars, stars.handed(), set(), {}, {"60718": (20.0, 20.0)}
        )
        assert rows["catalogue_id"].to_pylist() == ["7", "9", "10"]
        assert claims_of(rows)[0] == ["hip/2007/60718"]

    def test_a_far_component_takes_no_number(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(1, 300.0, -60.0, "L  119-21", "HIP 111766", otype="**"),
                star(2, 300.0, -60.0, "L  119-21 A", V=11.9),
                # 13″ away and brighter.
                star(3, 300.0, -60.0036, "L  119-21 C", "Gaia DR3 639", G=10.9),
            ],
        )
        assert stars.primary(1) == 3
        assert stars.handed() == {}

    def test_the_primary_light_keeps_its_best_neighbour(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(1, RA, DEC, "* alf Gem", "HIP 36850", otype="**", V=1.6),
                star(2, RA, DEC, "* alf Gem A", V=1.9),
                star(3, RA, DEC + 0.001, "* alf Gem B", "Gaia DR3 892", V=3.0),
                star(4, 10.0, 10.0, "* zet Her", "HIP 81693", otype="SB*"),
                star(5, 10.0, 10.0, "* zet Her A", "Gaia DR3 345", G=2.7),
                star(6, 10.0, 10.0001, "* zet Her B", "Gaia DR3 730", G=2.8),
            ],
        )
        # Gaia pairs HIP 36850 with B, which SIMBAD keeps apart from it.
        assert simbad.disputed_hip(stars, stars.handed(), {"36850": "892"}) == {36850}
        # HIP 81693 has no best neighbour: it takes its primary's source.
        assert simbad.handed_neighbours(stars, stars.handed(), {"36850": "892"}) == {
            81693: 345
        }
        # A source that another HIP number has stays with that number.
        assert simbad.handed_neighbours(stars, stars.handed(), {"1": "345"}) == {}

    def test_a_number_that_no_row_takes_keeps_its_best_neighbour(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                # Two HIP numbers: the object takes neither.
                star(1, RA, DEC, "HD   675A", "HIP 883", "HIP 884", "Gaia DR3 77"),
                star(2, 10.0, 10.0, "HD 1", "HIP 900", "Gaia DR3 78"),
                star(3, 10.0, 10.001, "HD 1B", "Gaia DR3 79"),
            ],
        )
        assert simbad.disputed_hip(stars, stars.handed(), {"883": "77"}) == frozenset()
        # A row that takes the number still disputes it.
        assert simbad.disputed_hip(stars, stars.handed(), {"900": "79"}) == {900}

    def test_every_row_that_takes_a_number_is_checked(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(1, RA, DEC, "* nu Sco", "HIP 910", otype="**"),
                # The system hands HIP 910 to its primary, which has no Gaia id.
                star(2, RA, DEC, "* nu Sco A", V=4.0),
                star(3, 10.0, 10.0, "HD 11", "HIP 910", "Gaia DR3 81"),
            ],
        )
        handed = stars.handed()
        assert handed == {2: {"hip": "910"}}
        # The second row has another Gaia id.
        assert simbad.disputed_hip(stars, handed, {"910": "80"}) == {910}
        # The second row has the best neighbour.
        assert simbad.disputed_hip(stars, handed, {"910": "81"}) == frozenset()

    def test_a_simbad_type_gives_the_class(self, tmp_path):
        stars = self.stars(
            tmp_path,
            [
                star(1, RA, DEC, "* alf CMa B", "Gaia DR3 294", otype="WD*"),
                star(2, RA, DEC + 1, "Luhman 16", "Gaia DR3 40", otype="BD*"),
                star(3, RA, DEC + 2, "* alf CMa", "HIP 32349", otype="SB*"),
            ],
        )
        rows, _ = simbad.engine_rows(stars, stars.handed(), set(), {}, {})
        assert rows["class"].to_pylist() == ["white dwarf", "brown dwarf", "star"]

    def test_best_neighbours_with_pairs(self):
        best = gaia.BestNeighbours(np.array([5, 9]), np.array([50, 90]))
        found = best.with_pairs({70: 7})
        assert found.source_id.tolist() == [5, 7, 9]
        assert found.source_of() == {50: 5, 70: 7, 90: 9}
