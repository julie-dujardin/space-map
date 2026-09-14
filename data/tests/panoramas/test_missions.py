from space_map_data.panoramas.missions import MISSION_NAIF, body_id, probe_id


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
        assert all(probe_id(mission) for mission in MISSION_NAIF)

    def test_an_unmapped_mission_links_nothing(self):
        assert probe_id("venera13") is None
        assert probe_id(None) is None


class TestBodyId:
    """The world a traverse is on, without which the export drops it."""

    def test_every_mission_with_a_probe_names_its_world(self):
        """A traverse the export cannot place a body for never reaches the map."""
        assert all(body_id(mission) for mission in MISSION_NAIF)
        assert body_id("perseverance") == "naif-499"
        assert body_id("yutu-2") == "naif-301"

    def test_an_unmapped_mission_names_no_world(self):
        assert body_id("apollo15") is None
