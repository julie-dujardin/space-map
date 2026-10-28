"""Tests for the star families of the Metadata tiles."""

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.constants.stars import families as rules
from space_map_data.export.extrasolar import families
from space_map_data.extrasolar.tables import POINT_SOURCE


def names(mask) -> set[str]:
    """The families of `mask`. The root is in TestRoot only."""
    return {
        f
        for f in rules.FAMILIES
        if int(mask) & int(families.BIT[f]) and f != rules.ROOT_FAMILY
    }


def rows(*stars: dict) -> pa.Table:
    """Point source rows with only the columns that the families read."""
    schema = POINT_SOURCE.schema
    columns = [name for name in families.COLUMNS if name != "id"]
    return pa.table(
        {
            "id": pa.array(range(1, len(stars) + 1), pa.int64()),
            **{
                name: pa.array([s.get(name) for s in stars], schema.field(name).type)
                for name in columns
            },
        }
    )


def classify(*stars: dict, classes: list[str] | None = None):
    star_classes = pa.array(classes or ["star"] * len(stars), pa.string())
    published, estimated = families.masks(rows(*stars), star_classes)
    return [names(m) for m in published], [names(m) for m in estimated]


GIANT_FLAME = {"evolstage_flame": 600, "mass_flame": 1.5, "flags_flame": "10"}
DWARF_FLAME = {"evolstage_flame": 250, "mass_flame": 1.0, "flags_flame": "00"}


class TestParseSpectralType:
    """The letter, stage and other families of an MK spectral type."""

    @pytest.mark.parametrize(
        ("text", "letter", "stage"),
        [
            ("G2V", "G", "main-sequence"),
            ("K2III", "K", "giant"),
            ("K0III-IV", "K", "giant"),
            ("G8/K0III", "G", "giant"),
            ("F5 IV-V", "F", "subgiant"),
            ("M1.5Ve", "M", "main-sequence"),
            ("B1Ia+", "B", "hypergiant"),
            ("G0 0-Ia", "G", "hypergiant"),
            ("O9.7Iab", "O", "supergiant"),
            ("K3IIb", "K", "bright-giant"),
            ("M2VI", "M", "subdwarf"),
            ("sdB", "B", "subdwarf"),
            ("sdB2VIIHe3", "B", "subdwarf"),
            ("sdOB", "B", "subdwarf"),
            ("dM3", "M", "main-sequence"),
            ("gK0", "K", "giant"),
            ("kA2hA5mA7V", "A", "main-sequence"),
            ("hF5", "F", None),
            ("K0", "K", None),
            ("DA3.2", "D", None),
            ("DAV4.2", "D", None),
            ("DBV", "D", None),
            ("WC8+O9I", "W", None),
            ("C-N5", "C", None),
            ("C5,4", "C", None),
            ("S3/2", "S", None),
            ("R0", "R", None),
            ("L5", "L", None),
            ("T7.5", "T", None),
            ("K0III+A2V", "K", "giant"),
        ],
    )
    def test_letter_and_stage(self, text, letter, stage):
        found_letter, found_stage, _ = families.parse_spectral_type(text)
        assert (found_letter, found_stage) == (letter, stage)

    @pytest.mark.parametrize("text", ["O-rich", "CEMP-s", "Ce", "kA5mF0", "?"])
    def test_no_class(self, text):
        assert families.parse_spectral_type(text)[:2] == (None, None)

    @pytest.mark.parametrize(
        ("text", "family"),
        [
            ("PSR", "pulsar"),
            ("LBV", "luminous-blue-variable"),
            ("PG1159", "white-dwarf"),
            ("K1Ba2", "barium-star"),
            ("G8IIIBa0.3", "barium-star"),
        ],
    )
    def test_other_families(self, text, family):
        assert names(families.parse_spectral_type(text)[2]) == {family}

    @pytest.mark.parametrize("text", ["kA6hF1mF1(IV)Ba", "C5,3e_Ba5"])
    def test_ba_of_an_am_or_carbon_star_is_no_barium_star(self, text):
        assert families.parse_spectral_type(text)[2] == 0


