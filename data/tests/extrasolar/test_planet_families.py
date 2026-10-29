"""Tests for the planet families of the planet records."""

import pytest

from space_map_data.constants.planets.families import (
    EARTH_MASSES_PER_JUPITER,
    EARTH_RADII_PER_JUPITER,
    FAMILIES,
    ROOT_FAMILY,
)
from space_map_data.export.extrasolar.planet_families import families_of, listed

# An Earth mass and radius in the Jupiter units of the records.
ME = 1 / EARTH_MASSES_PER_JUPITER
RE = 1 / EARTH_RADII_PER_JUPITER
STAR = {"class": "star", "teff": 5772.0, "radius": None}
R = ("radius",)


def _planet(
    cls: str = "planet",
    assumed: tuple[str, ...] = (),
    estimated: tuple[str, ...] = (),
    limits: tuple[str, ...] = (),
    **values,
) -> dict:
    """A planet record with these values, true masses unless `mass_kind`
    says otherwise."""
    if "mass" in values:
        values.setdefault("mass_kind", "true")
    return {
        "class": cls,
        "values": values,
        "assumed": list(assumed),
        "estimated": list(estimated),
        "limits": list(limits),
    }


def _published(record: dict, host: dict = STAR) -> set[str]:
    published, _ = families_of(record, host)
    return set(published)


def _estimated(record: dict, host: dict = STAR) -> set[str]:
    _, estimated = families_of(record, host)
    return set(estimated)


class TestFamilies:
    """Each family's rule on measured values."""

    def test_sub_earth(self):
        record = _planet(mass=0.5 * ME, radius=0.8 * RE)
        assert _published(record) == {ROOT_FAMILY, "terrestrial-planet", "sub-earth"}

    def test_super_earth(self):
        record = _planet(mass=5 * ME, radius=1.8 * RE)
        assert _published(record) == {ROOT_FAMILY, "super-earth"}

    def test_a_small_super_earth_is_terrestrial(self):
        record = _planet(mass=1.2 * ME, radius=1.1 * RE)
        assert _published(record) == {
            ROOT_FAMILY,
            "terrestrial-planet",
            "super-earth",
        }

    def test_mega_earth(self):
        record = _planet(mass=20 * ME, radius=2.5 * RE)
        assert _published(record) == {
            ROOT_FAMILY,
            "terrestrial-planet",
            "mega-earth",
            "mini-neptune",
        }

    def test_mini_neptune_by_radius_alone(self):
        assert _published(_planet(radius=3 * RE)) == {ROOT_FAMILY, "mini-neptune"}

    def test_a_mass_and_a_radius_must_agree(self):
        """GJ 1214 b: a super-Earth mass in a mini-Neptune radius."""
        record = _planet(mass=8 * ME, radius=2.7 * RE)
        assert _published(record) == {ROOT_FAMILY, "mini-neptune"}

    def test_super_puff(self):
        record = _planet(mass=5 * ME, radius=6 * RE)
        assert _published(record) == {ROOT_FAMILY, "super-puff"}

    def test_super_neptune_and_hot_neptune(self):
        record = _planet(mass=25 * ME, radius=5 * RE, period=3.0)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "super-neptune",
            "hot-neptune",
        }

    def test_a_hot_puffy_super_jupiter(self):
        record = _planet(mass=1.5, radius=1.8, period=3.0, semi_major_axis=0.04)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "super-jupiter",
            "hot-jupiter",
            "puffy-planet",
        }

    def test_warm_jupiter(self):
        record = _planet(mass=1.0, radius=1.0, period=50.0, semi_major_axis=0.3)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "warm-jupiter",
        }

    def test_an_eccentric_jupiter_analogue(self):
        record = _planet(mass=1.0, period=4000.0, semi_major_axis=5.0, eccentricity=0.2)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "cold-jupiter",
            "jupiter-analogue",
            "eccentric-jupiter",
        }

    def test_ultra_short_period(self):
        record = _planet(radius=1.2 * RE, period=0.5)
        assert _published(record) == {
            ROOT_FAMILY,
            "terrestrial-planet",
            "super-earth",
            "ultra-short-period-planet",
        }

    def test_circumbinary(self):
        record = _planet(radius=3 * RE, binary_type="P-type")
        assert "circumbinary-planet" in _published(record)
        record = _planet(radius=3 * RE, binary_type="S-type")
        assert "circumbinary-planet" not in _published(record)

    def test_pulsar_planet(self):
        record = _planet(radius=3 * RE)
        assert "pulsar-planet" in _published(record, STAR | {"class": "pulsar"})
        assert "pulsar-planet" not in _published(record)

    def test_goldilocks_by_the_catalogue_insolation(self):
        record = _planet(radius=1.2 * RE, insolation=0.9)
        assert "goldilocks-planet" in _published(record)
        assert "goldilocks-planet" not in _published(_planet(insolation=5.0))

    def test_goldilocks_from_the_star_is_an_estimate(self):
        record = _planet(star_radius=1.0, star_teff=5772.0, semi_major_axis=1.0)
        assert _estimated(record) == {ROOT_FAMILY, "goldilocks-planet"}

    def test_goldilocks_from_the_host_radius(self):
        """HD 1461 d: no star radius in the planet's catalogue."""
        record = _planet(star_teff=5772.0, semi_major_axis=1.0)
        assert _estimated(record, STAR | {"radius": 1.0}) == {
            ROOT_FAMILY,
            "goldilocks-planet",
        }
        assert families_of(record, STAR) == ([], [])

    def test_goldilocks_needs_a_teff_in_the_zone(self):
        record = _planet(insolation=0.9)
        assert _published(record, STAR | {"teff": 9000.0}) == set()
        assert _published(record, STAR | {"teff": None}) == set()

    def test_the_bounds(self):
        """An eccentricity of 0.1 is eccentric, a period of 10 d is warm and
        not hot, and 1 AU is not cold."""
        record = _planet(mass=1.0, period=10.0, semi_major_axis=1.0, eccentricity=0.1)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "warm-jupiter",
            "eccentric-jupiter",
        }

    def test_no_values_no_family(self):
        assert families_of(_planet(), STAR) == ([], [])


