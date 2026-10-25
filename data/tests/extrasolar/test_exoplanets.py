"""Tests for the exoplanet catalogues, host stars, the join, classes and names."""

import gzip
import math
import zlib
from collections import Counter

import pyarrow as pa
import pytest

from space_map_data.extrasolar.exoplanets import (
    catalogues,
    hosts,
    iau,
    ingest,
    join,
    names,
    table,
)
from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    EU,
    MICROLENSING,
    OEC,
    Catalogue,
    Measure,
    Planet,
    Star,
)
from space_map_data.extrasolar.exoplanets.ingest import doubles, shared_ids
from space_map_data.extrasolar.exoplanets.join import (
    BY_LETTER,
    BY_OBJECT,
    BY_PERIOD,
    Joined,
    join_planets,
)
from space_map_data.extrasolar.exoplanets.simbad import Simbad
from tests.extrasolar.exoplanet_files import (
    ARCHIVE_COLUMNS,
    EU_COLUMNS,
    archive_planet,
    eu_planet,
    write_csv,
)


class TestCatalogueHelpers:
    """Letters, dates, positions and methods as the catalogues print them."""

    @pytest.mark.parametrize(
        ("name", "capital", "letter"),
        [
            ("HD 1 b", False, "b"),
            ("HD 1 Ab", False, "b"),
            ("Kepler-16 (AB) b", False, "b"),
            ("2M1510 (AB)b", False, "b"),
            ("OGLE-2005-BLG-390L b", False, "b"),
            ("HD 1", False, None),
            ("WD 0806-661 B", False, None),
            ("WD 0806-661 B", True, "b"),
            ("2M1207 A", True, None),
        ],
    )
    def test_letters(self, name, capital, letter):
        assert catalogues.letter_of(name, capital) == letter

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (3085.8, 2_453_085.8),
            (55_000.5, 2_455_000.5),
            (2_455_000.0, 2_455_000.0),
            (245_813.5, None),
            (22_454_964.5, None),
            (None, None),
        ],
    )
    def test_julian_dates(self, value, expected):
        found = catalogues.julian_date(value)
        assert found == (pytest.approx(expected) if expected else None)

    def test_sexagesimal(self):
        assert catalogues.sexagesimal("19 41 48.95", hours=True) == pytest.approx(
            15 * (19 + 41 / 60 + 48.95 / 3600)
        )
        assert catalogues.sexagesimal("-50 49 25.4", hours=False) == pytest.approx(
            -(50 + 49 / 60 + 25.4 / 3600)
        )
        assert catalogues.sexagesimal("", hours=True) is None

    def test_methods(self):
        assert catalogues.method_of("Primary Transit") == "Transit"
        assert catalogues.method_of("Radial Velocity, Astrometry") == "Radial Velocity"
        assert catalogues.method_of("RV") == "Radial Velocity"
        assert catalogues.method_of("Disk Kinematics") == "Disk Kinematics"
        assert catalogues.method_of("") is None


class TestReaders:
    """Each reader gives stars and planets with errors, limits and kinds."""

    def test_archive(self, tmp_path):
        rows = [
            archive_planet(
                "3.2",
                "HD 1 c",
                "HD 1",
                "2.1",
                10.0,
                20.0,
                pl_orbper="100",
                pl_orbpererr1="1",
                pl_orbpererr2="-2",
                pl_bmassj="0.5",
                pl_bmassprov="M-R relationship",
                pl_bmassj_reflink="<a>Calculated Value</a>",
                pl_orbeccen="0.1",
                pl_orbeccenlim="1",
                pl_controv_flag="1",
                st_mass="1.1",
                gaia_dr3_id="Gaia DR3 99",
                hip_name="HIP 7",
            ),
            archive_planet(
                "3.1",
                "HD 1 b",
                "HD 1",
                "2.1",
                10.0,
                20.0,
                sy_dist="12.5",
                st_teff="5800",
            ),
        ]
        found = catalogues.read_archive(
            write_csv(tmp_path / "ps.csv", rows, ARCHIVE_COLUMNS)
        )
        (star,) = found.stars.values()
        assert (star.key, star.name, star.gaia_dr3, star.hip) == (
            "2.1",
            "HD 1",
            None,
            None,
        )
        assert star.values["distance"].value == 12.5
        b, c = found.planets
        assert (b.name, b.key, b.status) == ("HD 1 b", "3.1", catalogues.CONFIRMED)
        assert c.status == catalogues.CONTROVERSIAL
        assert c.values["period"] == Measure(100.0, 1.0, 2.0)
        assert c.values["eccentricity"].limit == catalogues.UPPER_LIMIT
        assert c.values["mass"].estimated and c.mass_kind == catalogues.ESTIMATED_MASS
        assert c.values["star_mass"].value == 1.1

    def test_eu(self, tmp_path):
        rows = [
            eu_planet("A b", "A", 1.0, 2.0, mass="2", mass_sini="2", tperi="3085.8"),
            eu_planet(
                "A c",
                "A",
                1.0,
                2.0,
                mass="3",
                mass_measurement_type="Theoretical",
                tzero_tr="245813.5",
                tconj="2455000.25",
                molecules="H2O, CO",
            ),
            eu_planet("A d", "A", 1.0, 2.0, mass_sini="4", planet_status="Candidate"),
            eu_planet("Rogue", "", 1.0, 2.0),
        ]
        found = catalogues.read_eu(write_csv(tmp_path / "eu.csv", rows, EU_COLUMNS))
        assert list(found.stars) == ["A"]
        b, c, d = found.planets
        assert b.mass_kind == catalogues.MINIMUM_MASS
        assert b.values["periastron_time"].value == pytest.approx(2_453_085.8)
        assert c.mass_kind == catalogues.ESTIMATED_MASS and c.values["mass"].estimated
        assert c.values["transit_time"].value == 2_455_000.25
        assert c.molecules == ("H2O", "CO")
        assert d.status == catalogues.OTHER and d.mass_kind == catalogues.MINIMUM_MASS

    def test_oec_binaries(self, tmp_path):
        xml = """<systems>
        <system><name>Bin</name><rightascension>01 00 00</rightascension>
          <declination>+10 30 00</declination><distance>20</distance>
          <binary>
            <star><name>Bin A</name><mass>1.0</mass></star>
            <star><name>Bin B</name>
              <planet><name>Bin B b</name><period errorminus="1" errorplus="2">50</period>
                <list>Confirmed planets</list></planet></star>
            <planet><name>Bin (AB) b</name><ascendingnode>30</ascendingnode>
              <list>Controversial</list></planet>
          </binary>
          <planet><name>Lonely</name><list>Confirmed planets</list></planet>
        </system>
        <system><name>Solo</name><star><name>Solo</name>
          <planet><name>Solo b</name><list>Solar System</list></planet></star></system>
        </systems>"""
        path = tmp_path / "oec.xml.gz"
        path.write_bytes(gzip.compress(xml.encode()))
        found = catalogues.read_oec(path)
        assert [s.order for s in found.stars.values()] == [0, 1, 0]
        assert found.stars["Bin A"].ra == pytest.approx(15.0)
        assert found.stars["Bin A"].values["distance"].value == 20
        planets = {p.name: p for p in found.planets}
        assert (planets["Bin B b"].star, planets["Bin B b"].binary) == (
            "Bin B",
            "S-type",
        )
        assert planets["Bin B b"].values["period"] == Measure(50.0, 2.0, 1.0)
        assert (planets["Bin (AB) b"].star, planets["Bin (AB) b"].binary) == (
            "Bin A",
            "P-type",
        )
        assert planets["Bin (AB) b"].status == catalogues.CONTROVERSIAL
        assert planets["Bin (AB) b"].values["node"].value == 30
        assert planets["Lonely"].star is None
        assert planets["Solo b"].status == catalogues.OTHER


