"""The papers of `planet_hosts`: hosts, cited joins, letters."""

import gzip
import logging
import re

import pytest

from space_map_data.constants.stars.planet_hosts import (
    HOSTS,
    JOINS,
    REFERENCES,
    STARS,
    Host,
    HostStar,
    Join,
)
from space_map_data.extrasolar.exoplanets import catalogues, hosts, table
from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    CATALOGUES,
    EU,
    OEC,
    Measure,
    apply_papers,
    check_papers,
    citation,
)
from space_map_data.extrasolar.exoplanets.join import (
    BY_CITATION,
    join_planets,
)
from space_map_data.extrasolar.exoplanets.table import Record, settle_letters
from space_map_data.extrasolar.sky import separation
from space_map_data.extrasolar.sources.wikidata import gaia_position
from space_map_data.extrasolar.systems.planets import _identity_ids
from tests.extrasolar.exoplanet_files import EU_COLUMNS, eu_planet, write_csv
from tests.extrasolar.test_exoplanets import (
    catalogue,
    hub,
    identity,
    joined_planet,
    planet,
    star,
)

GAIA_STAR = HostStar(("gaia", "dr3", "77"), "T A", 10.0, 20.0)
SIMBAD_STAR = HostStar(("simbad", "oid", "88"), "T B", 11.0, 21.0)
XUAN = citation("xuan_2024")
BENEDICT = citation("benedict_2022")
# Arcsec from a Gaia HEALPix pixel of level 12 to its centre, with a margin.
GAIA_PIXEL_REACH = 60.0


def host(found: HostStar) -> Host:
    return Host(found, "xuan_2024")


class TestTable:
    """The entries are ones that the code can follow."""

    def test_references(self):
        for entry in (*HOSTS.values(), *JOINS.values(), *STARS.values()):
            assert entry.reference in REFERENCES

    def test_rows_name_a_catalogue(self):
        for found, _ in (*HOSTS, *JOINS, *STARS):
            assert found in CATALOGUES
        for join in JOINS.values():
            assert join.row[0] in CATALOGUES

    def test_keys_give_a_gaia_id_or_a_simbad_object(self):
        for entry in (*HOSTS.values(), *STARS.values()):
            assert entry.star.key[:2] in (("gaia", "dr3"), ("simbad", "oid"))

    def test_a_star_entry_keeps_the_name_of_its_row(self):
        for (_, name), entry in STARS.items():
            assert entry.star.name == name

    def test_an_archive_target_is_an_objectid(self):
        targets = [j.row[1] for j in JOINS.values() if j.row[0] == ARCHIVE]
        assert targets
        assert all(re.fullmatch(r"\d+\.\d+", target) for target in targets)

    def test_a_gaia_key_is_at_the_position_of_its_entry(self):
        stars = [e.star for e in (*HOSTS.values(), *STARS.values())]
        checked = 0
        for found in stars:
            if found.key[:2] == ("gaia", "dr3"):
                at = gaia_position(found.key[2])
                assert separation(found.ra, found.dec, *at) < GAIA_PIXEL_REACH
                checked += 1
        assert checked

    def test_a_join_names_an_earlier_row_unless_it_has_no_star(self):
        later = {
            (EU, "2MASS J1119-1137 b"),
            (EU, "MOA-2016-BLG-231 b"),
        }
        for row, join in JOINS.items():
            earlier = CATALOGUES.index(join.row[0]) < CATALOGUES.index(row[0])
            assert earlier != (row in later)


