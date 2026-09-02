"""Which Wikidata entity an object's page is built from.

A launch is catalogued once, so a capsule, a lander and the craft that carried
them share one NORAD. Reading identity off that row gives the siblings one
name, one description and one photograph between them, which is how a sample
capsule ends up presented as the spacecraft that dropped it.
"""

from space_map_data.export.objects.wikidata_claims import resolve_wikidata_qid
from space_map_data.models.object import ObjectType, OrbitalSource, Satcat

from tests.conftest import make_object


def _satcat(qid: str | None) -> Satcat:
    return Satcat(NORAD_CAT_ID=27809, wikidata_qid=qid)


def _probe(**overrides):
    return make_object(
        id="probe-87474177",
        name="Hayabusa SRC",
        object_type=ObjectType.spacecraft,
        orbital_source=OrbitalSource.spice_probe,
        probe_id=87474177,
        norad_cat_id=27809,
        **overrides,
    )


class TestProbeIdentity:
    """A probe answers to the registry, never to the launch's SATCAT row."""

    def test_a_probe_does_not_borrow_its_satcat_rows_entity(self):
        obj = _probe(wikidata_qid=None)
        obj.satcat = _satcat("Q275444")
        assert resolve_wikidata_qid(obj) is None

    def test_a_probes_own_qid_still_wins(self):
        obj = _probe(wikidata_qid="Q112958759")
        obj.satcat = _satcat("Q275444")
        assert resolve_wikidata_qid(obj) == "Q112958759"


class TestSatelliteIdentity:
    """An Earth satellite is the SATCAT row, so it may borrow its entity."""

    def test_a_satellite_borrows_its_satcat_rows_entity(self):
        obj = make_object(
            id="norad_satcat-27809",
            object_type=ObjectType.spacecraft,
            orbital_source=OrbitalSource.spacetrack,
            norad_cat_id=27809,
            wikidata_qid=None,
        )
        obj.satcat = _satcat("Q275444")
        assert resolve_wikidata_qid(obj) == "Q275444"

    def test_a_row_with_no_entity_resolves_to_nothing(self):
        obj = make_object(
            id="norad_satcat-27809",
            object_type=ObjectType.spacecraft,
            orbital_source=OrbitalSource.spacetrack,
            norad_cat_id=27809,
            wikidata_qid=None,
        )
        obj.satcat = _satcat(None)
        assert resolve_wikidata_qid(obj) is None