class TestIauClass:
    """The IAU working definition: deuterium limit and the L4/L5 mass ratio."""

    def test_limits(self):
        assert iau.MASS_RATIO_LIMIT == pytest.approx(1 / 25, rel=0.01)
        assert iau.JUPITER_IN_SUNS == pytest.approx(9.546e-4, rel=1e-3)

    @pytest.mark.parametrize(
        ("mass", "kind", "central", "expected"),
        [
            (1.0, "true", 1.0, (iau.PLANET, iau.TRUE)),
            (12.9, "minimum", 1.0, (iau.PLANET, iau.MINIMUM)),
            (13.0, "true", 1.0, (iau.BROWN_DWARF, iau.TRUE)),
            (30.0, "minimum", 1.0, (iau.BROWN_DWARF, iau.MINIMUM)),
            # 5 MJ around a 25 MJ brown dwarf: ratio 0.2.
            (5.0, "true", 25 * iau.JUPITER_IN_SUNS, (iau.SUB_BROWN_DWARF, iau.TRUE)),
            (0.1, "estimate", None, (iau.PLANET, iau.ESTIMATED)),
            (None, None, 1.0, (iau.PLANET, iau.NONE)),
        ],
    )
    def test_classes(self, mass, kind, central, expected):
        found = iau.classify(mass, kind, central)
        assert found[:2] == expected

    def test_ratio_at_the_limit(self):
        # About 4 MJ around a 0.1 solar mass star.
        central = 0.1
        mass = iau.MASS_RATIO_LIMIT * central / iau.JUPITER_IN_SUNS
        assert iau.classify(mass * 0.999, "true", central)[0] == iau.PLANET
        assert iau.classify(mass * 1.001, "true", central)[0] == iau.SUB_BROWN_DWARF


class TestNameKeys:
    """Designations compare across catalogue spellings."""

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("14 Andromedae b", "14 And b"),
            ("upsilon Andromedae b", "ups And b"),
            ("upsilon Andromedae A b", "ups And Ab"),
            ("xi Aquilae b", "ksi Aql b"),
            ("Fomalhaut b (alpha Piscis Austrini b)", "Fomalhaut b"),
            ("HD 1 b", "hd1b"),
            # Star designations end with a genitive, not a letter.
            ("upsilon Andromedae", "ups And"),
            ("14 Andromedae", "14 And"),
            ("47 Ursae Majoris", "47 UMa"),
            ("epsilon Eridani", "eps Eri"),
        ],
    )
    def test_same(self, a, b):
        assert names.tries(a)[0] == names.key(b)

    def test_final_case_counts(self):
        assert names.key("PSR 1257+12 B") != names.key("PSR 1257+12 b")

    def test_final_component_letters_keep_their_case(self):
        # A pair is not its component A b, which two spellings give.
        assert names.key("Kepler-16 AB") != names.key("Kepler-16 Ab")
        assert names.key("Kepler-16 AB") != names.key("Kepler-16 A b")
        assert names.key("Kepler-16 Ab") == names.key("Kepler-16 A b")
        assert names.key("Kepler-16 (AB) b") == names.key("Kepler-16 AB b")

    def test_brackets(self):
        assert names.tries("Ain b (epsilon Tauri b)") == [
            names.key("Ain b"),
            names.key("eps Tau b"),
        ]


def star(catalogue, key, name=None, **more) -> Star:
    """A star whose position follows from its name, so names apart are far."""
    name = name or key
    ra = zlib.crc32(name.encode()) % 360_000 / 1000
    return Star(catalogue, key, name, (name,), ra=ra, dec=20.0, **more)


def planet(catalogue, name, star_key, period=None, **more) -> Planet:
    values = {} if period is None else {"period": Measure(period)}
    values |= more.pop("values", {})
    return Planet(
        catalogue,
        more.pop("key", name),
        name,
        (name, *more.pop("aliases", ())),
        more.pop("status", catalogues.CONFIRMED),
        star_key,
        letter=catalogues.letter_of(name, capital=True),
        values=values,
        **more,
    )


def catalogue(name, stars, planets) -> Catalogue:
    return Catalogue(name, {s.key: s for s in stars}, planets)