class TestPublished:
    """Families from catalogued classifications only."""

    def test_spectral_type_with_its_parents(self):
        published, estimated = classify({"simbad_sp_type": "G2V"})
        assert published[0] == {"g-type-main-sequence", "main-sequence", "dwarf"}
        assert estimated[0] == set()

    def test_simbad_type_comes_before_hipparcos(self):
        published, _ = classify({"simbad_sp_type": "K2III", "sp_type": "K2V"})
        assert published[0] == {"giant", "red-giant"}

    def test_host_type_is_last(self):
        published, _ = classify({"sp_type": "M4V", "host_spectral_type": "K"})
        assert "red-dwarf" in published[0]
        published, _ = classify({"host_spectral_type": "M4V"})
        assert "red-dwarf" in published[0]

    def test_a_bright_giant_is_a_giant(self):
        published, _ = classify({"sp_type": "K3IIb"}, {"sp_type": "B2II"})
        assert published[0] == {"bright-giant", "red-giant", "giant"}
        assert published[1] == {"bright-giant", "blue-giant", "giant"}

    def test_an_object_type_red_giant_has_the_giant_stage(self):
        published, estimated = classify(
            {"simbad_otype": "RG*", "spectraltype_esphs": "K", "flags_esphs": "02000"}
            | DWARF_FLAME
        )
        assert published[0] == {"red-giant", "giant"}
        assert estimated[0] == set()

    def test_a_letter_family_keeps_its_stage_to_its_letter(self):
        published, _ = classify(
            {"simbad_otype": "RG*", "sp_type": "B"},
            {"simbad_otype": "RG*", "sp_type": "K"},
        )
        assert published[0] == {"red-giant", "giant"}
        assert published[1] == {"red-giant", "giant"}

    def test_of_a_spectral_type(self):
        assert families.of_spectral_type("G2V") == [
            "classification",
            "dwarf",
            "g-type-main-sequence",
            "main-sequence",
        ]
        assert families.most_specific(families.of_spectral_type("G2V")) == [
            "g-type-main-sequence"
        ]
        assert families.most_specific(families.of_spectral_type("K3IIb")) == [
            "bright-giant",
            "red-giant",
        ]

    def test_colour_supergiants(self):
        published, _ = classify(
            {"sp_type": "M2Iab"}, {"sp_type": "B8Ia"}, {"sp_type": "G0Ia+"}
        )
        assert published[0] == {"red-supergiant", "supergiant"}
        assert published[1] == {"blue-supergiant", "supergiant"}
        assert published[2] == {"yellow-hypergiant", "hypergiant"}

    def test_simbad_object_types(self):
        published, _ = classify(
            {"simbad_otype": "Mi*"},
            {"simbad_otype": "Psr"},
            {"simbad_otype": "EB*"},
            {"simbad_otype": "WD?"},
        )
        assert published[0] == {
            "mira-variable",
            "asymptotic-giant-branch",
            "variable-star",
        }
        assert published[1] == {"pulsar", "neutron-star"}
        assert published[2] == {"variable-star"}
        assert published[3] == set()

    def test_an_object_type_stage_joins_the_mk_letter(self):
        published, _ = classify(
            {"simbad_sp_type": "K0", "simbad_otype": "MS*"},
            {"simbad_sp_type": "B1", "simbad_otype": "sg*"},
        )
        assert published[0] == {"k-type-main-sequence", "main-sequence", "dwarf"}
        assert published[1] == {"blue-supergiant", "supergiant"}

    def test_metadata_class(self):
        published, _ = classify({}, classes=["brown dwarf"])
        assert published[0] == {"brown-dwarf", "dwarf"}

    def test_sources_add_up(self):
        published, _ = classify({"sp_type": "K1III", "simbad_otype": "LP*"})
        assert published[0] == {"giant", "red-giant", "variable-star"}


