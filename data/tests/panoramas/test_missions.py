from space_map_data.panoramas.missions import probe_id


class TestProbeId:
    """The mission slug on a traverse resolved back to the craft that drove it."""

    def test_a_mapped_mission_names_its_probe(self):
        assert probe_id("curiosity") == "probe-100265984"
        assert probe_id("perseverance") == "probe-113246208"

    def test_an_unmapped_mission_links_nothing(self):
        assert probe_id("venera13") is None
        assert probe_id(None) is None