class TestApplyPapers:
    """A paper moves a row to its star, or names the row it joins."""

    def cited(self, *rows, stars=("S",), hosts_=None, joins=None, stars_=None):
        found = catalogue(EU, [star(EU, name) for name in stars], list(rows))
        return apply_papers(found, hosts_ or {}, joins or {}, stars_ or {})

    def test_a_listed_row_moves_to_its_star(self):
        values = {"mass": Measure(30.0), "star_mass": Measure(0.5)}
        found = self.cited(
            planet(EU, "S Bb", "S", 12.0, values=values),
            planet(EU, "S c", "S", 50.0),
            hosts_={(EU, "S Bb"): host(GAIA_STAR)},
        )
        moved, stays = found.planets
        assert (moved.star, moved.letter, moved.listed) == ("T A", None, True)
        # The star columns describe the star that the catalogue gave it.
        assert set(moved.values) == {"period", "mass"}
        assert (stays.star, stays.letter, stays.listed) == ("S", "c", False)
        new = found.stars["T A"]
        assert (new.gaia_dr3, new.oid, new.listed) == (77, None, GAIA_STAR.key)
        assert (new.ra, new.dec) == (10.0, 20.0)

    def test_a_simbad_key_gives_the_object(self):
        found = self.cited(
            planet(EU, "S Bb", "S"), hosts_={(EU, "S Bb"): host(SIMBAD_STAR)}
        )
        new = found.stars["T B"]
        assert (new.gaia_dr3, new.oid, new.listed) == (None, "88", SIMBAD_STAR.key)

    def test_two_rows_share_one_star(self):
        entry = host(SIMBAD_STAR)
        found = self.cited(
            planet(EU, "S Ba", "S"),
            planet(EU, "S Bb", "S"),
            hosts_={(EU, "S Ba"): entry, (EU, "S Bb"): entry},
        )
        assert {p.star for p in found.planets} == {"T B"}
        assert list(found.stars) == ["S", "T B"]

    def test_a_cited_row_names_its_planet(self):
        found = self.cited(
            planet(EU, "S e", "S"),
            joins={(EU, "S e"): Join((ARCHIVE, "3.1"), "benedict_2022")},
        )
        assert found.planets[0].same_as == (ARCHIVE, "3.1")
        assert found.planets[0].papers == (BENEDICT,)

    def test_a_row_finds_its_entry_by_its_key(self):
        row = planet(ARCHIVE, "S b", "2.1", key="3.1")
        found = apply_papers(
            catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "S")], [row]),
            {(ARCHIVE, "3.1"): host(GAIA_STAR)},
            {},
            {},
        )
        assert found.planets[0].listed

    def test_a_listed_row_and_its_star_name_their_paper(self):
        found = self.cited(
            planet(EU, "S Bb", "S"), hosts_={(EU, "S Bb"): host(GAIA_STAR)}
        )
        assert found.planets[0].papers == (XUAN,)
        assert found.stars["T A"].papers == (XUAN,)

    def test_a_star_keeps_the_paper_of_each_row(self):
        found = self.cited(
            planet(EU, "S Ba", "S"),
            planet(EU, "S Bb", "S"),
            hosts_={
                (EU, "S Ba"): Host(SIMBAD_STAR, "thompson_2025"),
                (EU, "S Bb"): host(SIMBAD_STAR),
            },
        )
        assert found.stars["T B"].papers == (citation("thompson_2025"), XUAN)

    def test_a_star_row_names_its_paper(self):
        found = self.cited(planet(EU, "S b", "S"), stars_={(EU, "S"): host(GAIA_STAR)})
        assert found.stars["S"].papers == (XUAN,)

    def test_a_star_row_takes_the_key_and_position(self):
        found = self.cited(
            planet(EU, "S b", "S"), stars_={(EU, "S"): host(GAIA_STAR)}
        ).stars["S"]
        assert (found.ra, found.dec, found.epoch) == (10.0, 20.0, None)
        assert (found.gaia_dr3, found.listed) == (77, GAIA_STAR.key)
        assert found.name == "S"

    def test_a_star_row_keeps_its_planets_and_letters(self):
        found = self.cited(planet(EU, "S b", "S"), stars_={(EU, "S"): host(GAIA_STAR)})
        assert (found.planets[0].star, found.planets[0].letter) == ("S", "b")
        assert found.planets[0].listed is False

    def test_the_entry_wins_over_the_star_of_the_catalogue(self):
        values = {"teff": Measure(900.0)}
        rows = [planet(EU, "S Bb", "T A")]
        found = catalogue(EU, [star(EU, "T A", values=values)], rows)
        new = apply_papers(found, {(EU, "S Bb"): host(GAIA_STAR)}, {}, {}).stars["T A"]
        assert (new.gaia_dr3, new.listed, new.papers) == (77, GAIA_STAR.key, (XUAN,))
        assert (new.ra, new.dec, new.epoch) == (10.0, 20.0, None)
        assert new.values == values

    def test_a_row_on_the_star_of_its_entry_says_the_entry_can_go(self):
        found = self.cited(
            planet(EU, "S Bb", "T A"),
            stars=("T A",),
            hosts_={(EU, "S Bb"): host(GAIA_STAR)},
        )
        assert found.superseded == [f"S Bb ({EU}): T A"]

    def test_a_row_that_a_paper_moves_needs_its_entry(self):
        found = self.cited(
            planet(EU, "S Bb", "S"),
            planet(EU, "T A b", "T A"),
            stars=("S", "T A"),
            hosts_={(EU, "S Bb"): host(GAIA_STAR)},
        )
        assert found.stars["T A"].listed == GAIA_STAR.key
        assert found.superseded == []


