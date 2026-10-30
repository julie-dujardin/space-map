"""Where the Wikidata items go, on the real cases of the round-6 registry.

The classes are as the download gives them, the numbers are the registry IDs
of the stars, points and nodes.
"""

import pytest

from space_map_data.download.providers.stars.wikidata_stars import StarItem
from space_map_data.extrasolar.sources import wikidata
from space_map_data.extrasolar.sources.wikidata import (
    MIXED,
    OTHER,
    STAR,
    SYSTEM,
    Reach,
    kind,
    names_component,
    place,
)

# Star classes.
STAR_CLASS = "Q523"
HIGH_PROPER_MOTION = "Q2247863"
NAVIGATIONAL = "Q1547772"
VARIABLE = "Q6243"
DELTA_SCUTI = "Q836976"
RED_DWARF = "Q5893"
# System classes.
BINARY = "Q50053"
DOUBLE = "Q13890"
OPTICAL_DOUBLE = "Q3037794"
MULTIPLE = "Q878367"
TRIPLE = "Q2088753"
SPECTROSCOPIC = "Q1993624"
# Kinds of star and of star system.
ECLIPSING = "Q1457376"
ALGOL_TYPE = "Q24452"

HIP, GAIA, HD = range(3)


def item(
    qid: str,
    label: str | None,
    articles: int = 1,
    stars: tuple[str, ...] = (),
    systems: tuple[str, ...] = (),
    mul: str | None = None,
) -> StarItem:
    """An item with these classes: `stars` reach a star, `systems` a star
    system. A class in both is a kind of star and of star system."""
    return StarItem(
        qid=qid,
        gaia_dr3=(),
        hip=(),
        hd=(),
        label_en=label,
        label_mul=mul,
        articles=articles,
        star_classes=stars,
        system_classes=systems,
    )


def where(*reaches: Reach) -> dict[str, tuple[int | None, str]]:
    return {found.qid: (found.node, found.case) for found in place(reaches)}


SIRIUS_A = item("Q13415844", "Sirius A", 2, (HIGH_PROPER_MOTION, STAR_CLASS))
SIRIUS = item("Q3409", "Sirius", 12, (NAVIGATIONAL,), (SPECTROSCOPIC,))
CASTOR = item("Q13029", "Castor", 12, systems=(MULTIPLE,))
ALGOL = item(
    "Q13080",
    "Algol",
    12,
    (ALGOL_TYPE, ECLIPSING),
    (ALGOL_TYPE, ECLIPSING, SPECTROSCOPIC, DOUBLE),
)
# A transit host that Wikidata types as an eclipsing binary.
WASP_45 = item(
    "Q4052848",
    None,
    1,
    (HIGH_PROPER_MOTION, ECLIPSING),
    (ECLIPSING,),
    mul="WASP-45",
)
# Typed only with survey classes.
ZETA_AQUARII = item("Q13252", "Zeta Aquarii", 8)
TOLIMAN = item(
    "Q1052548",
    "Alpha Centauri B",
    4,
    (HIGH_PROPER_MOTION, STAR_CLASS),
    (DOUBLE,),
    mul="Toliman",
)


class TestKind:
    """What an item is about, by its classes."""

    @pytest.mark.parametrize(
        ("found", "expected"),
        [
            (SIRIUS_A, STAR),
            # A spectroscopic binary is no kind of star.
            (SIRIUS, MIXED),
            (CASTOR, SYSTEM),
            (ALGOL, MIXED),
            # An eclipsing binary is a kind of star: one point that is a pair.
            (WASP_45, STAR),
            (ZETA_AQUARII, OTHER),
        ],
    )
    def test_kinds(self, found, expected):
        assert kind(found) == expected


class TestNamesComponent:
    """A label that ends in a component letter."""

    @pytest.mark.parametrize(
        ("label", "mul", "expected"),
        [
            ("Alpha Centauri B", "Toliman", True),
            (None, "Alpha Centauri B", True),
            ("61 Ophiuchi A", None, True),
            ("Fomalhaut C", None, True),
            ("Xi Ursae Majoris Ba", None, True),
            ("Sirius", "Sirius", False),
            ("Gamma¹ Andromedae", "Almach", False),
            # A pair of components names a system.
            ("Alpha Centauri AB", None, False),
            (None, None, False),
        ],
    )
    def test_labels(self, label, mul, expected):
        assert names_component(item("Q1", label, mul=mul)) is expected


