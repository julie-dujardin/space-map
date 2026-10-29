"""Tests for the star families of the Metadata tiles."""

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.constants.stars import families as rules
from space_map_data.extrasolar import families
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
DWARF_ESPHS = {"teff_esphs": 15_000, "logg_esphs": 4.0}
GIANT_ESPHS = {"teff_esphs": 15_000, "logg_esphs": 3.2}


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
            ("A0mA1Va", "A", "main-sequence"),
            ("A5mF2 (IV)", "A", "subgiant"),
            ("A3mB9.5IV", "A", "subgiant"),
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
            ("K5+III", "K", "giant"),
            ("B5+K3III", "B", None),
            ("G2_0", "G", "hypergiant"),
            ("K2_0-Ia", "K", "hypergiant"),
            ("F(6)V", "F", "main-sequence"),
            ("K(2)(III)", "K", "giant"),
            ("B(0/3)ne", "B", None),
            ("ON8.5V", "O", "main-sequence"),
            ("BC0.7Ia", "B", "supergiant"),
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

    def test_the_type_of_the_simbad_system_comes_after_simbad(self):
        system = {"simbad_system_sp_type": "M5Iae", "sp_type": "M3/M4II:"}
        published, _ = classify(system, system | {"simbad_sp_type": "M2V"})
        assert published[0] == {"supergiant", "red-supergiant"}
        assert published[1] == {"red-dwarf", "main-sequence", "dwarf"}

    def test_the_object_type_of_the_simbad_system(self):
        published, _ = classify(
            {"simbad_otype": "LP?", "simbad_system_otype": "s*r", "sp_type": "M3"}
        )
        assert published[0] == {"supergiant", "red-supergiant"}

    def test_a_white_dwarf_type_of_the_system_needs_gaia_to_agree(self):
        red = {"phot_bp_mean_mag": 15.0, "phot_rp_mean_mag": 13.2}
        blue = {"phot_bp_mean_mag": 15.0, "phot_rp_mean_mag": 14.8}
        system = {"simbad_system_sp_type": "DA2.4", "sp_type": "M1V"}
        published, _ = classify(
            system | red | {"classprob_dsc_combmod_whitedwarf": 0.0},
            system | red | {"classprob_dsc_combmod_whitedwarf": 0.9},
            system | blue,
            {"simbad_system_otype": "WD*"} | red,
        )
        assert published[0] == {"red-dwarf", "main-sequence", "dwarf"}
        assert published[1] == published[2] == {"white-dwarf", "dwarf"}
        assert published[3] == set()

    def test_a_white_dwarf_type_of_the_system_drops_only_its_own_column(self):
        red = {"phot_bp_mean_mag": 15.0, "phot_rp_mean_mag": 12.5}
        published, _ = classify(
            {"simbad_system_otype": "WD*", "simbad_system_sp_type": "M4.5V"} | red
        )
        assert published[0] == {"red-dwarf", "main-sequence", "dwarf"}

    @pytest.mark.parametrize(
        ("text", "composite"),
        [
            ("DA2+dM", True),
            ("G8/K0V+(F)", True),
            ("B1.5IV+(B2V)", True),
            ("sdB+?", True),
            ("K5+III", False),
            ("M2+V", False),
            ("B1Ia+", False),
        ],
    )
    def test_a_composite_type(self, text, composite):
        found = rules.COMPOSITE_SPECTRAL_TYPE.search(text) is not None
        assert found == composite

    def test_the_spectral_type_of_a_row(self):
        table = rows(
            {"simbad_system_sp_type": "DA", "sp_type": "M1V"},
            {"simbad_system_sp_type": "M5Iae", "sp_type": "M3/M4II:"},
            {"simbad_system_sp_type": "DA", "sp_type": "M1V"}
            | {"phot_bp_mean_mag": 15.0, "phot_rp_mean_mag": 13.2},
        )
        assert families.spectral_type(table).to_pylist() == ["DA", "M5Iae", "M1V"]

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
        tree = rules.FAMILIES, rules.PARENTS
        assert families.most_specific(families.of_spectral_type("G2V"), *tree) == [
            "g-type-main-sequence"
        ]
        assert families.most_specific(families.of_spectral_type("K3IIb"), *tree) == [
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

    def test_candidate_types_are_estimates(self):
        published, estimated = classify(
            {"simbad_otype": "BD?"},
            {"simbad_otype": "WD?"},
            {"simbad_otype": "BD?", "sp_type": "M4V"},
            {"host_simbad_otype": "WD?"},
            {"host_simbad_otype": "WD*"},
        )
        assert published[:2] == [set(), set()]
        assert estimated[0] == {"brown-dwarf", "dwarf"}
        assert estimated[1] == {"white-dwarf", "dwarf"}
        assert "brown-dwarf" not in published[2] | estimated[2]
        assert estimated[3] == {"white-dwarf", "dwarf"}
        # A host's confirmed type counts, also on a node, whose class does not.
        assert published[4] == {"white-dwarf", "dwarf"}

    def test_a_bright_candidate_is_no_brown_dwarf(self):
        star = {"simbad_otype": "BD?", "parallax": 20.0, "parallax_error": 0.1}
        star |= DWARF_FLAME
        _, estimated = classify(
            {**star, "phot_g_mean_mag": 11.0},
            {**star, "phot_g_mean_mag": 17.0},
            {**star, "phot_g_mean_mag": 11.0, "parallax_error": None},
            {**star, "phot_g_mean_mag": 20.5, "parallax": 0.4, "parallax_error": 1.0},
            # OGLE-2012-BLG-0358L: no 5σ parallax, but a catalogue distance.
            {
                "simbad_otype": "BD?",
                "phot_g_mean_mag": 17.76,
                "parallax": -0.15,
                "parallax_error": 0.16,
                "host_distance": 1760.0,
            },
            {**star, "phot_g_mean_mag": 17.0, "parallax": None, "distance": 20.0},
        )
        assert estimated[0] == {"main-sequence", "dwarf"}
        assert "brown-dwarf" in estimated[1]
        assert "brown-dwarf" in estimated[2]
        assert "brown-dwarf" in estimated[3]
        assert "brown-dwarf" not in estimated[4]
        assert "brown-dwarf" in estimated[5]

    def test_a_red_candidate_is_no_white_dwarf(self):
        red = {"phot_bp_mean_mag": 15.0, "phot_rp_mean_mag": 13.2}
        _, estimated = classify(
            {"simbad_otype": "WD?"} | red,
            {"simbad_otype": "WD?", "classprob_dsc_combmod_whitedwarf": 0.9} | red,
        )
        assert "white-dwarf" not in estimated[0]
        assert "white-dwarf" in estimated[1]

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

    @pytest.mark.parametrize(
        ("star", "families"),
        [
            ({"simbad_otype": "HB*", "simbad_sp_type": "A0V"}, {"horizontal-branch"}),
            ({"simbad_otype": "RG*", "sp_type": "G8IV"}, {"red-giant", "giant"}),
            ({"simbad_otype": "RG*", "sp_type": "G5Ib"}, {"red-giant", "giant"}),
            (
                {"simbad_otype": "TT*", "sp_type": "K3V"},
                {"t-tauri", "pre-main-sequence", "variable-star"},
            ),
            (
                {"simbad_otype": "Ae*", "sp_type": "B9V"},
                {"herbig-ae-be", "pre-main-sequence"},
            ),
            (
                {"simbad_otype": "BD*", "sp_type": "L3V"},
                {"l-dwarf", "brown-dwarf", "dwarf"},
            ),
            (
                {"simbad_otype": "BD*", "sp_type": "L3.V"},
                {"l-dwarf", "brown-dwarf", "dwarf"},
            ),
            ({"simbad_otype": "WR*", "sp_type": "Ofpe/WN9"}, {"wolf-rayet"}),
            ({"simbad_otype": "WR*", "sp_type": "O2If*/WN5"}, {"wolf-rayet"}),
            ({"simbad_otype": "WR*", "sp_type": "O2.5If*/WN6+OB"}, {"wolf-rayet"}),
            ({"simbad_system_otype": "WR*", "sp_type": "O2If*-WN6"}, {"wolf-rayet"}),
        ],
    )
    def test_an_object_type_beats_an_mk_class(self, star, families):
        published, estimated = classify(star)
        assert published[0] == families
        assert estimated[0] == set()

    def test_a_class_beats_an_mk_class_as_its_object_type_does(self):
        published, _ = classify({"sp_type": "L5V"}, classes=["brown dwarf"])
        assert published[0] == {"l-dwarf", "brown-dwarf", "dwarf"}

    @pytest.mark.parametrize(
        ("star", "families"),
        [
            (
                {"simbad_otype": "Y*O", "sp_type": "G8V"},
                {"g-type-main-sequence", "main-sequence", "dwarf"},
            ),
            (
                {"simbad_otype": "Or*", "sp_type": "B2Ve"},
                {"b-type-main-sequence", "main-sequence", "dwarf", "variable-star"},
            ),
            ({"simbad_otype": "TT*", "sp_type": "G5IV"}, {"subgiant", "variable-star"}),
            (
                {"simbad_otype": "Or*", "sp_type": "B1III"},
                {"blue-giant", "giant", "variable-star"},
            ),
            (
                {"simbad_otype": "s*b", "sp_type": "B1II"},
                {"blue-giant", "giant", "bright-giant"},
            ),
        ],
    )
    def test_an_mk_class_beats_an_object_type(self, star, families):
        published, _ = classify(star)
        assert published[0] == families

    @pytest.mark.parametrize(
        ("star", "kept"),
        [
            ({"simbad_otype": "BD*", "sp_type": "M8V"}, {"brown-dwarf", "red-dwarf"}),
            (
                {"simbad_otype": "BD*", "sp_type": "L1V"},
                {"brown-dwarf", "main-sequence"},
            ),
            (
                {"simbad_otype": "Or*", "sp_type": "O5V"},
                {"pre-main-sequence", "main-sequence"},
            ),
            (
                {"simbad_otype": "WR*", "sp_type": "O3If*"},
                {"wolf-rayet", "blue-supergiant"},
            ),
            (
                {"simbad_otype": "WR*", "sp_type": "B0I+WN"},
                {"wolf-rayet", "blue-supergiant"},
            ),
        ],
    )
    def test_too_little_evidence_keeps_both(self, star, kept):
        published, _ = classify(star)
        assert kept <= published[0]

    def test_sources_add_up(self):
        published, _ = classify({"sp_type": "K1III", "simbad_otype": "LP*"})
        assert published[0] == {"giant", "red-giant", "variable-star"}


class TestCatalogued:
    """The GCVS types give published families, the SPICY classes estimated
    ones."""

    @pytest.mark.parametrize(
        "vartype", ["UV", "UVN", "BY+UV", "UV+BY:", "UVN(YY)", "INST(YY)+UV"]
    )
    def test_a_gcvs_flare_type(self, vartype):
        published, _ = classify({"vartype_gcvs": vartype})
        assert published[0] == {"flare-star", "variable-star"}

    @pytest.mark.parametrize("vartype", ["UV:", "BY+UV:", "EA", "M", "UVN(YY):"])
    def test_an_uncertain_or_other_gcvs_type_gives_none(self, vartype):
        published, _ = classify({"vartype_gcvs": vartype})
        assert published[0] == set()

    @pytest.mark.parametrize(
        ("spicy_class", "found"),
        [
            ("ClassI", {"protostar"}),
            ("FS", {"protostar"}),
            ("ClassII", set()),
            ("uncertain", set()),
        ],
    )
    def test_spicy_classes(self, spicy_class, found):
        published, estimated = classify({"class_spicy": spicy_class})
        assert published[0] == set()
        assert estimated[0] == found

    def test_a_spicy_protostar_stops_the_flame_stage(self):
        published, estimated = classify({"class_spicy": "FS"} | DWARF_FLAME)
        assert published[0] == set()
        assert estimated[0] == {"protostar"}

    @pytest.mark.parametrize(
        ("label", "found"),
        [
            ("TTauri", {"t-tauri", "pre-main-sequence"}),
            ("HerbigStar", {"herbig-ae-be", "pre-main-sequence"}),
        ],
    )
    def test_an_esp_els_label_stops_a_spicy_protostar(self, label, found):
        _, estimated = classify({"classlabel_espels": label, "class_spicy": "FS"})
        assert estimated[0] == found

    def test_a_catalogued_stage_stops_a_spicy_protostar(self):
        published, estimated = classify({"sp_type": "K5V", "class_spicy": "ClassI"})
        assert "protostar" not in published[0] | estimated[0]


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
        star = {"spectraltype_esphs": "B", "flags_esphs": "01000"} | DWARF_FLAME
        star |= DWARF_ESPHS
        _, estimated = classify(star, star | {"in_oba_golden_sample": True})
        assert estimated[0] == {"main-sequence", "dwarf"}
        assert estimated[1] == {"b-type-main-sequence", "main-sequence", "dwarf"}

    def test_o_and_b_stages_come_from_esphs(self):
        hot = {"in_oba_golden_sample": True, "flags_esphs": "01000"} | DWARF_FLAME
        published, estimated = classify(
            hot | {"spectraltype_esphs": "B"} | GIANT_ESPHS,
            hot | {"spectraltype_esphs": "O", "teff_esphs": 35_000, "logg_esphs": 4},
            hot | {"spectraltype_esphs": "B"},
            hot | {"spectraltype_esphs": "A"} | GIANT_ESPHS,
            {"sp_type": "B5"} | DWARF_ESPHS,
        )
        assert estimated[0] == {"blue-giant", "giant"}
        assert estimated[1] == {"o-type-main-sequence", "main-sequence", "dwarf"}
        assert estimated[2] == set()
        assert estimated[3] == {"a-type-main-sequence", "main-sequence", "dwarf"}
        assert published[4] == set()
        assert estimated[4] == {"b-type-main-sequence", "main-sequence", "dwarf"}

    def test_esphs_needs_the_temperature_of_the_letter(self):
        _, estimated = classify(
            {"sp_type": "B2", "teff_esphs": 35_000, "logg_esphs": 4.0},
            {"sp_type": "B9", "teff_esphs": 9_000, "logg_esphs": 4.0},
            {"sp_type": "O9", "teff_esphs": 8_000, "logg_esphs": 4.0},
            {"sp_type": "O9", "teff_esphs": 20_000, "logg_esphs": 4.0},
            {"sp_type": "O9", "teff_esphs": 25_000, "logg_esphs": 4.0},
        )
        assert estimated[:4] == [set(), set(), set(), set()]
        assert estimated[4] == {"o-type-main-sequence", "main-sequence", "dwarf"}

    def test_esphs_gives_no_stage_above_the_main_sequence(self):
        _, estimated = classify(
            {"sp_type": "B2", "teff_esphs": 25_000, "logg_esphs": 4.6},
            {"sp_type": "B2", "teff_esphs": 25_000, "logg_esphs": 4.5},
        )
        assert estimated[0] == set()
        assert estimated[1] == {"b-type-main-sequence", "main-sequence", "dwarf"}

    @pytest.mark.parametrize(
        "star",
        [
            {"sp_type": "B2", "classlabel_espels": "beStar"},
            {"sp_type": "B2", "simbad_otype": "Be*"},
            {"sp_type": "B2", "simbad_otype": "Em*"},
            {"sp_type": "B2", "simbad_otype": "Be?"},
            {"simbad_sp_type": "B2", "sp_type": "B2Ve"},
            {"sp_type": "B2e"},
            {"sp_type": "B(0/3)ne"},
            {"sp_type": "B[e]"},
            {"sp_type": "B1:pe+K0"},
        ],
    )
    def test_esphs_gives_an_emission_line_star_no_stage(self, star):
        _, estimated = classify(star | DWARF_ESPHS)
        assert estimated[0] == set()

    @pytest.mark.parametrize(
        ("text", "emission"),
        [
            ("B1IV-Ve", 1),
            ("B1Iae", 1),
            ("O9.5V((f))e", 1),
            ("B2He-weak", 0),
            ("B9pSiFe", 0),
            ("B5pec", 0),
            ("B5+K0e", 0),
            ("B5+IIIe", 1),
            ("B1Ia+e", 1),
            ("B3+Ve", 1),
            ("B2+Vne", 1),
            ("B2Ve+K0III", 1),
        ],
    )
    def test_emission_lines_of_a_type(self, text, emission):
        assert families._emission_lines(text) == (emission,)

    def test_tag_quality(self):
        hot = {"in_oba_golden_sample": True}
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
            rules.CANDIDATE_OTYPE_FAMILIES,
            rules.CLASS_FAMILIES,
            rules.ELS_FAMILIES,
            rules.GCVS_FAMILIES,
            rules.SPICY_FAMILIES,
            rules.PARENTS,
        )
        named = {f for table in tables for value in table.values() for f in value}
        named |= set(rules.STATES) | set(rules.PARENTS)
        named |= set(rules.LUMINOSITY_CLASSES.values())
        assert named <= set(rules.FAMILIES)

    def test_every_conflict_rule_names_a_type_letter_and_stage(self):
        conflicts = (*rules.OTYPE_OVER_MK, *rules.MK_OVER_OTYPE)
        codes = {code for code, _, _ in conflicts} | {rules.WN_STAR_OTYPE}
        assert codes <= set(rules.OTYPE_FAMILIES)
        assert set(rules.CLASS_OTYPES.values()) <= set(rules.OTYPE_FAMILIES)
        letters = {
            letter.rstrip("0123456789.")
            for _, given, _ in conflicts
            for letter in given or ()
        }
        letters |= rules.WN_STAR_LETTERS
        assert letters <= set(families.LETTER_CODE)
        stages = {stage for _, _, given in conflicts for stage in given}
        assert stages <= set(families.STAGE_CODE)