class TestCheckPapers:
    """An entry of `planet_hosts` that names no row stops the ingest."""

    def catalogues(self):
        return [
            catalogue(ARCHIVE, [], [planet(ARCHIVE, "S c", "2.1", key="3.1")]),
            catalogue(EU, [star(EU, "S")], [planet(EU, "S e", "S")]),
            catalogue(OEC, [], [planet(OEC, "M b", "M")]),
        ]

    def test_entries_with_their_rows_pass(self):
        check_papers(
            self.catalogues(),
            {(EU, "S e"): host(GAIA_STAR)},
            {
                (EU, "S e"): Join((ARCHIVE, "3.1"), "benedict_2022"),
                (OEC, "M b"): Join((ARCHIVE, "3.1"), "benedict_2022"),
            },
            {(EU, "S"): host(GAIA_STAR)},
        )

    def test_a_join_can_name_a_later_catalogue(self):
        check_papers(
            self.catalogues(),
            {},
            {(EU, "S e"): Join((OEC, "M b"), "best_2017")},
            {},
        )

    @pytest.mark.parametrize(
        ("hosts_", "joins", "stars", "entry"),
        [
            ({(EU, "Gone b"): host(GAIA_STAR)}, {}, {}, f"HOSTS {EU} Gone b"),
            (
                {},
                {(EU, "Gone b"): Join((ARCHIVE, "3.1"), "benedict_2022")},
                {},
                f"JOINS {EU} Gone b",
            ),
            (
                {},
                {(EU, "S e"): Join((ARCHIVE, "3.9"), "benedict_2022")},
                {},
                f"JOINS {EU} S e names {ARCHIVE} 3.9",
            ),
            ({}, {}, {(EU, "Gone"): host(GAIA_STAR)}, f"STARS {EU} Gone"),
            # An archive row goes by its objectid.
            ({(ARCHIVE, "S c"): host(GAIA_STAR)}, {}, {}, f"HOSTS {ARCHIVE} S c"),
        ],
    )
    def test_a_stale_entry_raises(self, hosts_, joins, stars, entry):
        with pytest.raises(ValueError, match=f"planet_hosts: no row for {entry}"):
            check_papers(self.catalogues(), hosts_, joins, stars)

    def test_the_message_says_what_to_do(self):
        with pytest.raises(ValueError, match="new key of its row, or remove it"):
            check_papers([], {(EU, "Gone b"): host(GAIA_STAR)}, {}, {})


