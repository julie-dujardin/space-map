"""Tests for the planet family tree."""

from space_map_data.constants.planets.families import (
    FAMILIES,
    PARENTS,
    PLANET_FAMILY_PAGES,
    ROOT_FAMILY,
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
    """Every family is in one tree below the root."""

    def test_every_parent_is_a_family(self):
        for family, parents in PARENTS.items():
            assert family in FAMILIES
            assert set(parents) <= set(FAMILIES), family

    def test_only_the_root_has_no_parent(self):
        assert set(PARENTS) == set(FAMILIES) - {ROOT_FAMILY}

    def test_the_root_is_above_every_other_family(self):
        for family in FAMILIES:
            if family != ROOT_FAMILY:
                assert ROOT_FAMILY in _ancestors(family), family
                assert family not in _ancestors(family), family

    def test_parents(self):
        assert _ancestors("jupiter-analogue") == {
            "cold-jupiter",
            "gas-giant",
            "giant-planet",
            ROOT_FAMILY,
        }
        assert _ancestors("sub-earth") == {"terrestrial-planet", ROOT_FAMILY}
        assert _ancestors("super-earth") == {ROOT_FAMILY}


class TestPages:
    """The QIDs and the order of the families."""

    def test_a_parent_comes_before_its_children(self):
        """A planet's lists then start at the root and go down the tree."""
        assert FAMILIES[0] == ROOT_FAMILY
        for family, parents in PARENTS.items():
            for parent in parents:
                assert FAMILIES.index(parent) < FAMILIES.index(family), family

    def test_each_qid_is_in_one_family(self):
        qids = [qid for qids in PLANET_FAMILY_PAGES.values() for qid in qids]
        assert len(qids) == len(set(qids))

    def test_the_root_page_is_exoplanet(self):
        assert PLANET_FAMILY_PAGES[ROOT_FAMILY] == ("Q44559",)

    def test_mini_neptune_is_before_sub_neptune(self):
        assert PLANET_FAMILY_PAGES["mini-neptune"] == ("Q691537", "Q97359320")