class TestStarItemsWin:
    """(a) A star item keeps its star; the system item goes on to its node."""

    def test_sirius_a(self):
        star, root = 22137869, 55692301
        assert where(
            Reach(SIRIUS_A, star, HIP, root=root), Reach(SIRIUS, star, HD, root=root)
        ) == {
            "Q13415844": (0, wikidata.WINS),
            "Q3409": (root, wikidata.TO_ROOT),
        }

    def test_41_aurigae_a(self):
        star, root = 18541642, 52096074
        a = item("Q3599079", "41 Aurigae A", 1, (HIGH_PROPER_MOTION,))
        system = item(
            "Q66477085", "41 Aurigae", 3, (HIGH_PROPER_MOTION,), (BINARY, DOUBLE)
        )
        assert where(
            Reach(a, star, GAIA, root=root), Reach(system, star, HIP, root=root)
        ) == {
            "Q3599079": (0, wikidata.WINS),
            "Q66477085": (root, wikidata.TO_ROOT),
        }

    def test_alpha_crucis_on_the_point_of_acrux(self):
        """The star item wins the point; the system item goes to the root."""
        point, root = 27789029, 61343461
        acrux = item("Q66476660", "Acrux", 9, (STAR_CLASS,))
        alpha_crucis = item(
            "Q13102",
            "Alpha Crucis",
            3,
            (NAVIGATIONAL, STAR_CLASS),
            (MULTIPLE, SPECTROSCOPIC, BINARY),
        )
        assert where(
            Reach(acrux, point, HD, point, root),
            Reach(alpha_crucis, point, HIP, point, root),
        ) == {
            "Q66476660": (0, wikidata.WINS),
            "Q13102": (root, wikidata.TO_ROOT),
        }

    def test_p_eridani_a_keeps_hip_7751(self):
        """Of two star items, the Hipparcos claim wins over the Gaia claim of
        the companion. The system item goes to the node that its ids name."""
        star, root = 562581742, 59265262
        a = item("Q1147410", "p Eridani A", 1, (HIGH_PROPER_MOTION, STAR_CLASS))
        b = item("Q18380782", "p Eridani B", 2, (HIGH_PROPER_MOTION, STAR_CLASS))
        system = item("Q83969658", "p Eridani", 5, (STAR_CLASS,), (BINARY, DOUBLE))
        assert where(
            Reach(a, star, HIP, root=root),
            Reach(b, star, GAIA, root=root),
            Reach(system, star, HIP, root=root, named=root, named_root=root),
        ) == {
            "Q1147410": (0, wikidata.WINS),
            "Q18380782": (None, wikidata.OUTRANKED),
            "Q83969658": (root, wikidata.TO_NAMED),
        }

    def test_gn_andromedae_on_a_point_that_is_its_system(self):
        """The system item that loses a point with no system above is left
        off."""
        point = 21977390
        gn = item("Q98537993", "GN Andromedae", 1, (DELTA_SCUTI,))
        system = item(
            "Q2720509", "28 Andromedae", 6, (VARIABLE, DELTA_SCUTI), (TRIPLE,)
        )
        assert where(
            Reach(gn, point, HIP, point, point),
            Reach(system, point, HIP, point, point),
        ) == {
            "Q98537993": (0, wikidata.WINS),
            "Q2720509": (None, wikidata.OUTRANKED),
        }

    def test_of_two_mixed_items_the_claim_wins_the_point_of_dabih(self):
        """β Cap A's item claims HIP 100345, β Cap's the Gaia source."""
        point, root = 29284569, 62839001
        a = item("Q11078478", None, 1, (VARIABLE,), (BINARY, SPECTROSCOPIC))
        system = item(
            "Q1068047", "Beta Capricorni", 11, (STAR_CLASS,), (DOUBLE, BINARY)
        )
        assert where(
            Reach(a, point, HIP, point, root), Reach(system, point, GAIA, point, root)
        ) == {
            "Q11078478": (0, wikidata.ON_POINT),
            "Q1068047": (root, wikidata.TO_ROOT),
        }


