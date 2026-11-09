"""Tests for the sizes and colours of listed stars.

The lineup reads the radius that the extrasolar export chose, so a star draws
at the same size here as in the scene.
"""

import pytest

from space_map_data.constants.stars import binaries
from space_map_data.constants.stars.literature import REFERENCES
from space_map_data.export.groups.star_lineup import (
    JMDC,
    WORKS,
    _bp_rp,
    add_lineup_fields,
    drawable_star_radii,
)
from space_map_data.export.names import Names
from space_map_data.export.notable import NotableObject
from space_map_data.extrasolar.exoplanets.catalogues import EU


def colour(**values: float | None) -> dict:
    return {
        "teff": None,
        "phot_bp_mean_mag": None,
        "phot_rp_mean_mag": None,
        "v_i": None,
        **values,
    }


def size(radius: float | None, source: str | None = None, **more) -> dict:
    return {"radius": radius, "radius_source": source, "cross_ids": [], **more}


def star(id_: int) -> NotableObject:
    return NotableObject(f"x-{id_}", None, Names(""), None, None, extrasolar=True)


class FakeReader:
    def __init__(self, tables: dict[str, dict[int, dict]]) -> None:
        self.tables = tables

    def rows(self, slug: str, ids: list[int], columns: list[str]) -> dict[int, dict]:
        """As the tiles serve them: a column that a row leaves out is null."""
        table = self.tables.get(slug, {})
        return {
            id_: {name: table[id_].get(name) for name in columns}
            for id_ in ids
            if id_ in table
        }


def bp_rp(found: dict) -> float | None:
    return _bp_rp({1: found})[1]


class TestColour:
    def test_prefers_gaia(self) -> None:
        assert bp_rp(colour(phot_bp_mean_mag=2.5, phot_rp_mean_mag=1.0, v_i=9)) == 1.5

    def test_falls_back_to_hipparcos_v_i(self) -> None:
        assert bp_rp(colour(v_i=2.32)) == pytest.approx(2.5, abs=0.05)

    def test_none_without_either(self) -> None:
        assert bp_rp(colour()) is None


class TestDrawableStars:
    """`drawable_star_radii` asks what the comparison row asks of a star."""

    def radii(self, ids: list[int], **tables: dict) -> dict[int, float]:
        reader = FakeReader(tables)
        return drawable_star_radii(reader, ids)  # ty: ignore[invalid-argument-type]

    def test_a_size_and_a_temperature(self) -> None:
        radii = self.radii(
            [1],
            metadata={1: size(2.0, "gaia-dr3-flame")},
            **{"point-source": {1: colour(teff=5000.0)}},
        )
        assert radii == {1: 1390000.0}

    def test_no_size_or_no_colour_draws_nothing(self) -> None:
        radii = self.radii(
            [1, 2],
            metadata={1: size(None), 2: size(2.0, "gaia-dr3-flame")},
            **{"point-source": {1: colour(teff=5000.0), 2: colour()}},
        )
        assert radii == {}

    def test_a_system_stands_for_its_primary(self) -> None:
        radii = self.radii(
            [9],
            metadata={1: size(2.0, "gaia-dr3-flame")},
            system={9: {"primary": 1}},
            **{"point-source": {1: colour(teff=5000.0)}},
        )
        assert radii == {9: 1390000.0}

    @staticmethod
    def sirius(dominant: bool, teff: float | None = 9940.0) -> dict:
        """Point 5 holds A (6) and the white dwarf B; A has its radius."""
        return {
            "metadata": {5: size(None), 6: size(1.71, "jmdc"), 9: size(None)},
            "system": {
                5: {
                    "primary": 5,
                    "point": True,
                    "members": [{"id": 6}, {"id": None}],
                },
                6: {"primary": None, "star": [{"teff": teff, "dominant": dominant}]},
            },
            "point-source": {5: colour(teff=9500.0)},
        }

    def test_a_point_stands_for_its_dominant_star(self) -> None:
        assert self.radii([5], **self.sirius(True)) == {5: 1190000.0}

    def test_a_point_whose_light_can_blend_has_no_size(self) -> None:
        assert self.radii([5], **self.sirius(False)) == {}

    def test_the_dominant_star_takes_the_colour_of_its_point(self) -> None:
        assert self.radii([5, 6], **self.sirius(True, teff=None)) == {5: 1190000.0}

    def test_a_system_stands_for_the_dominant_star_of_its_primary(self) -> None:
        tables = self.sirius(True)
        tables["system"][9] = {"primary": 5}
        assert self.radii([9], **tables) == {9: 1190000.0}

    def test_a_held_star_takes_the_teff_of_its_system_row(self) -> None:
        radii = self.radii(
            [6],
            metadata={6: size(1.69, EU)},
            system={6: {"primary": None, "star": [{"teff": 6265.0}]}},
        )
        assert radii == {6: 1180000.0}