def hub(**fields) -> Simbad:
    return Simbad(**fields)


def identity(stars: hosts.Stars, catalogue: str, key: str) -> hosts.Identity:
    found = stars.identity(catalogue, key)
    assert found is not None
    return found


class TestStars:
    """Star identities across the catalogues."""

    def test_joins_by_id_and_name(self):
        cats = [
            catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "Alpha", gaia_dr3=5)], []),
            catalogue(EU, [star(EU, "Alpha A"), star(EU, "Beta"), star(EU, "Gam")], []),
            catalogue(OEC, [star(OEC, "Beta"), star(OEC, "Delta", gaia_dr2=9)], []),
        ]
        simbad = hub(
            resolved={
                ("exoplanet_eu", "catalog", "star", "Alpha A"): {
                    "printed": Counter({"11": 1})
                },
            },
            otype={"11": "*"},
            gaia_dr3={"11": 5},
        )
        stars = hosts.build_stars(cats, simbad, {9: 77})
        alpha = identity(stars, ARCHIVE, "2.1")
        assert alpha is stars.identity(EU, "Alpha A")
        assert alpha.gaia_dr3 == 5 and alpha.gaia_from_catalogue
        assert stars.identity(EU, "Beta") is stars.identity(OEC, "Beta")
        assert identity(stars, OEC, "Delta").gaia_dr3 == 77
        assert len(stars.identities) == 4

    def test_refusals_and_second_names(self):
        cats = [
            catalogue(
                ARCHIVE,
                [
                    star(ARCHIVE, "2.1", "HD 9 A", hip=40),
                    star(ARCHIVE, "2.2", "HD 9 B", hip=40),
                    star(ARCHIVE, "2.3", "Kep-5", gaia_dr3=7),
                ],
                [],
            ),
            catalogue(
                EU,
                [
                    star(EU, "Kep-5", gaia_dr3=8),
                    star(EU, "2MASS J1", gaia_dr3=3),
                    star(EU, "Kep-6", gaia_dr3=3),
                ],
                [],
            ),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        # Two components with one unresolved HIP number stay two stars.
        a, b = identity(stars, ARCHIVE, "2.1"), identity(stars, ARCHIVE, "2.2")
        assert a is not b and a.hip is None and b.hip is None
        assert "HIP 40 on HD 9 A, HD 9 B: kept by none" in stars.dropped_ids
        # Two DR3 ids: not one star, though the names agree.
        assert stars.identity(ARCHIVE, "2.3") is not stars.identity(EU, "Kep-5")
        assert any("two Gaia DR3 ids" in r for r in stars.refused)
        # One catalogue lists one star twice: one identity, the first name kept.
        twice = identity(stars, EU, "Kep-6")
        assert twice is stars.identity(EU, "2MASS J1")
        assert twice.members[EU].name == "2MASS J1"
        assert stars.duplicates == ["exoplanet-eu: Kep-6 is 2MASS J1"]

    def test_stars_without_ids_join_by_position_and_lens_name(self):
        cats = [
            catalogue(
                ARCHIVE,
                [
                    Star(
                        ARCHIVE, "2.1", "MOA-2009-BLG-319L", ("x",), ra=10.0, dec=-30.0
                    ),
                    Star(ARCHIVE, "2.2", "OGLE-1", ("x",), ra=10.0, dec=-29.0),
                ],
                [],
            ),
            catalogue(
                EU,
                [
                    Star(
                        EU,
                        "MOA 2009 319",
                        "MOA 2009 319",
                        ("x",),
                        ra=10.0005,
                        dec=-30.0,
                    ),
                    Star(EU, "Twin", "Twin", ("x",), ra=10.0, dec=-29.0003),
                ],
                [],
            ),
            catalogue(
                OEC,
                [
                    Star(OEC, "OGLE-1L", "OGLE-1L", ("x",), ra=50.0, dec=0.0),
                    Star(OEC, "KMT-2021-BLG-0240", "KMT-2021-BLG-0240", ("x",)),
                    Star(OEC, "KMT-2021-BLG-0240L", "KMT-2021-BLG-0240L", ("x",)),
                ],
                [],
            ),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        moa = identity(stars, ARCHIVE, "2.1")
        # 1.6″ apart and no ids: one star.
        assert moa is identity(stars, EU, "MOA 2009 319")
        assert identity(stars, ARCHIVE, "2.2") is identity(stars, EU, "Twin")
        # One catalogue lists an event with and without its lens letter.
        kmt = identity(stars, OEC, "KMT-2021-BLG-0240")
        assert kmt is identity(stars, OEC, "KMT-2021-BLG-0240L")
        assert identity(stars, OEC, "OGLE-1L") is not identity(stars, ARCHIVE, "2.2")

    def test_one_catalogue_by_position_is_two_stars(self):
        cats = [
            catalogue(
                EU,
                [
                    Star(EU, "P", "P", ("P",), ra=1.0, dec=1.0),
                    Star(EU, "Q", "Q", ("Q",), ra=1.0, dec=1.0002),
                ],
                [],
            )
        ]
        stars = hosts.build_stars(cats, hub(), {})
        assert identity(stars, EU, "P") is not identity(stars, EU, "Q")

    def test_component_letters(self):
        assert hosts.component_letter("HD 1 B") == "B"
        assert hosts.component_letter("HD 1 A") == ""
        assert hosts.component_letter("HD 1") == ""
        assert hosts.component_letter("OGLE-2005-BLG-390L") == ""
        assert hosts.component_letter("OGLE-2006-BLG-284L A") == ""
        assert hosts.component_letter("OGLE-2016-BLG-0613L B") == "B"
        assert hosts.component_letter("Kepler-16 (AB)") == "AB"

    def test_systems_and_keys(self):
        cats = [
            catalogue(
                ARCHIVE,
                [
                    star(ARCHIVE, "2.1", "XO-9 B", system="XO-9"),
                    star(ARCHIVE, "2.2", "XO-9 A", system="XO-9"),
                ],
                [],
            ),
            catalogue(
                OEC,
                [
                    star(OEC, "G A", system="G", order=0),
                    star(OEC, "G C", system="G", order=2),
                    star(OEC, "G B", system="G", order=1),
                ],
                [],
            ),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        systems = hosts.group_systems(stars)
        index = {s.name: s.index for s in stars.identities}
        assert systems.of[index["XO-9 A"]] == systems.of[index["XO-9 B"]]
        # G A has no planets: the key is the first star with planets.
        systems.choose_keys(
            stars, {index["XO-9 A"], index["XO-9 B"], index["G C"], index["G B"]}
        )
        assert systems.key[systems.of[index["XO-9 B"]]] == index["XO-9 A"]
        assert systems.key[systems.of[index["G A"]]] == index["G B"]

    def test_host_rows_claim_one_id(self):
        cats = [
            catalogue(
                ARCHIVE,
                [
                    star(ARCHIVE, "2.1", "G", gaia_dr3=5, hip=8),
                    star(ARCHIVE, "2.2", "H", hip=8 + 1),
                    star(
                        ARCHIVE,
                        "2.3",
                        "Lit",
                        values={
                            "g_mag": Measure(12.0),
                            "distance": Measure(50.0, 2, 3),
                        },
                    ),
                    star(ARCHIVE, "2.4", "OGLE-1L"),
                ],
                [planet(ARCHIVE, "OGLE-1L b", "2.4", method="Microlensing")],
            ),
            catalogue(EU, [star(EU, "Lit")], []),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        lensed = hosts.found_by(stars, cats, {MICROLENSING})
        lens = identity(stars, ARCHIVE, "2.4").index
        rows = {
            source: {
                row["catalogue_id"]: row
                for row in hosts.host_rows(
                    source,
                    stars.identities,
                    {0: "Prima"},
                    {},
                    lensed,
                    {lens: ("gaia", "dr3", "77")},
                    {},
                ).to_pylist()
            }
            for source in (ARCHIVE, EU)
        }
        archive, eu = rows[ARCHIVE], rows[EU]
        assert archive["2.1"]["claims"] == [
            {"catalogue": "gaia", "release": "dr3", "catalogue_id": "5"}
        ]
        assert archive["2.1"]["name"] == "Prima"
        assert archive["2.2"]["claims"][0]["catalogue"] == "hip"
        assert archive["2.3"]["claims"] is None
        assert archive["2.3"]["match_kind"] == hosts.STAR_KIND
        assert archive["2.3"]["host_distance"] == 50.0
        assert archive["2.3"]["host_distance_error"] == 3.0
        assert archive["2.4"]["match_kind"] == hosts.UNMATCHED_KIND
        assert archive["2.4"]["claims"] == [
            {"catalogue": "gaia", "release": "dr3", "catalogue_id": "77"}
        ]
        assert eu["Lit"]["claims"] == [
            {
                "catalogue": ARCHIVE,
                "release": "pscomppars",
                "catalogue_id": "2.3",
            }
        ]
        assert eu["Lit"]["match_ra"] == archive["2.3"]["match_ra"]


class TestJoin:
    """Planets across catalogues: objects, letters and periods, one-to-one."""

    def run(self, archive, eu, oec=(), simbad=None):
        cats = [
            catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "S")], list(archive)),
            catalogue(EU, [star(EU, "S"), star(EU, "Sun")], list(eu)),
            catalogue(OEC, [star(OEC, "S")], list(oec)),
        ]
        simbad = simbad or hub()
        stars = hosts.build_stars(cats, simbad, {})
        systems = hosts.group_systems(stars)
        return join_planets(cats, stars, systems, simbad)

    def joined(self, result) -> dict[str, list[str]]:
        return {
            j.first.name: sorted(p.name for p in j.rows.values())
            for j in result.planets
        }

    def test_letters_and_periods(self):
        result = self.run(
            [
                planet(ARCHIVE, "S b", "2.1", 10.0),
                planet(ARCHIVE, "S c", "2.1", 30.0),
                planet(ARCHIVE, "S d", "2.1", 90.0),
            ],
            [
                # Re-lettered: its letter is c, its period that of d.
                planet(EU, "S c", "S", 90.5),
                planet(EU, "S b", "S", 10.5),
                planet(EU, "S e", "S", 30.1),
            ],
        )
        assert self.joined(result) == {
            "S b": ["S b", "S b"],
            "S c": ["S c", "S e"],
            "S d": ["S c", "S d"],
        }
        assert result.same_letter == []
        assert result.counts[(EU, BY_LETTER)] == 1
        assert result.counts[(EU, BY_PERIOD)] == 2

    def test_a_letter_with_a_far_period_is_a_weak_match(self):
        result = self.run(
            [planet(ARCHIVE, "S b", "2.1", 9100.0)],
            [],
            [planet(OEC, "S b", "S", 15000.0)],
        )
        assert self.joined(result) == {"S b": ["S b", "S b"]}
        assert result.counts[(OEC, BY_LETTER)] == 1
        assert len(result.period_checks) == 1

    def test_a_weak_letter_needs_its_component_and_a_close_ratio(self):
        result = self.run(
            [planet(ARCHIVE, "S b", "2.1", 579.0), planet(ARCHIVE, "S c", "2.1", 10.0)],
            # A brown dwarf of star B, and a period 3.5 times the archive's.
            [planet(EU, "S Bb", "S", 12.1), planet(EU, "S 1 c", "S", 35.0)],
        )
        assert [len(j.rows) for j in result.planets] == [1, 1, 1, 1]
        # The same designation joins whatever the periods.
        result = self.run(
            [planet(ARCHIVE, "S d", "2.1", 534.5)], [planet(EU, "S d", "S", 13.9)]
        )
        assert self.joined(result) == {"S d": ["S d", "S d"]}
        assert join.component("S Bb") == "B" and join.component("S (AB) b") == "AB"
        assert join.component("S Ab") == "" and join.component("S b") == ""

    def test_a_period_beats_a_weak_letter(self):
        # A re-lettered system: the eu c has the period of the archive's d.
        result = self.run(
            [planet(ARCHIVE, "S c", "2.1", 40.0), planet(ARCHIVE, "S d", "2.1", 89.7)],
            [planet(EU, "S c", "S", 89.68)],
        )
        assert self.joined(result) == {"S c": ["S c"], "S d": ["S c", "S d"]}
        assert result.same_letter == []

    def test_simbad_object_needs_a_close_period(self):
        simbad = hub(
            resolved={
                ("exoplanet_archive", "pscomppars", "planet", "S b"): {
                    "printed": Counter({"9": 1})
                },
                ("exoplanet_eu", "catalog", "planet", "S Ba"): {
                    "printed": Counter({"9": 1})
                },
                ("exoplanet_eu", "catalog", "planet", "S x"): {
                    "printed": Counter({"9": 1})
                },
            },
            otype={"9": "Pl"},
        )
        result = self.run(
            [planet(ARCHIVE, "S b", "2.1", 10.0)],
            [planet(EU, "S Ba", "S", 4000.0), planet(EU, "S x", "S", 10.2)],
            simbad=simbad,
        )
        assert self.joined(result)["S b"] == ["S b", "S x"]
        assert result.counts[(EU, BY_OBJECT)] == 1
        assert result.period_checks == []

    def test_ties_contests_and_checks(self):
        result = self.run(
            [
                planet(ARCHIVE, "S b", "2.1", 10.0),
                planet(ARCHIVE, "S c", "2.1", 10.05),
                planet(ARCHIVE, "S d", "2.1", 20.0),
                planet(ARCHIVE, "S e", "2.1", 20.04),
            ],
            [
                planet(EU, "S x", "S", 10.02),
                planet(EU, "S w", "S", 20.02),
                planet(EU, "S b", "S", 11.5),
                planet(EU, "S y", "S", 10.06, status=catalogues.OTHER),
            ],
            [planet(OEC, "S b", "S", None), planet(OEC, "S q", "S", None)],
        )
        assert len(result.ambiguous) == 1 and "S w" in result.ambiguous[0]
        # The eu S b joins S b with a period 15% off: listed as a check.
        assert self.joined(result)["S b"] == ["S b", "S b", "S b"]
        assert len(result.period_checks) == 1
        # S b went to the better row, so S x takes S c, its other period.
        assert self.joined(result)["S c"] == ["S c", "S x"]
        # S w stays alone, with S d and S e of the same period.
        assert any(m.startswith("S w (exoplanet-eu)") for m in result.missed)
        assert result.same_letter == []
        assert "S y" not in self.joined(result)

    def test_names_and_aliases_join_relettered_planets(self):
        # exoplanet.eu letters GJ 229 A's planets c and d, and names them Ab, Ac.
        result = self.run(
            [
                planet(ARCHIVE, "S b", "2.1", 579.5),
                planet(ARCHIVE, "S A c", "2.1", 121.9),
            ],
            [
                planet(EU, "S c", "S", 523.2, aliases=("S Ab",)),
                planet(EU, "S d", "S", 122.0, aliases=("S Ac",)),
            ],
        )
        assert self.joined(result)["S b"] == ["S b", "S c"]
        assert self.joined(result)["S A c"] == ["S A c", "S d"]

    def test_a_planet_that_lost_its_period_takes_its_letter(self):
        # OEC gives Kepler-271 b half its period, which is d's.
        result = self.run(
            [
                planet(ARCHIVE, "S b", "2.1", 10.4355),
                planet(ARCHIVE, "S d", "2.1", 5.2497),
            ],
            [],
            [planet(OEC, "S b", "S", 5.2177), planet(OEC, "S d", "S", 5.2497)],
        )
        assert self.joined(result)["S b"] == ["S b", "S b"]
        assert self.joined(result)["S d"] == ["S d", "S d"]

    def test_the_designation_settles_a_contest(self):
        # Two exoplanet.eu rows on one lens; only one has the archive's name.
        result = self.run(
            [planet(ARCHIVE, "KMT-2017-BLG-2509L b", "2.1")],
            [
                planet(EU, "KMT-2017-BLG-2509 b", "S"),
                planet(EU, "OGLE-2019-BLG-0299 b", "S"),
            ],
        )
        assert self.joined(result)["KMT-2017-BLG-2509L b"] == [
            "KMT-2017-BLG-2509 b",
            "KMT-2017-BLG-2509L b",
        ]
        assert result.contested == []

    def test_a_component_that_repeats_its_star(self):
        # exoplanet.eu names the star HAT-P-44 "HAT-P-44 B"; its c has the
        # other alias period, 4× the archive's.
        cats = [
            catalogue(
                ARCHIVE,
                [star(ARCHIVE, "2.1", "S", gaia_dr3=5)],
                [planet(ARCHIVE, "S c", "2.1", 872.2)],
            ),
            catalogue(
                EU,
                [star(EU, "S B", gaia_dr3=5)],
                [planet(EU, "S Bc", "S B", 219.9)],
            ),
            catalogue(OEC, [], []),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        result = join_planets(cats, stars, hosts.group_systems(stars), hub())
        assert self.joined(result) == {"S c": ["S Bc", "S c"]}

    def test_a_microlensing_planet_by_its_orbit(self):
        # No period: the archive letters it c, exoplanet.eu b.
        orbit = {"semi_major_axis": Measure(3.2), "mass": Measure(2.2)}
        other = {"semi_major_axis": Measure(3.1), "mass": Measure(2.2)}
        result = self.run(
            [planet(ARCHIVE, "S AB c", "2.1", values=orbit)],
            [planet(EU, "S (AB)b", "S", values=other)],
        )
        assert self.joined(result) == {"S AB c": ["S (AB)b", "S AB c"]}

    def test_rows_that_are_not_planets_of_a_star(self):
        result = self.run(
            [],
            [
                planet(EU, "Exomoon S b I", "S", 5.0),
                planet(EU, "S", "S", None),
                planet(EU, "ISO 1I", "Sun", None),
                planet(EU, "S b", "S", 5.0),
            ],
        )
        assert list(self.joined(result)) == ["S b"]
        assert result.counts[(EU, "moons, comets and trojans")] == 1
        assert result.counts[(EU, "named like their star")] == 1
        assert result.counts[(EU, "objects of the Sun")] == 1


def joined_planet(*rows: Planet) -> Joined:
    return Joined({row.catalogue: row for row in rows})


class TestTable:
    """Groups by source order, defaults and flags."""

    def test_campbell_round_trip(self):
        a, i, w, node = 2.0, math.radians(60), math.radians(40), math.radians(110)
        cos_w, sin_w, cos_o, sin_o = (
            math.cos(w),
            math.sin(w),
            math.cos(node),
            math.sin(node),
        )
        elements = (
            a * (cos_w * cos_o - sin_w * sin_o * math.cos(i)),
            a * (cos_w * sin_o + sin_w * cos_o * math.cos(i)),
            a * (-sin_w * cos_o - cos_w * sin_o * math.cos(i)),
            a * (-sin_w * sin_o + cos_w * cos_o * math.cos(i)),
        )
        axis, inclination, omega, found = table.campbell(*elements)
        assert axis == pytest.approx(2.0)
        assert inclination == pytest.approx(60)
        # Ω in [0°, 180°): 110° stays, ω keeps 40°.
        assert found == pytest.approx(110) and omega == pytest.approx(40)

    def test_groups_and_mass_order(self):
        archive = planet(
            ARCHIVE,
            "S b",
            "2.1",
            10.0,
            values={
                "mass": Measure(0.5, estimated=True),
                "radius": Measure(1.0),
                "star_mass": Measure(0.9),
            },
            mass_kind=catalogues.ESTIMATED_MASS,
        )
        eu = planet(
            EU,
            "S b",
            "S",
            10.1,
            values={
                "mass": Measure(0.8, 0.1, 0.1),
                "omega": Measure(30.0),
                "radius": Measure(1.2, estimated=True),
            },
            mass_kind=catalogues.TRUE_MASS,
            molecules=("H2O",),
        )
        oec = planet(OEC, "S b", "S", 10.0, values={"node": Measure(45.0)})
        orbit = table.SkyOrbit(1, "Orbital", 10.3, 120.0, 80.0)
        record = table.merge(
            joined_planet(archive, eu, oec), 0, 0, 0, [orbit], None, ("S",)
        )
        values = record.values
        # The orbit group comes whole from the archive: no ω from exoplanet.eu.
        assert values["orbit_source"] == ARCHIVE and "omega" not in values
        assert (values["mass"], values["mass_source"]) == (0.8, EU)
        assert values["mass_kind"] == catalogues.TRUE_MASS
        assert (values["radius"], values["radius_source"]) == (1.0, ARCHIVE)
        assert (values["node"], values["sky_source"]) == (120.0, "gaia-dr3")
        assert values["molecules"] == ["H2O"]
        assert values["class"] == iau.PLANET and values["class_basis"] == iau.TRUE
        assert record.estimated == set()

    def test_defaults(self):
        transiting = planet(
            ARCHIVE,
            "S b",
            "2.1",
            5.0,
            values={
                "inclination": Measure(87.0),
                "transit_time": Measure(2_455_000.0),
                "eccentricity": Measure(0.0),
            },
        )
        rv = planet(
            ARCHIVE,
            "S c",
            "2.1",
            None,
            values={"semi_major_axis": Measure(1.0), "star_mass": Measure(1.0)},
        )
        imaged = planet(
            ARCHIVE, "S d", "2.1", None, values={"angular_separation": Measure(500.0)}
        )
        records = [
            table.merge(joined_planet(p), 0, 7, 0, [], None)
            for p in (transiting, rv, imaged)
        ]
        for record in records:
            table.kepler(record, 1.0, 20.0)
        table.fill_defaults(records)
        b, c, d = records
        assert b.assumed == {"eccentricity", "omega"}
        assert c.values["period"] == pytest.approx(365.2569, rel=1e-6)
        assert c.computed == {"period"}
        assert c.values["inclination"] == 87.0 and "inclination" in c.assumed
        assert c.values["periastron_time"] == table.J2000
        assert d.values["semi_major_axis"] == pytest.approx(10.0)
        assert d.computed == {"semi_major_axis", "period"}
        row = table.to_row(c, 123, 2, 123)
        assert row["node"] == table.default_node(123) and "node" in row["assumed"]
        assert table.to_row(b, 123, 1, 123)["node"] == row["node"]
        assert table.default_node(124) != row["node"]

    def test_mass_cut(self):
        heavy = planet(ARCHIVE, "S b", "2.1", 5.0, values={"mass": Measure(70.0)})
        limit = planet(
            ARCHIVE, "S c", "2.1", 5.0, values={"mass": Measure(70.0, limit="<")}
        )
        assert table.too_massive(table.merge(joined_planet(heavy), 0, 0, 0, [], None))
        assert not table.too_massive(
            table.merge(joined_planet(limit), 0, 0, 0, [], None)
        )

    def test_aliases_leave_out_star_names(self):
        row = planet(EU, "S b", "S", 5.0, aliases=("GJ 1", "S-1 b"))
        record = table.merge(joined_planet(row), 0, 0, 0, [], None, ("S", "GJ 1"))
        assert record.values["aliases"] == ["S b", "S-1 b"]
        table.name_planet(record, "Primus")
        assert record.values["name"] == "Primus"
        assert record.values["aliases"] == ["Primus", "S b", "S-1 b"]
        cross_ids = record.values["cross_ids"]
        assert isinstance(cross_ids, list)
        assert cross_ids[-1] == {
            "catalogue": "iau",
            "release": "nameexoworlds",
            "catalogue_id": "Primus",
        }

    def test_star_names_in_other_scripts_leave_out_only_themselves(self):
        row = planet(EU, "S b", "S", 5.0, aliases=("β Cen", "α  cen", "アエギル"))
        record = table.merge(
            joined_planet(row), 0, 0, 0, [], None, ("S", "α Cen", "天苑四")
        )
        assert record.values["aliases"] == ["S b", "β Cen", "アエギル"]


def test_shared_ids_list_stars_that_one_id_holds():
    cats = [
        catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "OGLE-1L")], []),
        catalogue(EU, [star(EU, "KMT-9L"), star(EU, "Solo")], []),
    ]
    stars = hosts.build_stars(cats, hub(), {})
    ids = {identity.index: 77 for identity in stars.identities}
    ids[identity(stars, EU, "Solo").index] = 78
    assert shared_ids(ids, stars) == [
        "77: OGLE-1L (nasa-exoplanet-archive), KMT-9L (exoplanet-eu)"
    ]