class TestSystemItemsGoToTheirNode:
    """(b) A system or mixed item on a star of a system goes to its node."""

    def test_50_arietis_goes_to_the_root(self):
        star, root = 16841950, 50396382
        system = item("Q4405146", "50 Arietis", 1, (STAR_CLASS,), (DOUBLE, BINARY))
        assert where(Reach(system, star, HIP, root=root)) == {
            "Q4405146": (root, wikidata.TO_ROOT)
        }

    def test_of_two_mixed_items_on_almach_the_most_articles_wins_the_root(self):
        """γ¹ And finds the root taken and stays on its star."""
        star, root = 17407007, 50961439
        gamma_1 = item(
            "Q13046", "Gamma¹ Andromedae", 1, (STAR_CLASS,), (SPECTROSCOPIC,)
        )
        gamma = item("Q66477099", "Gamma Andromedae", 11, (STAR_CLASS,), (MULTIPLE,))
        assert where(
            Reach(gamma_1, star, HIP, root=root), Reach(gamma, star, HIP, root=root)
        ) == {
            "Q66477099": (root, wikidata.TO_ROOT),
            "Q13046": (0, wikidata.TAKEN_MIXED),
        }

    @pytest.mark.parametrize(
        ("found", "star", "root"),
        [
            (TOLIMAN, 564339647, 597894079),
            (
                item("Q10948228", "61 Ophiuchi A", 1, (STAR_CLASS,), (BINARY,)),
                24737212,
                58291644,
            ),
            (
                item("Q15875316", "Fomalhaut C", 5, (RED_DWARF,), (BINARY,)),
                28825022,
                599218983,
            ),
        ],
    )
    def test_a_label_that_names_a_component_stays_on_its_star(self, found, star, root):
        assert where(Reach(found, star, HIP, root=root)) == {
            found.qid: (0, wikidata.COMPONENT)
        }

    def test_17_crateris_holds_its_root(self):
        """The root has an item of its own, so the mixed item of 17 Crt A
        stays on its star."""
        star, root = 23111531, 56665963
        a = item("Q10847382", None, 1, (HIGH_PROPER_MOTION,), (BINARY,))
        system = item("Q4553532", "17 Crateris", 3, systems=(BINARY,))
        assert where(
            Reach(a, star, GAIA, root=root),
            Reach(system, star, HIP, root=root, named=root, named_root=root),
        ) == {
            "Q4553532": (root, wikidata.TO_NAMED),
            "Q10847382": (0, wikidata.TAKEN_MIXED),
        }

    def test_a_system_item_finds_its_root_taken(self):
        """Xi UMa has its own item, so the system item of Xi UMa B is left
        off."""
        root = 51708356
        b = item("Q1072624", None, 1, systems=(MULTIPLE,), mul="HD 98230")
        system = item(
            "Q66531057",
            "Xi Ursae Majoris",
            1,
            ("Q1392913", VARIABLE),
            (DOUBLE, "Q1392913"),
        )
        point = 18153924
        assert where(
            Reach(b, 555024836, GAIA, root=root),
            Reach(system, point, HIP, point, root, root, root),
        ) == {
            "Q66531057": (root, wikidata.TO_NAMED),
            "Q1072624": (None, wikidata.TAKEN_SYSTEM),
        }

    def test_epsilon_lyrae_goes_up_from_the_cd_node(self):
        """Both items name ε² Lyr's node by HIP 91926. The item about the
        smaller part keeps it, and ε Lyr goes to the root."""
        star, cd, root = 20593823, 54148255, 591019232
        epsilon = item("Q13355", "Epsilon Lyrae", 8, systems=(MULTIPLE,))
        epsilon_2 = item(
            "Q75821643", None, 1, (VARIABLE,), (DOUBLE, BINARY), mul="* eps02 Lyr"
        )
        assert where(
            Reach(epsilon, star, HIP, root=root, named=cd, named_root=root),
            Reach(epsilon_2, star, HIP, root=root, named=cd, named_root=root),
        ) == {
            "Q75821643": (cd, wikidata.TO_NAMED),
            "Q13355": (root, wikidata.TO_ROOT),
        }

    def test_an_item_of_no_kind_follows_its_ids(self):
        """Zeta Aquarii names the root by HIP 110960. Zeta² Aquarii keeps its
        point."""
        point, root = 21648730, 592074074
        zeta_2 = item("Q10395052", "Zeta2 Aquarii", 1, (STAR_CLASS,), (BINARY, DOUBLE))
        assert where(
            Reach(ZETA_AQUARII, point, HIP, point, root, root, root),
            Reach(zeta_2, point, GAIA, point, root),
        ) == {
            "Q13252": (root, wikidata.TO_NAMED),
            "Q10395052": (0, wikidata.TAKEN_MIXED),
        }