class TestReaders:
    """The readers follow the table, and exoplanet.eu has no capital letters."""

    def read(self, tmp_path, rows):
        return catalogues.read_eu(write_csv(tmp_path / "eu.csv", rows, EU_COLUMNS))

    def test_eu_rows_move(self, tmp_path):
        found = self.read(
            tmp_path,
            [
                eu_planet("GJ 229 Bb", "GJ 229", 92.6, -21.9, star_mass="0.5"),
                eu_planet("NLTT 31450 b", "NLTT 730", 3.8, 29.9),
            ],
        )
        moved = {p.name: p for p in found.planets}
        assert moved["GJ 229 Bb"].star == "GJ 229 B"
        assert "star_mass" not in moved["GJ 229 Bb"].values
        assert found.stars["GJ 229 B"].oid == "864867"
        # A claim reaches only near its row: the row's position is NLTT 730's.
        assert moved["NLTT 31450 b"].star == "NLTT 31450"
        assert found.stars["NLTT 31450"].ra == pytest.approx(189.9555)

    def test_a_capital_is_no_letter_in_eu(self, tmp_path):
        found = self.read(tmp_path, [eu_planet("GJ 1001 B", "GJ 1001", 1.0, 2.0)])
        assert found.planets[0].letter is None

    def test_a_capital_is_a_letter_in_oec(self, tmp_path):
        xml = """<systems><system><name>W</name><star><name>W</name>
          <planet><name>W B</name><list>Confirmed planets</list></planet>
          </star></system></systems>"""
        path = tmp_path / "oec.xml.gz"
        path.write_bytes(gzip.compress(xml.encode()))
        assert catalogues.read_oec(path).planets[0].letter == "b"

    def test_only_a_cited_row_passes_with_no_star(self, tmp_path):
        found = self.read(
            tmp_path,
            [
                eu_planet("2MASS J1119-1137 b", "", 169.9, -11.6, mass="3.7"),
                eu_planet("MOA-2016-BLG-231 b", "", 268.3, -30.2, mass="9"),
                eu_planet("2MASS J1119-1137", "", 169.9, -11.6, mass="3.7"),
                eu_planet("Rogue b", "", 1.0, 2.0),
            ],
        )
        cited = {p.name: p for p in found.planets}
        assert set(cited) == {"2MASS J1119-1137 b", "MOA-2016-BLG-231 b"}
        assert cited["2MASS J1119-1137 b"].star is None
        assert cited["2MASS J1119-1137 b"].same_as == (OEC, "2MASS J1119-1137 b")
        assert found.stars == {}


class TestStars:
    """A listed star joins by the ids of its key."""

    def stars(self, *more):
        eu = catalogue(EU, [star(EU, "S")], [planet(EU, "S Bb", "S")])
        apply_papers(eu, {(EU, "S Bb"): host(SIMBAD_STAR)}, {})
        return hosts.build_stars([eu, *more], hub(otype={"88": "BD*"}), {})

    def test_a_simbad_key_joins_the_star_of_its_object(self):
        oec = catalogue(OEC, [star(OEC, "S B", oid="88")], [])
        stars = self.stars(oec)
        found = identity(stars, EU, "T B")
        assert found.index == identity(stars, OEC, "S B").index
        assert found.oid == "88"
        assert found.listed == SIMBAD_STAR.key

    def test_the_old_star_keeps_no_claim(self):
        assert identity(self.stars(), EU, "S").listed is None

    def test_a_gaia_key_joins_the_star_of_its_id(self):
        eu = catalogue(EU, [star(EU, "S")], [planet(EU, "S Bb", "S")])
        apply_papers(eu, {(EU, "S Bb"): host(GAIA_STAR)}, {}, {})
        archive = catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "P", gaia_dr3=77)], [])
        stars = hosts.build_stars([archive, eu], hub(), {})
        found = identity(stars, EU, "T A")
        assert found.index == identity(stars, ARCHIVE, "2.1").index
        assert found.listed == GAIA_STAR.key


def test_a_tree_member_lists_no_id_of_a_listed_star():
    eu = catalogue(EU, [star(EU, "S")], [planet(EU, "S Bb", "S")])
    apply_papers(eu, {(EU, "S Bb"): host(SIMBAD_STAR)}, {})
    oec = catalogue(OEC, [star(OEC, "S B", oid="88")], [])
    found = identity(hosts.build_stars([eu, oec], hub(), {}), EU, "T B")
    assert _identity_ids(found) == [
        ("simbad", "oid", "88"),
        (OEC, "systems", "S B"),
    ]