class TestLineupFields:
    def test_the_work_follows_the_source(self) -> None:
        member, jmdc, paper = (star(i) for i in (1, 2, 3))
        literature = [
            {
                "catalogue": "literature",
                "release": "star",
                "catalogue_id": "hd/1949/58061",
            }
        ]
        reader = FakeReader(
            {
                "metadata": {
                    1: size(0.14, EU),
                    2: size(10.0, "jmdc"),
                    3: size(1420.0, "literature", cross_ids=literature),
                },
                "point-source": {i: colour(teff=3000.0) for i in (1, 2, 3)},
            }
        )
        add_lineup_fields(reader, {"page": [member, jmdc, paper]})  # ty: ignore[invalid-argument-type]
        assert member.radii is not None and member.radii["source"] == EU
        assert member.radii["reference"] == dict(WORKS[EU]._asdict())
        assert jmdc.radii is not None and jmdc.radii["reference"] == dict(
            JMDC._asdict()
        )
        assert paper.radii is not None
        assert paper.radii["reference"] == dict(REFERENCES["wittkowski_2012"]._asdict())
        assert member.teff == 3000.0

    def test_a_held_star_cites_where_its_paper_radius_came_from(self) -> None:
        """A held star has no literature cross-id: its paper radius is its
        pair's paper, or the paper of the point whose measurement it takes."""
        from_pair, from_point = star(6), star(7)
        literature = [
            {
                "catalogue": "literature",
                "release": "star",
                "catalogue_id": "hd/1949/58061",
            }
        ]
        pair_paper = [{"source": "literature", "reference": "doyle_2011"}]
        reader = FakeReader(
            {
                "metadata": {
                    5: size(None, cross_ids=literature),
                    6: size(0.65, "literature"),
                    7: size(1420.0, "literature"),
                },
                "system": {
                    6: {
                        "parent": 4,
                        "star": [
                            {
                                "teff": 4450.0,
                                "radius_source": "literature",
                                "references": pair_paper,
                            }
                        ],
                    },
                    7: {
                        "parent": 5,
                        "star": [
                            {"teff": 3000.0, "radius_source": None, "references": []}
                        ],
                    },
                },
            }
        )
        add_lineup_fields(reader, {"page": [from_pair, from_point]})  # ty: ignore[invalid-argument-type]
        assert from_pair.radii is not None and from_point.radii is not None
        assert from_pair.radii["reference"] == dict(
            binaries.REFERENCES["doyle_2011"]._asdict()
        )
        assert from_point.radii["reference"] == dict(
            REFERENCES["wittkowski_2012"]._asdict()
        )

    def test_a_paper_radius_that_nothing_traces_credits_no_work(self) -> None:
        """A pair's paper with no work, and a point with no paper, give a
        size with no reference."""
        stars = [star(i) for i in (6, 7, 8)]
        reader = FakeReader(
            {
                "metadata": {
                    5: size(None),
                    6: size(0.65, "literature"),
                    7: size(1.2, "literature"),
                    8: size(0.9, "literature"),
                },
                "system": {
                    6: {
                        "parent": 4,
                        "star": [
                            {
                                "teff": 4450.0,
                                "radius_source": "literature",
                                "references": [],
                            }
                        ],
                    },
                    7: {
                        "parent": 5,
                        "star": [
                            {"teff": 3000.0, "radius_source": None, "references": []}
                        ],
                    },
                },
            }
        )
        add_lineup_fields(reader, {"page": stars})  # ty: ignore[invalid-argument-type]
        for member in stars[:2]:
            assert member.radii is not None and "reference" not in member.radii
        assert stars[2].radii is not None and "reference" not in stars[2].radii