def test_doubles_in_one_system():
    def row(host, name, letter, period, catalogues, computed=(), system=None):
        return {
            "host": host,
            "system": host if system is None else system,
            "designation": name,
            "letter": letter,
            "period": period,
            "cross_ids": [
                {"catalogue": c, "release": "", "catalogue_id": name}
                for c in catalogues
            ],
            "computed": list(computed),
        }

    planets = pa.Table.from_pylist(
        [
            row(1, "A b", "b", 10.0, [ARCHIVE, EU]),
            row(1, "A c", "c", 30.0, [ARCHIVE]),
            row(1, "K b", "b", 99.0, [OEC]),
            row(1, "K x", "x", 30.5, [EU]),
            row(2, "B b", "b", None, [ARCHIVE]),
            row(2, "B c", "c", 50.0, [EU], computed=["period"]),
            row(2, "B d", "d", 50.5, [OEC]),
            # The other star of system 1: one letter is no double, one period is.
            row(3, "A2 b", "b", 70.0, [OEC], system=1),
            row(3, "A2 c", "c", 10.1, [OEC], system=1),
        ]
    )
    assert doubles(planets) == [
        "1: A b and K b",
        "1: A b and A2 c",
        "1: A c and K x",
    ]


def test_the_primary_keeps_a_shared_gaia_id():
    cats = [
        catalogue(
            ARCHIVE,
            [
                star(ARCHIVE, "2.1", "HD 9 A"),
                star(ARCHIVE, "2.2", "HD 9 B", gaia_dr3=5),
            ],
            [],
        ),
        catalogue(EU, [star(EU, "HD 9 A")], []),
    ]
    # SIMBAD gives A the id; the archive gives it to B.
    simbad = hub(
        resolved={
            (source, table, "star", "HD 9 A"): {"printed": Counter({"3": 1})}
            for source, table in (
                ("exoplanet_eu", "catalog"),
                ("exoplanet_archive", "stellarhosts"),
            )
        },
        otype={"3": "*"},
        gaia_dr3={"3": 5},
    )
    stars = hosts.build_stars(cats, simbad, {})
    assert identity(stars, ARCHIVE, "2.1") is identity(stars, EU, "HD 9 A")
    assert identity(stars, ARCHIVE, "2.1").gaia_dr3 == 5
    assert identity(stars, ARCHIVE, "2.2").gaia_dr3 is None


