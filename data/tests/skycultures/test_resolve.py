"""Tests for resolving sky-culture objects to extrasolar IDs."""

import csv
from pathlib import Path

import pytest

from space_map_data.extrasolar.registry import Registry
from space_map_data.skycultures.refs import (
    Ref,
    bucur_ref,
    stellarium_name,
    stellarium_point,
)
from space_map_data.skycultures.resolve import (
    COMPONENT,
    DEEP_SKY,
    GAIA,
    HIP,
    MATCHED,
    NO_STAR_NUMBER,
    NOT_IN_REGISTRY,
    NOT_IN_SIMBAD,
    SOLAR_SYSTEM,
    UNKNOWN,
    VIA_GAIA,
    VIA_HD,
    VIA_HIP,
    VIA_PARENT,
    Lookup,
    Matcher,
    SimbadCrosswalk,
    registry_ids,
    wanted,
)
from tests.skycultures.registry import write_registry


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def simbad_files(directory: Path) -> Path:
    """A crosswalk with one star for each route and a cluster."""
    directory.mkdir(parents=True, exist_ok=True)
    names = {
        "* by hip": "1",
        "* by gaia": "2",
        "* by hd": "3",
        "* component A": "4",
        "* no number": "5",
        "M  45": "6",
        "* lost": "7",
        "NAME Milky Way": "",
    }
    _write(directory / "names.csv", ["name", "oid"], [[k, v] for k, v in names.items()])
    objects = {
        "1": ("* by hip", "PM*", "HIP 100|Gaia DR3 900"),
        "2": ("* by gaia", "*", "Gaia DR3 200"),
        "3": ("* by hd", "*", "HD  300|HD 300"),
        "4": ("* component A", "PM*", "WDS J1A"),
        "5": ("* no number", "*", "TYC 1-2-3"),
        "6": ("Cl Melotte   22", "OpC", "M  45"),
        "7": ("* lost", "*", "HIP 999"),
        "40": ("* component", "**", "HIP 400"),
    }
    _write(
        directory / "basic.csv",
        ["oid", "main_id", "otype", "ra", "dec", "sp_type"],
        [[oid, main, otype, "0", "0", ""] for oid, (main, otype, _) in objects.items()],
    )
    _write(
        directory / "ids.csv",
        ["oidref", "ids"],
        [[oid, ids] for oid, (_, _, ids) in objects.items()],
    )
    _write(
        directory / "h_link.csv", ["child", "parent", "membership"], [["4", "40", ""]]
    )
    _write(
        directory / "otypedef.csv",
        ["otype", "path"],
        [["*", "*"], ["PM*", "* > PM*"], ["**", "* > **"], ["OpC", "Cl* > OpC"]],
    )
    return directory


@pytest.fixture
def lookup(tmp_path) -> Lookup:
    crosswalk = SimbadCrosswalk.read(simbad_files(tmp_path / "simbad"))
    return Lookup(
        hip={"100": 11, "400": 44, "32349": 77},
        gaia={"900": 99, "200": 22, "5350358584482202880": 55},
        hd={"300": 33},
        simbad=crosswalk,
    )


class TestCrosswalk:
    """The numbers of each SIMBAD object, and of the systems that hold it."""

    def test_numbers_and_parents(self, lookup):
        assert lookup.simbad is not None
        star = lookup.simbad.get("* component A")
        assert star is not None
        assert (star.hip, star.gaia, star.hd, star.parent_hip) == (
            None,
            None,
            None,
            ("400",),
        )
        assert lookup.simbad.get("* by hd").hd == "300"

    def test_cluster_is_not_a_star_and_unknown_name_is_none(self, lookup):
        assert not lookup.simbad.get("M  45").is_star
        assert lookup.simbad.get("NAME Milky Way") is None

    def test_wanted_numbers(self, lookup):
        refs = [
            stellarium_point(32349),
            stellarium_name("HIP 5 B"),
            bucur_ref("* by hd"),
        ]
        refs += [bucur_ref("* component A"), stellarium_point("200")]
        hips, gaias, hds = wanted(refs, lookup.simbad)
        assert hips == {"32349", "400"}
        assert gaias == {"200"}
        assert hds == {"300"}