class TestEstimated:
    """Families that need a Gaia estimate."""

    def test_letter_and_stage_from_gaia(self):
        published, estimated = classify(
            {"spectraltype_esphs": "K", "flags_esphs": "02000"} | DWARF_FLAME
        )
        assert published[0] == set()
        assert estimated[0] == {"k-type-main-sequence", "main-sequence", "dwarf"}

    def test_published_letter_with_an_estimated_stage(self):
        published, estimated = classify(
            {"sp_type": "K0", "spectraltype_esphs": "M", "flags_esphs": "01000"}
            | DWARF_FLAME
        )
        assert published[0] == set()
        assert estimated[0] == {"k-type-main-sequence", "main-sequence", "dwarf"}

    def test_a_published_stage_stops_the_estimates(self):
        published, estimated = classify(
            {"sp_type": "K2III", "spectraltype_esphs": "G", "flags_esphs": "01000"}
            | DWARF_FLAME
        )
        assert published[0] == {"giant", "red-giant"}
        assert estimated[0] == set()

    def test_a_published_white_dwarf_stops_the_estimates(self):
        _, estimated = classify(
            {
                "simbad_otype": "WD*",
                "spectraltype_esphs": "A",
                "flags_esphs": "01000",
                "in_oba_golden_sample": True,
            }
            | DWARF_FLAME
        )
        assert estimated[0] == set()

    def test_a_published_variable_does_not_stop_them(self):
        published, estimated = classify(
            {"simbad_otype": "EB*", "spectraltype_esphs": "G", "flags_esphs": "03000"}
            | DWARF_FLAME
        )
        assert published[0] == {"variable-star"}
        assert estimated[0] == {"g-type-main-sequence", "main-sequence", "dwarf"}

    def test_hot_letters_need_the_golden_sample(self):
        star = {
            "spectraltype_esphs": "B",
            "flags_esphs": "01000",
            "teff_gspphot": 15_000,
        } | DWARF_FLAME
        _, estimated = classify(star, star | {"in_oba_golden_sample": True})
        assert estimated[0] == {"main-sequence", "dwarf"}
        assert estimated[1] == {"b-type-main-sequence", "main-sequence", "dwarf"}

    def test_a_hot_letter_needs_a_flame_temperature_that_fits(self):
        hot = {"in_oba_golden_sample": True, "flags_esphs": "01000"} | DWARF_FLAME
        published, estimated = classify(
            hot | {"spectraltype_esphs": "B", "teff_gspphot": 8_000},
            hot | {"spectraltype_esphs": "O", "teff_gspphot": 20_000},
            hot | {"spectraltype_esphs": "A", "teff_gspphot": 8_000},
            {"sp_type": "B5", "teff_gspphot": 8_000} | DWARF_FLAME,
        )
        assert estimated[0] == set()
        assert estimated[1] == set()
        assert estimated[2] == {"a-type-main-sequence", "main-sequence", "dwarf"}
        assert (published[3], estimated[3]) == (set(), set())

    def test_tag_quality(self):
        hot = {"in_oba_golden_sample": True, "teff_gspphot": 15_000}
        _, estimated = classify(
            {"spectraltype_esphs": "K", "flags_esphs": "09000"} | DWARF_FLAME,
            {"spectraltype_esphs": "CSTAR", "flags_esphs": "05000"},
            {"spectraltype_esphs": "CSTAR", "flags_esphs": "00000"},
            {"spectraltype_esphs": "K", "flags_esphs": "05000"} | DWARF_FLAME,
            {"spectraltype_esphs": "K", "flags_esphs": "04000"} | DWARF_FLAME,
            {"spectraltype_esphs": "B", "flags_esphs": "02000"} | hot | DWARF_FLAME,
        )
        assert estimated[0] == {"main-sequence", "dwarf"}
        assert estimated[1] == set()
        assert estimated[2] == {"carbon-star"}
        assert estimated[3] == {"main-sequence", "dwarf"}
        assert estimated[4] == {"k-type-main-sequence", "main-sequence", "dwarf"}
        assert estimated[5] == {"main-sequence", "dwarf"}

    def test_the_spectroscopic_flame_run_comes_first(self):
        _, estimated = classify(
            DWARF_FLAME
            | {
                "evolstage_flame_spec": 450,
                "mass_flame_spec": 1.2,
                "flags_flame_spec": "0",
            }
        )
        assert estimated[0] == {"subgiant"}

    def test_a_flame_giant_needs_a_mass_gaia_trusts(self):
        _, estimated = classify(
            GIANT_FLAME,
            GIANT_FLAME | {"mass_flame": 3.0},
            {"evolstage_flame": 250, "flags_flame": "20"},
        )
        assert estimated[0] == {"giant"}
        assert estimated[1] == set()
        assert estimated[2] == set()

    def test_an_estimated_letter_joins_an_object_type_stage(self):
        published, estimated = classify(
            {"simbad_otype": "MS*", "spectraltype_esphs": "K", "flags_esphs": "02000"}
        )
        assert published[0] == {"main-sequence", "dwarf"}
        assert estimated[0] == {"k-type-main-sequence"}

    def test_red_giant_from_letter_and_stage(self):
        _, estimated = classify(
            {"spectraltype_esphs": "M", "flags_esphs": "02000"} | GIANT_FLAME
        )
        assert estimated[0] == {"red-giant", "giant"}

    def test_white_dwarf_from_dsc(self):
        _, estimated = classify(
            {
                "classprob_dsc_combmod_whitedwarf": 0.9,
                "spectraltype_esphs": "A",
                "flags_esphs": "01000",
                "in_oba_golden_sample": True,
            }
            | DWARF_FLAME,
            {"classprob_dsc_combmod_whitedwarf": 0.9, "sp_type": "G2V"},
        )
        assert estimated[0] == {"white-dwarf", "dwarf"}
        assert estimated[1] == set()

    def test_emission_line_classes(self):
        published, estimated = classify(
            {"classlabel_espels": "TTauri"} | DWARF_FLAME,
            {"classlabel_espels": "beStar"},
            {"classlabel_espels": "wC", "sp_type": "WC8"},
        )
        assert estimated[0] == {"t-tauri", "pre-main-sequence"}
        assert estimated[1] == set()
        assert published[2] == {"wolf-rayet"}
        assert estimated[2] == set()

    def test_published_and_estimated_are_apart(self):
        published, estimated = classify(
            {"simbad_otype": "BY*", "sp_type": "K"} | DWARF_FLAME
        )
        assert published[0] == {"variable-star"}
        assert not published[0] & estimated[0]