@pytest.mark.parametrize(
    ("name", "hipparcos", "shown"),
    [
        ("sig Per", "Sigma Persei", "Sigma Persei"),
        ("tau Gem", "Tau Geminorum", "Tau Geminorum"),
        ("rho CrB", "Rho Coronae Borealis", "Rho Coronae Borealis"),
        ("pi1 Cnc", "Pi1 Cancri", "Pi1 Cancri"),
        ("14 Her", "14 Herculis", "14 Herculis"),
        # Not only a short form of the Hipparcos designation.
        ("WASP-33", "HD 15082", "WASP-33"),
        ("HD 10697", "109 Piscium", "HD 10697"),
        ("nu Oct A", "Nu Octantis", "nu Oct A"),
        ("9 CMa", "Alpha Canis Majoris", "9 CMa"),
        ("sig Per", "Sigma Orionis", "sig Per"),
        ("sig Per", None, "sig Per"),
    ],
)
def test_long_form_of_a_bayer_or_flamsteed_name(name, hipparcos, shown):
    assert hosts.long_form(name, hipparcos) == shown


class TestStarsOfOneTwin:
    """Two stars at one registry twin are one star only on evidence."""

    def stars(self, **masses):
        names = {"P": "X", "Q": "X A", "R": "X B", "T": "X (AB)", "U": "X Ab"}
        cats = [
            catalogue(
                ARCHIVE,
                [
                    star(
                        ARCHIVE,
                        key,
                        name,
                        values={"mass": Measure(masses[key])} if key in masses else {},
                    )
                    for key, name in names.items()
                ],
                [planet(ARCHIVE, f"{n} b", k, 5.0) for k, n in names.items()],
            )
        ]
        stars = hosts.build_stars(cats, hub(), {})
        return {k: identity(stars, ARCHIVE, k) for k in names}, ingest._periods(
            stars, cats
        )

    def test_the_same_component(self):
        found, periods = self.stars()
        assert ingest._same_star(found["P"], found["Q"], periods)
        assert ingest._same_star(found["T"], found["Q"], periods)
        assert ingest._same_star(found["R"], found["P"], periods) is None
        # One star of a close pair inside A is not A.
        assert ingest._same_star(found["U"], found["P"], periods) is None

    def test_another_letter_with_a_shared_planet_and_mass(self):
        found, periods = self.stars(P=0.17, R=0.17)
        why = ingest._same_star(found["R"], found["P"], periods)
        assert why is not None and "planet period" in why
        found, periods = self.stars(P=0.4, R=0.035)
        assert ingest._same_star(found["R"], found["P"], periods) is None