class TestResolve:
    """Every kind of object, and the reason when it has no ID."""

    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            (stellarium_point(32349), (77, MATCHED)),
            (stellarium_point(1), (None, NOT_IN_REGISTRY)),
            (stellarium_name("HIP 32349 A"), (77, MATCHED)),
            (stellarium_name("HIP 32349 B"), (None, COMPONENT)),
            (stellarium_point("5350358584482202880"), (55, MATCHED)),
            (stellarium_point("DSO:M44"), (None, DEEP_SKY)),
            (stellarium_name("NAME Sun"), (None, SOLAR_SYSTEM)),
            (stellarium_name("coalsack nebula"), (None, UNKNOWN)),
            (bucur_ref("NAME Milky Way"), (None, NOT_IN_SIMBAD)),
            (bucur_ref("* no number"), (None, NO_STAR_NUMBER)),
            (bucur_ref("* lost"), (None, NOT_IN_REGISTRY)),
        ],
    )
    def test_outcome(self, lookup, ref, expected):
        id_, outcome, _ = lookup.resolve(ref)
        assert (id_, outcome) == expected

    @pytest.mark.parametrize(
        ("name", "id_", "via"),
        [
            ("* by hip", 11, VIA_HIP),
            ("* by gaia", 22, VIA_GAIA),
            ("* by hd", 33, VIA_HD),
            ("* component A", 44, VIA_PARENT),
        ],
    )
    def test_simbad_routes(self, lookup, name, id_, via):
        assert lookup.resolve(bucur_ref(name)) == (id_, MATCHED, {"via": via})

    def test_simbad_cluster_keeps_its_main_identifier(self, lookup):
        assert lookup.resolve(bucur_ref("M  45")) == (
            None,
            DEEP_SKY,
            {
                "designation": "Cl Melotte   22",
                "simbad": {"main_id": "Cl Melotte   22", "otype": "OpC"},
            },
        )

    def test_disagreeing_numbers_are_listed(self, lookup):
        assert lookup.disagreements() == ["* by hip: HIP 100 is 11, Gaia DR3 900 is 99"]


class TestMatcher:
    """Unresolved objects keep their reference; counts go by place."""

    def test_point_forms_and_summary(self, lookup):
        matcher = Matcher(lookup)
        assert matcher(stellarium_point(32349), "lines") == 77
        assert matcher(stellarium_point("DSO:M44"), "lines") == {
            "ref": "DSO:M44",
            "reason": DEEP_SKY,
            "designation": "M44",
        }
        assert matcher(bucur_ref("* component A"), "names") == 44
        summary = matcher.summary()
        assert summary["refs"] == 3 and summary["matched"] == 2
        assert summary["unresolved"] == {DEEP_SKY: 1}
        assert summary["places"] == {
            "lines": {DEEP_SKY: 1, MATCHED: 1},
            "names": {MATCHED: 1},
        }
        assert summary["simbad_routes"] == {VIA_PARENT: 1}
        assert matcher.unresolved == [
            {
                "place": "lines",
                "ref": "DSO:M44",
                "reason": DEEP_SKY,
                "designation": "M44",
            }
        ]


class TestRegistryIds:
    """Numbers resolve through the claims of every region."""

    def test_claims_in_several_regions(self, tmp_path):
        minted = write_registry(
            tmp_path,
            [
                (10.0, 20.0, [("hip", "2007", "1"), ("gaia", "dr3", "71")]),
                (200.0, -60.0, [("hip", "2007", "2")]),
            ],
        )
        registry = Registry(tmp_path)
        with registry.reader():
            assert registry_ids(registry, HIP, {"1", "2", "3"}) == {
                "1": minted[0],
                "2": minted[1],
            }
            assert registry_ids(registry, GAIA, {"71"}) == {"71": minted[0]}
            assert registry_ids(registry, GAIA, set()) == {}

    def test_ref_text_is_kept_for_unresolved(self, lookup):
        matcher = Matcher(lookup)
        point = matcher(Ref("HIP  1", stellarium_name("HIP 1").kind, "1"), "names")
        assert point == {"ref": "HIP  1", "reason": NOT_IN_REGISTRY}