class TestHostRows:
    """A listed star's rows link it and leave its astrometry alone."""

    def found(self, *more):
        eu = catalogue(EU, [star(EU, "S")], [planet(EU, "S Bb", "S")])
        apply_papers(eu, {(EU, "S Bb"): host(SIMBAD_STAR)}, {})
        return identity(hosts.build_stars([eu, *more], hub(), {}), EU, "T B")

    def rows(self, found, source):
        assert found.listed is not None
        return hosts.host_rows(
            source, [found], {}, {}, {}, set(), {found.index: found.listed}, {}
        ).to_pylist()

    def oec(self):
        values = {"parallax": Measure(5.0), "distance": Measure(200.0)}
        return catalogue(
            OEC,
            [star(OEC, "S B", oid="88", values=values, spectral_type="T6")],
            [],
        )

    def test_a_star_that_no_catalogue_lists_gives_its_row(self):
        row = self.rows(self.found(), EU)[0]
        assert row["catalogue_id"] == "T B"
        assert row["name"] == "T B"

    def test_a_catalogue_star_gives_the_row(self):
        found = self.found(self.oec())
        assert self.rows(found, EU) == []
        row = self.rows(found, OEC)[0]
        assert row["catalogue_id"] == "S B"
        assert row["host_spectral_type"] == "T6"
        assert row["host_distance"] == 200.0

    def test_the_catalogue_star_comes_first(self):
        found = self.found(self.oec())
        assert found.first.catalogue == OEC
        assert found.first.spectral_type == "T6"

    def test_the_row_claims_the_key(self):
        for row in (
            self.rows(self.found(), EU)[0],
            self.rows(self.found(self.oec()), OEC)[0],
        ):
            assert row["claims"] == [
                {"catalogue": "simbad", "release": "oid", "catalogue_id": "88"}
            ]

    def test_the_row_matches_at_the_listed_position(self):
        for row in (
            self.rows(self.found(), EU)[0],
            self.rows(self.found(self.oec()), OEC)[0],
        ):
            assert (row["match_ra"], row["match_dec"]) == (11.0, 21.0)

    def test_the_row_has_no_astrometry(self):
        for row in (
            self.rows(self.found(), EU)[0],
            self.rows(self.found(self.oec()), OEC)[0],
        ):
            assert all(row[name] is None for name in hosts.ASTROMETRY_FIELDS)


class TestSimbadClaims:
    """A host with no Gaia DR3 id or HIP number claims a SIMBAD object that
    has a row and that no other identity holds."""

    def stars(self, *rows, **fields):
        found = hub(**fields)
        return hosts.build_stars([catalogue(EU, list(rows), [])], found, {})

    def claims(self, stars, rows=("7",)):
        return hosts.simbad_claims(stars, stars.identities, rows)

    def test_a_host_without_ids_claims_its_object(self):
        stars = self.stars(star(EU, "PSR", oid="7"))
        assert self.claims(stars) == {0: ("simbad", "oid", "7")}

    def test_an_object_with_no_row_gives_no_claim(self):
        assert self.claims(self.stars(star(EU, "PSR", oid="7")), ()) == {}

    def test_a_host_with_no_object_gives_no_claim(self):
        assert self.claims(self.stars(star(EU, "PSR"))) == {}

    @pytest.mark.parametrize("ids", [{"gaia_dr3": 5}, {"hip": 5}])
    def test_a_host_with_another_id_claims_that(self, ids):
        assert self.claims(self.stars(star(EU, "PSR", oid="7", **ids))) == {}

    def test_an_object_on_two_identities_gives_no_claim(self, caplog):
        stars = self.stars(star(EU, "HD 1 A", oid="7"), star(EU, "HD 1 B", oid="7"))
        assert len(stars.identities) == 2
        with caplog.at_level(logging.WARNING):
            assert self.claims(stars) == {}
        assert "SIMBAD 7 is on 2 stars" in caplog.text

    def test_a_star_outside_the_hosts_still_holds_its_object(self):
        stars = self.stars(star(EU, "HD 1 A", oid="7"), star(EU, "HD 1 B", oid="7"))
        assert hosts.simbad_claims(stars, stars.identities[:1], ("7",)) == {}

    def test_a_listed_star_claims_its_key_only(self):
        eu = catalogue(EU, [star(EU, "S")], [planet(EU, "S Bb", "S")])
        apply_papers(eu, {(EU, "S Bb"): host(SIMBAD_STAR)}, {}, {})
        found = hosts.build_stars([eu], hub(), {})
        assert hosts.simbad_claims(found, found.identities, ("88",)) == {}