class TestEvidence:
    """Measured values against estimates, limits and assumed values."""

    def test_an_estimated_radius(self):
        record = _planet(radius=3 * RE, estimated=("radius",))
        assert families_of(record, STAR) == ([], [ROOT_FAMILY, "mini-neptune"])

    def test_an_estimate_does_not_decide_beside_a_measured_value(self):
        record = _planet(mass=5 * ME, radius=1.5 * RE, estimated=("radius",))
        assert _published(record) == {ROOT_FAMILY, "super-earth"}
        assert _estimated(record) == set()

    @pytest.mark.parametrize(
        ("record", "published", "estimated"),
        [
            pytest.param(
                _planet(mass=5 * ME, mass_kind="minimum", radius=2.5 * RE, estimated=R),
                [],
                [ROOT_FAMILY, "super-earth"],
                id="KOBE-1 b",
            ),
            pytest.param(
                _planet(mass=15 * ME, radius=3 * RE, estimated=R),
                [ROOT_FAMILY, "giant-planet"],
                [],
                id="K2-111 c",
            ),
            pytest.param(
                _planet(mass=5 * ME, radius=3 * RE, estimated=R),
                [ROOT_FAMILY, "super-earth"],
                [],
                id="GJ 876 d",
            ),
            pytest.param(
                _planet(mass=5 * ME, radius=5 * RE, estimated=R),
                [ROOT_FAMILY, "super-earth"],
                [],
                id="61 Vir c",
            ),
            pytest.param(
                _planet(
                    mass=4.7, mass_kind="estimate", radius=1.2, estimated=("mass",)
                ),
                [ROOT_FAMILY, "giant-planet", "gas-giant"],
                [],
                id="K2-371 b",
            ),
        ],
    )
    def test_no_rule_uses_an_estimate_beside_a_measured_value(
        self, record, published, estimated
    ):
        """The estimated value contradicts the size of the measured one."""
        assert families_of(record, STAR) == (published, estimated)

    def test_a_density_from_an_estimate_is_no_density(self):
        """51 Peg b: an estimated radius cannot make a puffy planet."""
        record = _planet(mass=0.46, radius=1.9, period=4.2, estimated=("radius",))
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "hot-jupiter",
        }
        assert _estimated(record) == set()

    def test_the_catalogue_density(self):
        record = _planet(mass=1.0, radius=1.0, density=0.3)
        assert "puffy-planet" in _published(record)
        record = _planet(mass=1.0, radius=1.0, density=0.3, estimated=("density",))
        assert "puffy-planet" not in _published(record)

    def test_a_minimum_mass_passes_at_least(self):
        record = _planet(mass=2.0, mass_kind="minimum", period=3.0)
        assert _published(record) == {
            ROOT_FAMILY,
            "giant-planet",
            "gas-giant",
            "super-jupiter",
            "hot-jupiter",
        }

    def test_a_minimum_mass_below_at_least_fails(self):
        record = _planet(mass=0.2, mass_kind="minimum", period=3.0)
        assert "gas-giant" not in _published(record) | _estimated(record)

    def test_a_minimum_mass_in_at_most_is_an_estimate(self):
        """Proxima Cen b: 1.07 M⊕ minimum mass in the habitable zone."""
        record = _planet(mass=1.07 * ME, mass_kind="minimum", insolation=0.65)
        assert families_of(record, STAR | {"teff": 3000.0}) == (
            [ROOT_FAMILY, "goldilocks-planet"],
            ["terrestrial-planet", "super-earth"],
        )

    def test_an_upper_limit_on_a_minimum_mass_gives_no_bound(self):
        record = _planet(mass=0.5, mass_kind="minimum", limits=("mass<",))
        assert families_of(record, STAR) == ([], [])

    def test_an_upper_limit_that_settles(self):
        record = _planet(radius=1.2 * RE, limits=("radius<",))
        assert _published(record) == {ROOT_FAMILY, "terrestrial-planet"}

    def test_an_upper_limit_that_does_not_settle(self):
        record = _planet(mass=15 * ME, limits=("mass<",))
        assert families_of(record, STAR) == ([], [])

    def test_terrestrial_by_mass_when_the_radius_does_not_settle_it(self):
        record = _planet(mass=1 * ME, radius=3 * RE, limits=("radius<",))
        assert _published(record) == {
            ROOT_FAMILY,
            "terrestrial-planet",
            "super-earth",
        }

    def test_an_unsettled_limit_leaves_the_other_value(self):
        record = _planet(mass=15 * ME, radius=1.8 * RE, limits=("mass<",))
        assert _published(record) == {ROOT_FAMILY, "super-earth"}

    def test_a_lower_limit(self):
        record = _planet(mass=1.0, eccentricity=0.2, limits=("eccentricity>",))
        assert "eccentric-jupiter" in _published(record)

    def test_an_assumed_value_is_not_used(self):
        record = _planet(mass=1.0, eccentricity=0.2, assumed=("eccentricity",))
        assert "eccentric-jupiter" not in _published(record) | _estimated(record)

    def test_one_estimated_part_makes_the_family_estimated(self):
        record = _planet(mass=1.0, radius=1.0, period=3.0, estimated=("period",))
        assert _published(record) == {ROOT_FAMILY, "giant-planet", "gas-giant"}
        assert _estimated(record) == {"hot-jupiter"}

    def test_published_wins(self):
        published, estimated = families_of(
            _planet(mass=1.07 * ME, mass_kind="minimum", insolation=0.65), STAR
        )
        assert not set(published) & set(estimated)

    @pytest.mark.parametrize("cls", ["brown dwarf", "sub-brown dwarf"])
    def test_brown_dwarfs_get_none(self, cls):
        record = _planet(cls, mass=30.0, radius=1.0, period=3.0)
        assert families_of(record, STAR) == ([], [])

    def test_lists_are_in_family_order(self):
        record = _planet(mass=1.5, radius=1.8, period=3.0, binary_type="P-type")
        published, _ = families_of(record, STAR)
        assert published == [f for f in FAMILIES if f in published]


class TestListed:
    """The families of metadata.json."""

    def test_shape(self):
        entries = listed({"gas-giant": 3}, {"gas-giant": 1, "mini-neptune": 2})
        assert [entry["slug"] for entry in entries] == list(FAMILIES)
        by_slug = {entry["slug"]: entry for entry in entries}
        assert by_slug["gas-giant"] == {
            "slug": "gas-giant",
            "wikidata": ["Q121750"],
            "parents": ["giant-planet"],
            "published": 3,
            "estimated": 1,
        }
        assert by_slug["mini-neptune"]["wikidata"] == ["Q691537", "Q97359320"]
        assert by_slug[ROOT_FAMILY]["parents"] == []
        assert by_slug["hot-jupiter"]["published"] == 0