def test_one_designation_on_two_hosts():
    def row(host, designation, eu=None):
        ids = (
            [{"catalogue": EU, "release": "catalog", "catalogue_id": eu}] if eu else []
        )
        return {"host": host, "designation": designation, "cross_ids": ids}

    planets = pa.Table.from_pylist(
        [
            row(1, "OGLE-2019-BLG-0299L b"),
            row(2, "KMT-2017-BLG-2509L b", eu="KMT-2017-BLG-2509 b"),
            row(2, "OGLE-2019-BLG-0299 b", eu="OGLE-2019-BLG-0299 b"),
            row(3, "Kepler-38 b"),
            row(4, "Kepler-38 (AB)b"),
            row(5, "S b"),
            row(5, "S c"),
        ]
    )
    assert ingest.named_twice(planets) == [
        "OGLE-2019-BLG-0299L b on 1, OGLE-2019-BLG-0299 b on 2",
        "Kepler-38 b on 3, Kepler-38 (AB)b on 4",
    ]


def test_a_pair_and_its_primary_join_by_position():
    def at(catalogue, name, ra):
        return Star(catalogue, name, name, (name,), ra=ra, dec=-28.0)

    cats = [
        catalogue(ARCHIVE, [at(ARCHIVE, "MOA-1 AB", 269.0)], []),
        catalogue(EU, [at(EU, "KMT-1 B", 269.0001)], []),
        catalogue(OEC, [at(OEC, "OGLE-1 A", 269.0)], []),
    ]
    stars = hosts.build_stars(cats, hub(), {})
    pair = identity(stars, ARCHIVE, "MOA-1 AB")
    assert identity(stars, OEC, "OGLE-1 A") is pair
    assert identity(stars, EU, "KMT-1 B") is not pair