class TestSimbadRows:
    """A host that claims its SIMBAD object leaves its astrometry to SIMBAD."""

    def rows(self, claim):
        values = {
            "parallax": Measure(4.4),
            "pmra": Measure(1.0),
            "pmdec": Measure(2.0),
            "distance": Measure(230.0),
        }
        stars = hosts.build_stars(
            [catalogue(EU, [star(EU, "PSR", values=values, oid="7")], [])], hub(), {}
        )
        claims = {0: claim} if claim else {}
        return hosts.host_rows(
            EU, stars.identities, {}, {}, {}, set(), claims, {}
        ).to_pylist()[0]

    def test_the_row_has_no_astrometry(self):
        row = self.rows(("simbad", "oid", "7"))
        assert row["claims"] == [
            {"catalogue": "simbad", "release": "oid", "catalogue_id": "7"}
        ]
        assert all(row[name] is None for name in hosts.ASTROMETRY_FIELDS)

    def test_the_row_keeps_its_place_in_the_match_and_its_distance(self):
        row = self.rows(("simbad", "oid", "7"))
        assert row["match_ra"] is not None
        assert row["host_distance"] == 230.0

    def test_another_claim_keeps_the_astrometry(self):
        row = self.rows(("hip", "2007", "5"))
        assert row["parallax"] == pytest.approx(4.4)

    def test_no_claim_keeps_the_astrometry(self):
        assert self.rows(None)["parallax"] == pytest.approx(4.4)


class TestJoin:
    """A listed row stays out, a cited row joins first."""

    def run(self, archive, eu, oec=(), eu_stars=("S",), simbad=None):
        cats = [
            catalogue(ARCHIVE, [star(ARCHIVE, "2.1", "S")], list(archive)),
            catalogue(EU, [star(EU, name) for name in eu_stars], list(eu)),
            catalogue(OEC, [star(OEC, "S")], list(oec)),
        ]
        simbad = simbad or hub()
        stars = hosts.build_stars(cats, simbad, {})
        systems = hosts.group_systems(stars)
        return join_planets(cats, stars, systems, simbad)

    def names(self, result) -> set[frozenset[str]]:
        return {
            frozenset(f"{c}:{p.name}" for c, p in j.rows.items())
            for j in result.planets
        }

    def groups(self, *groups: tuple[str, ...]) -> set[frozenset[str]]:
        return {frozenset(group) for group in groups}

    def companions(self, listed: bool):
        """The exoplanet.eu companions of A beside the archive's planet of the
        pair, as 2M0441's. "S B" has no letter, as `read_eu` reads it."""
        rows = [planet(EU, "S Ab", "S"), planet(EU, "S B", "S")]
        if listed:
            entry = host(GAIA_STAR)
            apply_papers(
                catalogue(EU, [star(EU, "S")], rows),
                {(EU, "S Ab"): entry, (EU, "S B"): entry},
                {},
            )
        return self.run(
            [planet(ARCHIVE, "S b", "2.1")],
            rows,
            [planet(OEC, "S b", "S")],
            ("S", "T A") if listed else ("S",),
        )

    def test_without_the_table_a_companion_takes_the_planet(self):
        result = self.companions(False)
        assert self.names(result) == self.groups(
            (
                f"{ARCHIVE}:S b",
                f"{EU}:S Ab",
                f"{OEC}:S b",
            ),
            (f"{EU}:S B",),
        )

    def test_listed_rows_leave_the_planet_to_the_others(self):
        result = self.companions(True)
        assert self.names(result) == self.groups(
            (f"{EU}:S Ab",),
            (f"{EU}:S B",),
            (
                f"{ARCHIVE}:S b",
                f"{OEC}:S b",
            ),
        )
        assert result.listed == [
            f"S Ab ({EU}): T A ({XUAN})",
            f"S B ({EU}): T A ({XUAN})",
        ]

    def test_a_listed_row_counts_as_a_row_and_not_as_unmatched(self):
        result = self.companions(True)
        assert result.counts[(EU, "rows")] == 2
        assert result.counts[(EU, "unmatched")] == 0

    def test_no_later_row_joins_a_listed_row(self):
        rows = [planet(EU, "S Bb", "S", 12.0)]
        apply_papers(
            catalogue(EU, [star(EU, "S")], rows),
            {(EU, "S Bb"): host(GAIA_STAR)},
            {},
        )
        result = self.run([], rows, [planet(OEC, "S Bb", "S", 12.0)], ("S", "T A"))
        assert self.names(result) == self.groups((f"{EU}:S Bb",), (f"{OEC}:S Bb",))

    def test_a_cited_row_joins_at_any_period(self):
        cited = (ARCHIVE, "S c")
        result = self.run(
            [planet(ARCHIVE, "S c", "2.1", 3947.0)],
            [planet(EU, "S e", "S", 4205.8, same_as=cited)],
            [planet(OEC, "S e", "S", 4205.8, same_as=cited)],
        )
        assert self.names(result) == self.groups(
            (
                f"{ARCHIVE}:S c",
                f"{EU}:S e",
                f"{OEC}:S e",
            )
        )
        assert result.counts[(EU, BY_CITATION)] == 1
        assert result.counts[(OEC, BY_CITATION)] == 1
        # A pair this far apart stays in the report.
        assert len(result.period_checks) == 2

    def test_a_citation_beats_a_better_score(self):
        result = self.run(
            [
                planet(ARCHIVE, "S c", "2.1", 3947.0),
                planet(ARCHIVE, "S e", "2.1", 4205.0),
            ],
            [planet(EU, "S e", "S", 4205.8, same_as=(ARCHIVE, "S c"))],
        )
        assert self.names(result) == self.groups(
            (
                f"{ARCHIVE}:S c",
                f"{EU}:S e",
            ),
            (f"{ARCHIVE}:S e",),
        )

    def test_a_join_follows_the_key_when_the_archive_swaps_its_letters(self):
        # The archive takes the letters of the paper, so its c is the 9.64 d planet.
        result = self.run(
            [
                planet(ARCHIVE, "S c", "2.1", 9.64, key="3.2"),
                planet(ARCHIVE, "S e", "2.1", 3947.0, key="3.1"),
            ],
            [planet(EU, "S e", "S", 4205.8, same_as=(ARCHIVE, "3.1"))],
        )
        assert self.names(result) == self.groups(
            (f"{ARCHIVE}:S c",),
            (
                f"{ARCHIVE}:S e",
                f"{EU}:S e",
            ),
        )

    def test_a_join_goes_by_the_key_and_not_by_the_name(self):
        with pytest.raises(ValueError, match=f"joins {ARCHIVE} S c"):
            self.run(
                [planet(ARCHIVE, "S c", "2.1", 3947.0, key="3.1")],
                [planet(EU, "S e", "S", 4205.8, same_as=(ARCHIVE, "S c"))],
            )

    def test_the_join_lists_each_cited_row_with_its_paper(self):
        rows = [planet(EU, "S e", "S", 4205.8)]
        apply_papers(
            catalogue(EU, [star(EU, "S")], rows),
            {},
            {(EU, "S e"): Join((ARCHIVE, "S c"), "benedict_2022")},
            {},
        )
        result = self.run([planet(ARCHIVE, "S c", "2.1", 3947.0)], rows)
        assert result.cited == [f"S e ({EU}) is S c ({ARCHIVE}): {BENEDICT}"]
        assert result.planets[0].papers == (BENEDICT,)

    def test_a_cited_row_with_no_planet_raises(self):
        with pytest.raises(ValueError, match=f"S b .{EU}. joins {ARCHIVE} S z"):
            self.run(
                [planet(ARCHIVE, "S b", "2.1", 10.0)],
                [planet(EU, "S b", "S", 10.0, same_as=(ARCHIVE, "S z"))],
            )

    def test_a_citation_of_a_listed_row_raises(self):
        rows = [planet(ARCHIVE, "S c", "2.1", listed=True)]
        with pytest.raises(ValueError, match="no planet of the join"):
            self.run(rows, [planet(EU, "S e", "S", same_as=(ARCHIVE, "S c"))])


