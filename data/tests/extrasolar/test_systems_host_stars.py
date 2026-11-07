"""The held star that the planets of a point orbit (`host_stars`).

A move to the wrong star puts a planet and its host's values on a star they
do not belong to, so every rule that moves them is tested with a case that
must not move.
"""

import pytest

from space_map_data.extrasolar.systems.host_stars import (
    BY_BRIGHTNESS,
    BY_ID,
    BY_LETTER,
    BY_POINT,
    Host,
    Member,
    choose,
    dominates,
    type_teff,
)

ARCHIVE_KEY = ("nasa-exoplanet-archive", "pscomppars", "2.34013")
GAIA_KEY = ("gaia", "dr3", "4792774797545800832")


def wasp_12(
    teff: float | None = 6265.0, mass: float | None = 1.325
) -> tuple[Host, list[Member]]:
    """WASP-12 A, B and C in one point, as the MSC gives them, and the
    archive's host values."""
    members = [
        Member(0, True, "A", v_mag=11.5, mass=1.46, spectral_type="G0V"),
        Member(1, True, "B", v_mag=15.67, mass=0.58, spectral_type="K0V"),
        Member(2, True, "C", v_mag=15.67, mass=0.56),
    ]
    return Host(teff=teff, mass=mass), members


class TestTypeTeff:
    def test_interpolates_the_dwarf_sequence(self) -> None:
        assert type_teff("G0V") == 5930
        assert type_teff("G0.5V") == pytest.approx((5930 + 5860) / 2)

    def test_needs_a_subclass(self) -> None:
        assert type_teff("dK") is None
        assert type_teff("M") is None
        assert type_teff(None) is None

    def test_reads_a_dwarf_prefix(self) -> None:
        assert type_teff("dM4") == 3210

    @pytest.mark.parametrize(
        ("spectral_type", "first"),
        [("F(6)V", "F6V"), ("kA2hA5mA7V", "A5V")],
    )
    def test_reads_the_types_that_the_families_read(self, spectral_type, first):
        assert type_teff(spectral_type) == type_teff(first) is not None

    @pytest.mark.parametrize("spectral_type", ["G6?", "K0:", "M?"])
    def test_an_uncertain_type_has_none(self, spectral_type):
        assert type_teff(spectral_type) is None

    @pytest.mark.parametrize("spectral_type", ["G0V+K2V", "L2+L3.5", "A0V+?"])
    def test_a_type_of_two_stars_has_none(self, spectral_type):
        """Their combined light says nothing of the Teff of one of them."""
        assert type_teff(spectral_type) is None

    def test_a_giant_has_no_dwarf_teff(self) -> None:
        assert type_teff("K5+III") is None
        assert type_teff("K0III") is None

    @pytest.mark.parametrize("spectral_type", ["sdB5", "sdO6", "sdK7", "M2VI"])
    def test_a_subdwarf_has_no_dwarf_teff(self, spectral_type):
        """The sequence is of dwarfs of solar metallicity: an sdB is about
        twice as hot as a B5 dwarf."""
        assert type_teff(spectral_type) is None


class TestDominates:
    """The first member of a point dominates its light, else the light can
    blend. The radius of the point and its planets' host follow it."""

    def test_a_companion_fainter_in_g(self) -> None:
        members = [
            Member(0, True, g_mag=4.0, v_mag=4.0),
            Member(1, True, g_mag=7.0, v_mag=4.5),
        ]
        assert dominates(members) == (True, "ΔG 3.00")

    @pytest.mark.parametrize(
        "companion",
        [
            {"v_mag": 5.0},
            {"mass": 1.8},
            # G goes first: V alone would put it 4 mag fainter.
            {"g_mag": 4.5, "v_mag": 8.0},
            # Nothing rules out that it blends.
            {},
        ],
    )
    def test_a_companion_that_can_blend(self, companion) -> None:
        main = Member(0, True, g_mag=4.0, v_mag=4.0, mass=2.0)
        assert dominates([main, Member(1, True, **companion)])[0] is False

    def test_a_lighter_companion(self) -> None:
        members = [Member(0, True, mass=2.0), Member(1, True, mass=0.5)]
        assert dominates(members) == (True, "mass ratio 0.25")

    @pytest.mark.parametrize("masses", [(0.0, 0.5), (2.0, 0.0), (None, 0.5)])
    def test_a_mass_that_is_not_positive_tells_nothing(self, masses) -> None:
        mine, theirs = masses
        members = [Member(0, True, mass=mine), Member(1, True, mass=theirs)]
        assert dominates(members) == (False, "no band or mass that both have")

    def test_each_other_member(self) -> None:
        members = [
            Member(0, True, v_mag=4.0),
            Member(1, True, v_mag=9.0),
            Member(2, True, v_mag=5.0),
        ]
        assert dominates(members) == (False, "ΔV 1.00")

    def test_an_own_v_goes_before_the_v(self) -> None:
        """The MSC's V of A holds the light of the pair."""
        members = [
            Member(0, True, v_mag=4.0, own_v_mag=4.5),
            Member(1, True, v_mag=6.0, own_v_mag=6.0),
        ]
        assert dominates(members) == (False, "ΔV 1.50")

    def test_with_an_own_v_a_mass_does_not_tell(self) -> None:
        members = [
            Member(0, True, v_mag=4.0, own_v_mag=4.2, mass=2.0),
            Member(1, True, v_mag=14.0, mass=0.2),
        ]
        assert dominates(members) == (False, "no G or own V that both have")


