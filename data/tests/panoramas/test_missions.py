from space_map_data.probes.probe_id import load_registry

from space_map_data.panoramas.missions import MISSION_PROBE, body_id, probe_id


class TestProbeId:
    """The mission slug on a traverse resolved back to the craft that drove it."""

    def test_a_mapped_mission_names_its_probe(self):
        assert probe_id("curiosity") == "probe-100265984"
        assert probe_id("perseverance") == "probe-113246208"

    def test_both_mars_exploration_rovers_are_their_own_craft(self):
        assert probe_id("spirit") == "probe-87605248"
        assert probe_id("opportunity") == "probe-87719936"

    def test_every_mapped_mission_resolves_through_the_probe_inventory(self):
        """A slug mapped to a craft the inventory does not carry links nothing,
        which would silently drop a probe page rather than fail."""
        assert all(probe_id(mission) for mission in MISSION_PROBE)

    def test_every_mapped_probe_is_the_craft_that_drove_the_traverse(self):
        """NAIF ids are recycled, so the slugs are keyed on probe ids instead.
        Nothing at run time reads the inventory back, which leaves this as the
        one place a mistyped id is caught."""
        named = {int(entry["probe_id"]): entry["name"] for entry in load_registry()}
        assert {slug: named.get(probe) for slug, probe in MISSION_PROBE.items()} == {
            "curiosity": "Curiosity (MSL)",
            "perseverance": "Perseverance",
            "spirit": "Spirit (MER-A)",
            "opportunity": "Opportunity (MER-B)",
            "insight": "InSight",
            "phoenix": "Phoenix",
            "pathfinder": "Mars Pathfinder",
            "viking1": "Viking 1 Lander",
            "viking2": "Viking 2 Lander",
            "zhurong": "Zhurong",
            "yutu": "Yutu",
            "yutu-2": "Yutu-2",
        }

    def test_a_recycled_naif_id_no_longer_decides_anything(self):
        """Curiosity and Mariner 10 both answer to NAIF -76, and the inventory
        holds both; keying on that id made the link depend on their order."""
        recycled = [e for e in load_registry() if e.get("naif_id") == -76]

        assert len(recycled) > 1
        assert probe_id("curiosity") == "probe-100265984"

    def test_an_unmapped_mission_links_nothing(self):
        assert probe_id("venera13") is None
        assert probe_id(None) is None


class TestBodyId:
    """The world a traverse is on, without which the export drops it."""

    def test_every_mission_with_a_probe_names_its_world(self):
        """A traverse the export cannot place a body for never reaches the map."""
        assert all(body_id(mission) for mission in MISSION_PROBE)
        assert body_id("perseverance") == "naif-499"
        assert body_id("yutu-2") == "naif-301"

    def test_an_unmapped_mission_names_no_world(self):
        assert body_id("apollo15") is None