class TestRowsWithNoStar:
    """A cited row with no star takes the star of the planet that it names."""

    def run(self, eu):
        values = {"semi_major_axis": Measure(0.9)}
        oec = catalogue(OEC, [star(OEC, "M")], [planet(OEC, "M b", "M", values=values)])
        cats = [
            catalogue(ARCHIVE, [], []),
            catalogue(EU, [], list(eu)),
            oec,
        ]
        stars = hosts.build_stars(cats, hub(), {})
        systems = hosts.group_systems(stars)
        return join_planets(cats, stars, systems, hub()), stars

    def run_on_star(self, eu):
        """As `run`, with the star of `M b` in exoplanet.eu."""
        values = {"semi_major_axis": Measure(0.9)}
        oec = catalogue(OEC, [star(OEC, "M")], [planet(OEC, "M b", "M", values=values)])
        cats = [catalogue(ARCHIVE, [], []), catalogue(EU, [star(EU, "M")], eu), oec]
        stars = hosts.build_stars(cats, hub(), {})
        return join_planets(cats, stars, hosts.group_systems(stars), hub())

    def row(self, same_as=(OEC, "M b"), name="M b", **more):
        return planet(EU, name, None, same_as=same_as, **more)

    def test_it_joins_a_planet_of_a_later_catalogue(self):
        result, _ = self.run([self.row()])
        assert len(result.planets) == 1
        joined = result.planets[0]
        assert list(joined.rows) == [EU, OEC]
        assert joined.how[EU] == BY_CITATION
        assert result.counts[(EU, BY_CITATION)] == 1
        assert result.counts[(EU, "rows")] == 1

    def test_the_planet_keeps_its_star(self):
        result, stars = self.run([self.row()])
        found = next(iter(result.planets))
        assert found.rows[EU].star is None
        assert stars.identity(OEC, found.rows[OEC].star) is not None

    def test_a_row_outside_the_kept_status_stays_out(self):
        result, _ = self.run([self.row(status=catalogues.OTHER)])
        assert list(result.planets[0].rows) == [OEC]

    def test_a_row_with_no_planet_raises(self):
        with pytest.raises(ValueError, match=f"joins {OEC} Gone b"):
            self.run([self.row(same_as=(OEC, "Gone b"))])

    def test_two_rows_of_one_catalogue_raise(self):
        twin = planet(EU, "M 1", None, same_as=(OEC, "M b"))
        with pytest.raises(ValueError, match="already has the row"):
            self.run([self.row(), twin])

    def test_a_planet_with_a_row_of_that_catalogue_raises(self):
        joined = planet(EU, "M b", "M", values={"semi_major_axis": Measure(0.9)})
        with pytest.raises(ValueError, match=f"M c .{EU}. joins M b, which already"):
            self.run_on_star([joined, self.row(name="M c")])

    def test_the_join_names_the_planet_and_the_paper(self):
        row = self.row()
        row.papers = (BENEDICT,)
        result, _ = self.run([row])
        assert result.cited == [f"M b ({EU}) is M b ({OEC}): {BENEDICT}"]