def test_one_system_per_host():
    # Planets 0 and 1 have one host, which two star identities of the join
    # gave to systems 10 and 20; system 20 also holds host 3.
    host_of = {0: 1, 1: 1, 2: 3}
    system_of = {0: 10, 1: 20, 2: 20}
    found, joined = ingest.one_system_per_host(host_of, system_of, {10: (0,), 20: (1,)})
    assert found == {0: 10, 1: 10, 2: 10}
    assert joined == ["host 1: systems 10, 20, key 10"]


def test_joined_systems_keep_the_key_rule():
    # The B component has the lower ID, but A is the key.
    cats = [catalogue(ARCHIVE, [star(ARCHIVE, "W B"), star(ARCHIVE, "W A")], [])]
    stars = hosts.build_stars(cats, hub(), {})
    rank = {
        5: hosts.key_rank(stars, identity(stars, ARCHIVE, "W B").index),
        9: hosts.key_rank(stars, identity(stars, ARCHIVE, "W A").index),
    }
    found, joined = ingest.one_system_per_host({0: 1, 1: 1}, {0: 5, 1: 9}, rank)
    assert found == {0: 9, 1: 9}
    assert joined == ["host 1: systems 9, 5, key 9"]


def test_a_host_with_two_systems_is_found():
    planets = pa.Table.from_pylist(
        [
            {"host": 1, "system": 10},
            {"host": 1, "system": 20},
            {"host": 2, "system": 2},
        ]
    )
    assert ingest.hosts_with_several_systems(planets) == ["1: [10, 20]"]