class TestById:
    def test_a_shared_id_wins(self) -> None:
        host = Host(ids=frozenset({ARCHIVE_KEY}), teff=5850.0)
        members = [
            Member(
                0,
                True,
                "TrES-2",
                mass=0.98,
                teff=5850.0,
                spectral_type="G0",
                ids=frozenset({ARCHIVE_KEY}),
            ),
            Member(1, True, "TrES-2 B", mass=0.51, teff=3669.0),
        ]
        choice = choose(host, members)
        assert choice.row == 0 and choice.evidence.startswith(BY_ID)

    def test_two_members_with_the_id_stay(self) -> None:
        host = Host(ids=frozenset({ARCHIVE_KEY}))
        members = [Member(i, True, ids=frozenset({ARCHIVE_KEY})) for i in (0, 1)]
        choice = choose(host, members)
        assert choice.row is None and choice.evidence == BY_ID

    def test_values_that_disagree_stop_an_id(self) -> None:
        host = Host(ids=frozenset({ARCHIVE_KEY}), mass=1.4)
        members = [Member(0, True, mass=0.5, ids=frozenset({ARCHIVE_KEY}))]
        choice = choose(host, members)
        assert choice.row is None and "mass 1.4 vs 0.5" in (choice.reason or "")

    def test_the_id_needs_the_letter_of_the_host(self) -> None:
        """A WDS component often carries the Gaia id of its point, as the
        catalogue host does. The letter B of the host names the other star."""
        host = Host(ids=frozenset({GAIA_KEY}), letters=frozenset({"B"}), mass=0.4)
        members = [
            Member(0, True, "A", ids=frozenset({GAIA_KEY})),
            Member(1, True, "B", mass=0.4),
        ]
        choice = choose(host, members)
        assert choice.row is None and choice.evidence == BY_ID
        assert "letter B" in (choice.reason or "")

    def test_kepler_108_stays(self) -> None:
        """Mills & Fabrycky 2017 put the planets on B. The archive's Gaia id
        is that of A."""
        host = Host(ids=frozenset({GAIA_KEY}), letters=frozenset({"B"}), mass=1.25)
        members = [
            Member(0, True, "A", v_mag=12.66, mass=1.26, ids=frozenset({GAIA_KEY})),
            Member(1, True, "B", mass=0.96),
        ]
        assert choose(host, members).row is None

    def test_two_letters_stop_an_id(self) -> None:
        host = Host(ids=frozenset({GAIA_KEY}), letters=frozenset({"A", "B"}))
        members = [
            Member(0, True, "A", ids=frozenset({GAIA_KEY})),
            Member(1, True, "B"),
        ]
        choice = choose(host, members)
        assert choice.row is None and "letters A, B" in (choice.reason or "")

    def test_an_id_and_its_letter_move(self) -> None:
        """TrES-2: exoplanet.eu and OEC name the host TrES-2 A."""
        host = Host(ids=frozenset({ARCHIVE_KEY}), letters=frozenset({"A"}), teff=5850.0)
        members = [
            Member(0, True, "A", mass=0.98, teff=5850.0, ids=frozenset({ARCHIVE_KEY})),
            Member(1, True, "B", mass=0.51, teff=3669.0),
        ]
        choice = choose(host, members)
        assert choice.row == 0 and "letter A" in choice.evidence

    def test_an_id_with_no_values_moves(self) -> None:
        """No value of the member contradicts the host."""
        host = Host(ids=frozenset({GAIA_KEY}), teff=8039.0, mass=1.75)
        members = [
            Member(0, True, "Aa", ids=frozenset({GAIA_KEY})),
            Member(1, True, "Ab"),
        ]
        assert choose(host, members).row == 0

    def test_an_id_lists_the_values_that_agree(self) -> None:
        host = Host(ids=frozenset({GAIA_KEY}), teff=6234.0, mass=1.22)
        members = [
            Member(
                0,
                True,
                "Aa",
                v_mag=3.81,
                spectral_type="G0V",
                ids=frozenset({GAIA_KEY}),
            ),
            Member(1, True, "Ab", v_mag=19.19, spectral_type="T/Y"),
        ]
        choice = choose(host, members)
        assert choice.row == 0 and "Teff 6234 vs G0V 5930" in choice.evidence