def record(star_at: int, *rows) -> Record:
    return Record(joined_planet(*rows), star_at, star_at, 0)


class TestLetters:
    """One letter of a star goes to one planet."""

    def letters(self, *records) -> list[str | None]:
        settle_letters(list(records))
        return [r.values["letter"] for r in records]

    def test_a_later_record_takes_its_other_letter(self):
        # Kapteyn: exoplanet.eu swaps b and c, the archive has only c.
        first = record(
            1,
            planet(ARCHIVE, "K c", "k", 121.5),
            planet(EU, "K b", "k", 121.1),
            planet(OEC, "K c", "k", 121.5),
        )
        second = record(1, planet(EU, "K c", "k", 48.6), planet(OEC, "K b", "k", 48.6))
        assert self.letters(first, second) == ["c", "b"]

    def test_a_record_with_no_free_letter_has_none(self):
        # Kepler-451 (AB)b is a third planet with the letter of the archive's b.
        first = record(1, planet(ARCHIVE, "P b", "p"), planet(EU, "P (AB)c", "p"))
        second = record(1, planet(EU, "P (AB)b", "p"))
        third = record(1, planet(ARCHIVE, "P c", "p"))
        assert self.letters(first, second, third) == ["b", None, "c"]

    def test_the_first_record_wins(self):
        first = record(1, planet(EU, "H (AB)b", "h"))
        second = record(1, planet(EU, "H (ABC)b", "h"))
        assert self.letters(first, second) == ["b", None]

    def test_other_stars_keep_their_letters(self):
        first = record(1, planet(ARCHIVE, "A b", "a"))
        second = record(2, planet(ARCHIVE, "B b", "b"))
        assert self.letters(first, second) == ["b", "b"]

    def test_a_row_with_no_letter_stays_without(self):
        assert self.letters(record(1, planet(EU, "Z", "z"))) == [None]


def test_a_merged_record_takes_the_first_letter():
    found = table.merge(
        joined_planet(planet(ARCHIVE, "A b", "a"), planet(EU, "A c", "a")),
        1,
        1,
        1,
        [],
        None,
    )
    settle_letters([found])
    assert found.values["letter"] == "b"
