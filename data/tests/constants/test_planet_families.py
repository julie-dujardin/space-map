"""Tests for the planet family tree."""

from space_map_data.constants.planets.families import (
    FAMILIES,
    PARENTS,
    PLANET_FAMILY_PAGES,
)


def _ancestors(family: str) -> set[str]:
    found: set[str] = set()
    todo = list(PARENTS.get(family, ()))
    while todo:
        parent = todo.pop()
        if parent not in found:
            found.add(parent)
            todo.extend(PARENTS.get(parent, ()))
    return found


class TestTree:
    """The families form a tree below the Planets page, with no root family."""

    def test_every_parent_is_a_family(self):
        for family, parents in PARENTS.items():
            assert family in FAMILIES
            assert set(parents) <= set(FAMILIES), family

    def test_no_family_is_its_own_ancestor(self):
        for family in FAMILIES:
            assert family not in _ancestors(family), family

    def test_the_top_families(self):
        assert [f for f in FAMILIES if f not in PARENTS] == [
            "terrestrial-planet",
            "super-earth",
            "mini-neptune",
            "super-puff",
            "giant-planet",
            "ultra-short-period-planet",
            "circumbinary-planet",
            "pulsar-planet",
            "goldilocks-planet",
        ]

    def test_parents(self):
        assert _ancestors("jupiter-analogue") == {
            "cold-jupiter",
            "gas-giant",
            "giant-planet",
        }
        assert _ancestors("sub-earth") == {"terrestrial-planet"}
        assert _ancestors("ice-giant") == {"giant-planet"}
        assert _ancestors("super-earth") == set()


class TestPages:
    """The QIDs and the order of the families."""

    def test_a_parent_comes_before_its_children(self):
        """A planet's lists then go down the tree."""
        for family, parents in PARENTS.items():
            for parent in parents:
                assert FAMILIES.index(parent) < FAMILIES.index(family), family

    def test_each_qid_is_in_one_family(self):
        qids = [qid for qids in PLANET_FAMILY_PAGES.values() for qid in qids]
        assert len(qids) == len(set(qids))

    def test_no_page_is_on_exoplanet(self):
        """The Planets page has the exoplanet text in a tab."""
        assert "Q44559" not in {
            q for qids in PLANET_FAMILY_PAGES.values() for q in qids
        }

    def test_ice_giant(self):
        assert PLANET_FAMILY_PAGES["ice-giant"] == ("Q1319599",)

    def test_mini_neptune_is_before_sub_neptune(self):
        assert PLANET_FAMILY_PAGES["mini-neptune"] == ("Q691537", "Q97359320")