class TestByLetter:
    def test_the_letter_of_the_host_name(self) -> None:
        host = Host(letters=frozenset({"B"}), teff=5270.0)
        _, members = wasp_12()
        choice = choose(host, members)
        assert choice.row == 1 and choice.evidence.startswith(BY_LETTER)

    def test_a_letter_that_no_member_has_stays(self) -> None:
        """The brightest member is no fallback for a letter that names
        another star."""
        _, members = wasp_12()
        choice = choose(Host(letters=frozenset({"D"}), teff=6265.0), members)
        assert choice.row is None and choice.evidence == BY_LETTER
        assert "no member has it" in (choice.reason or "")

    def test_a_letter_of_two_members_stays(self) -> None:
        members = [Member(0, True, "A", v_mag=9.0), Member(1, True, "A", v_mag=12.0)]
        choice = choose(Host(letters=frozenset({"A"}), mass=1.0), members)
        assert choice.row is None and "2 members have it" in (choice.reason or "")

    def test_catalogues_that_give_two_letters_stay(self) -> None:
        _, members = wasp_12()
        choice = choose(Host(letters=frozenset({"A", "B"}), teff=6265.0), members)
        assert choice.row is None and "letters A, B" in (choice.reason or "")


class TestByBrightness:
    def test_wasp_12_moves_to_a(self) -> None:
        host, members = wasp_12()
        choice = choose(host, members)
        assert choice.row == 0
        assert choice.evidence.startswith(BY_BRIGHTNESS)
        assert "Teff 6265 vs G0V 5930" in choice.evidence
        assert "V 11.50, next 15.67" in choice.evidence

    def test_values_of_another_star_stay(self) -> None:
        """A K dwarf's values do not move to a G dwarf."""
        host, members = wasp_12(teff=5100.0, mass=0.8)
        choice = choose(host, members)
        assert choice.row is None and "but" in (choice.reason or "")

    def test_nothing_to_compare_stays(self) -> None:
        host, members = wasp_12(teff=None, mass=None)
        choice = choose(host, members)
        assert choice.row is None and choice.reason is not None
        assert "no value to compare" in choice.reason

    def test_members_within_the_margin_stay(self) -> None:
        members = [
            Member(0, True, "Aa", v_mag=11.45, mass=1.0),
            Member(1, True, "Ab", v_mag=11.8, mass=1.0),
        ]
        choice = choose(Host(mass=1.0), members)
        assert choice.row is None and "within 0.5 mag" in (choice.reason or "")

    def test_the_bands_are_not_mixed(self) -> None:
        """G of one member and V of another say nothing of which is brighter."""
        members = [
            Member(0, True, "A", g_mag=9.0, mass=1.0),
            Member(1, True, "B", v_mag=12.0, mass=0.5),
        ]
        choice = choose(Host(mass=1.0), members)
        assert choice.row is None and "no band" in (choice.reason or "")

    def test_g_goes_before_v(self) -> None:
        members = [
            Member(0, True, "A", g_mag=9.0, v_mag=12.0, mass=1.0),
            Member(1, True, "B", g_mag=11.0, v_mag=9.0, mass=0.5),
        ]
        choice = choose(Host(mass=1.0), members)
        assert choice.row == 0 and "G 9.00, next 11.00" in choice.evidence

    def test_the_own_v_goes_before_the_v(self) -> None:
        """MSC 19180+4149 A and B: the V of A in comp.tsv is the light of the
        whole point, and sys.tsv gives the stars 17.36 and 17.66."""
        members = [
            Member(0, True, "A", v_mag=16.71, own_v_mag=17.36, mass=0.49),
            Member(1, True, "B", v_mag=17.66, own_v_mag=17.66, mass=0.46),
        ]
        choice = choose(Host(mass=0.49), members)
        assert choice.row is None
        assert "own V 17.36, next 17.66, within 0.5 mag" in (choice.reason or "")

    def test_an_own_v_that_one_member_lacks_stays(self) -> None:
        """The V of an MSC member can be the light of its point (Kepler-705 A:
        16.71), so it does not stand in for its own V."""
        members = [
            Member(0, True, "A", v_mag=16.71, own_v_mag=17.36, mass=0.49),
            Member(1, True, "B", v_mag=17.9, mass=0.2),
        ]
        choice = choose(Host(mass=0.49), members)
        assert choice.row is None and "no band" in (choice.reason or "")

    def test_a_value_that_the_next_member_shares_does_not_count(self) -> None:
        """HAT-P-57: the archive's 2.77 ± 1.74 agrees with either star."""
        members = [
            Member(0, True, "A", v_mag=10.5, mass=1.47),
            Member(1, True, "B", v_mag=13.0, mass=0.61),
        ]
        choice = choose(Host(mass=2.77, mass_error=1.74), members)
        assert choice.row is None and "next member" in (choice.reason or "")

    def test_a_next_member_with_no_value_tells_nothing(self) -> None:
        members = [
            Member(0, True, "A", v_mag=10.5, mass=1.0),
            Member(1, True, "B", v_mag=13.0),
        ]
        choice = choose(Host(mass=1.0), members)
        assert choice.row is None and "next member" in (choice.reason or "")

    def test_an_unnamed_brightest_member_stays(self) -> None:
        """An entry that no source names holds no ID."""
        members = [
            Member(0, False, None, v_mag=9.0, mass=1.0),
            Member(1, True, "B", v_mag=12.0, mass=0.5),
        ]
        choice = choose(Host(mass=1.0), members)
        assert choice.row is None and "no source names" in (choice.reason or "")

    def test_no_magnitudes_stay(self) -> None:
        members = [Member(0, True, "A"), Member(1, True, "B")]
        choice = choose(Host(mass=1.0), members)
        assert choice.row is None and choice.evidence == BY_BRIGHTNESS