class TestStarsInNoSystem:
    """(c) A system item on a star in no system stays on it until we hold
    its system; (d) a mixed one stays too."""

    def test_mira(self):
        """Mira is typed only binary star, and we hold no Mira B."""
        mira = item("Q12965", "Mira", 12, systems=(BINARY,))
        assert where(Reach(mira, 21312666, HIP)) == {
            "Q12965": (0, wikidata.ALONE_SYSTEM)
        }

    def test_a_system_item_that_loses_the_star(self):
        star = item("Q1", "Mira A", 1, (STAR_CLASS,))
        mira = item("Q12965", "Mira", 12, systems=(BINARY,))
        assert where(Reach(star, 21312666, HIP), Reach(mira, 21312666, GAIA)) == {
            "Q1": (0, wikidata.WINS),
            "Q12965": (None, wikidata.OUTRANKED),
        }

    def test_mira_goes_to_its_system_once_we_hold_it(self):
        mira = item("Q12965", "Mira", 12, systems=(BINARY,))
        assert where(Reach(mira, 21312666, HIP, root=600000000)) == {
            "Q12965": (600000000, wikidata.TO_ROOT)
        }

    def test_ain(self):
        ain = item(
            "Q405857",
            "Ain",
            8,
            (STAR_CLASS,),
            (DOUBLE, OPTICAL_DOUBLE),
        )
        assert where(Reach(ain, 16864576, HIP)) == {
            "Q405857": (0, wikidata.ALONE_MIXED)
        }

    def test_a_star_item_stays(self):
        assert where(Reach(WASP_45, 20976962, GAIA, root=54531394)) == {
            "Q4052848": (0, wikidata.ON_STAR)
        }


class TestInnerPairs:
    """(e) No id names the root of Capella, Algol, Castor or Mizar, so each
    stays on the inner pair that its ids name."""

    def test_capella_and_algol_keep_their_points(self):
        capella = item("Q12970", "Capella", 12, (NAVIGATIONAL,), (MULTIPLE,))
        assert where(
            Reach(capella, 17162358, HIP, 17162358, 50716790),
            Reach(ALGOL, 17213524, HIP, 17213524, 50767956),
        ) == {
            "Q12970": (0, wikidata.INNER),
            "Q13080": (0, wikidata.INNER),
        }

    def test_castor_and_mizar_keep_their_ab_nodes(self):
        mizar = item("Q66477109", "Mizar", 12, (STAR_CLASS,), (DOUBLE, BINARY))
        assert where(
            Reach(CASTOR, 18400388, HIP, 18400388, 588825732, 51954820, 588825732),
            Reach(mizar, 19621370, HIP, 19621370, 590046714, 53175802, 590046714),
        ) == {
            "Q13029": (51954820, wikidata.INNER),
            "Q66477109": (53175802, wikidata.INNER),
        }

    def test_an_inner_pair_below_a_root_with_an_item(self):
        point, root = 17162358, 50716790
        capella = item("Q12970", "Capella", 12, (NAVIGATIONAL,), (MULTIPLE,))
        other = item("Q1", "Other", 1, (STAR_CLASS,), (BINARY,))
        assert where(
            Reach(capella, point, HIP, point, root),
            Reach(other, 2, HIP, root=root),
        ) == {
            "Q12970": (0, wikidata.ON_POINT),
            "Q1": (root, wikidata.TO_ROOT),
        }