class TestOneDesignationOnTwoStars:
    """A designation names one planet, on whichever star a catalogue puts it."""

    OGLE, KMT = "OGLE-2019-BLG-0299", "KMT-2017-BLG-2509"

    def run(self, eu_star, oec_star):
        ogle, kmt = self.OGLE, self.KMT
        cats = [
            catalogue(
                ARCHIVE,
                [star(ARCHIVE, "2.1", f"{ogle}L"), star(ARCHIVE, "2.2", f"{kmt}L")],
                [
                    planet(ARCHIVE, f"{ogle}L b", "2.1"),
                    planet(ARCHIVE, f"{kmt}L b", "2.2"),
                ],
            ),
            catalogue(
                EU,
                [star(EU, eu_star)],
                [planet(EU, f"{kmt} b", eu_star), planet(EU, f"{ogle} b", eu_star)],
            ),
            catalogue(OEC, [star(OEC, oec_star)], [planet(OEC, f"{ogle} b", oec_star)]),
        ]
        stars = hosts.build_stars(cats, hub(), {})
        systems = hosts.group_systems(stars)
        return stars, join_planets(cats, stars, systems, hub())

    def test_the_planet_joins_and_takes_the_star_it_names(self):
        # exoplanet.eu and OEC put OGLE-2019-BLG-0299 b on KMT-2017-BLG-2509.
        stars, result = self.run(self.KMT, self.KMT)
        joined = {j.first.name: j for j in result.planets}
        assert sorted(joined) == [f"{self.KMT}L b", f"{self.OGLE}L b"]
        ogle = joined[f"{self.OGLE}L b"]
        assert set(ogle.rows) == {ARCHIVE, EU, OEC}
        assert ogle.how[EU] == join.BY_DESIGNATION
        assert ingest._star_of(ogle, stars) == identity(stars, ARCHIVE, "2.1").index

    def test_a_star_of_the_same_name_keeps_the_usual_rules(self):
        # OEC's "…L A" and the archive's "…L" are one star by name, at other
        # positions; OEC's star comes first.
        stars, result = self.run(self.KMT, f"{self.OGLE}L A")
        ogle = next(j for j in result.planets if j.first.name == f"{self.OGLE}L b")
        oec = identity(stars, OEC, f"{self.OGLE}L A").index
        assert ingest._star_of(ogle, stars) == oec


def test_systems_take_linked_stars():
    cats = [
        catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "CD-1 B")], []),
        catalogue(EU, [star(EU, "CD-1")], []),
    ]
    stars = hosts.build_stars(cats, hub(), {})
    b, a = identity(stars, ARCHIVE, "2.1").index, identity(stars, EU, "CD-1").index
    assert hosts.group_systems(stars).of[a] != hosts.group_systems(stars).of[b]
    linked = hosts.group_systems(stars, [(b, a)])
    assert linked.of[a] == linked.of[b]