class TestByPointId:
    """A host whose ids are its point's goes to the member that dominates the
    point's light."""

    def test_gj_504_moves_to_its_first_member(self) -> None:
        members = [
            Member(0, True, "Aa", v_mag=3.81),
            Member(1, True, "Ab", v_mag=19.19),
        ]
        choice = choose(Host(teff=6205.0, mass=1.22, of_point=True), members)
        assert choice.row == 0
        assert choice.evidence == f"{BY_POINT}: dominant member (ΔV 15.38)"

    def test_without_the_point_id_it_stays(self) -> None:
        members = [
            Member(0, True, "Aa", v_mag=3.81),
            Member(1, True, "Ab", v_mag=19.19),
        ]
        assert choose(Host(teff=6205.0), members).row is None

    def test_3_cnc_within_the_margin_stays(self) -> None:
        members = [Member(0, True, "A", v_mag=5.59), Member(1, True, "B", v_mag=8.0)]
        choice = choose(Host(teff=4170.0, of_point=True), members)
        assert choice.row is None and "ΔV 2.41" in (choice.reason or "")

    def test_hd_15337_a_letter_it_lacks_stays(self) -> None:
        """exoplanet.eu names the host TOI-402 A."""
        members = [Member(0, True, "B", v_mag=9.1), Member(1, True, "C", v_mag=15.0)]
        host = Host(letters=frozenset({"A"}), teff=5131.0, of_point=True)
        assert choose(host, members).row is None

    def test_a_fainter_first_member_stays(self) -> None:
        members = [Member(0, True, "A", v_mag=12.0), Member(1, True, "B", v_mag=9.0)]
        assert choose(Host(teff=5000.0, of_point=True), members).row is None

    def test_values_that_disagree_stay(self) -> None:
        members = [
            Member(0, True, "A", v_mag=5.0, teff=8000.0),
            Member(1, True, "B", v_mag=12.0),
        ]
        choice = choose(Host(teff=5000.0, of_point=True), members)
        assert choice.row is None and "Teff 5000 vs Teff 8000" in (choice.reason or "")

    def test_an_own_v_that_one_member_lacks_stays(self) -> None:
        """A V can hold the light of the point when a member has its own V."""
        members = [
            Member(0, True, "A", v_mag=8.0, own_v_mag=8.2),
            Member(1, True, "B", v_mag=14.0, mass=0.2),
        ]
        choice = choose(Host(mass=1.0, of_point=True), members)
        assert choice.row is None

    def test_a_lighter_member_with_no_shared_band(self) -> None:
        members = [
            Member(0, True, "A", g_mag=9.0, mass=1.0),
            Member(1, True, "B", v_mag=12.0, mass=0.3),
        ]
        choice = choose(Host(mass=1.0, of_point=True), members)
        assert choice.row == 0 and "mass ratio 0.30" in choice.evidence