class TestRoot:
    """The root family of stellar classification."""

    def test_every_other_family_is_below_the_root(self):
        for family in rules.FAMILIES:
            if family != rules.ROOT_FAMILY:
                closed = int(families._closed(family))
                assert closed & int(families.BIT[rules.ROOT_FAMILY]), family

    def test_a_star_with_a_family_is_in_the_root(self):
        root = families.BIT[rules.ROOT_FAMILY]
        published, estimated = families.masks(
            rows(
                {"sp_type": "G2V"},
                {"sp_type": "G2V"} | GIANT_FLAME,
                GIANT_FLAME,
                {},
            ),
            pa.array(["star"] * 4, pa.string()),
        )
        assert [bool(m & root) for m in published] == [True, True, False, False]
        assert [bool(m & root) for m in estimated] == [False, False, True, False]


class TestMasks:
    """Bits and counts."""

    def test_bit_n_is_family_n(self):
        assert families.BIT[rules.FAMILIES[0]] == 1
        assert families.BIT[rules.FAMILIES[5]] == 32

    def test_counts(self):
        masks = np.array(
            [families.BIT["dwarf"] | families.BIT["giant"], families.BIT["dwarf"], 0],
            np.uint64,
        )
        counts = families.counts(masks)
        assert counts[rules.FAMILIES.index("dwarf")] == 2
        assert counts[rules.FAMILIES.index("giant")] == 1
        assert counts.sum() == 3

    def test_every_rule_names_a_family(self):
        tables = (
            rules.LETTER_STAGE_FAMILIES,
            rules.LETTER_FAMILIES,
            rules.SPECTRAL_TYPE_WORDS,
            rules.OTYPE_FAMILIES,
            rules.CLASS_FAMILIES,
            rules.ELS_FAMILIES,
            rules.PARENTS,
        )
        named = {f for table in tables for value in table.values() for f in value}
        named |= set(rules.STATES) | set(rules.PARENTS)
        named |= set(rules.LUMINOSITY_CLASSES.values())
        assert named <= set(rules.FAMILIES)
