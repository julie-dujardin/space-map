"""Tests for the pad labels shipped on ``site-`` group bundles."""

from space_map_data.export.groups.launch_site import _pad_labels


class TestPadLabels:
    """`_pad_labels` trims the place a site's pads all sit in off their tails."""

    def test_drops_the_tail_every_pad_shares(self):
        names = [
            "Space Launch Complex 40, Cape Canaveral",
            "Space Launch Complex 41, Cape Canaveral",
        ]
        assert _pad_labels(names) == [
            "Space Launch Complex 40",
            "Space Launch Complex 41",
        ]

    def test_takes_a_whole_tail_rather_than_one_part(self):
        # Baikonur's pads trail three parts; keeping only the first would read "LC200/39".
        names = [
            "LC200/39, PU39, GIK-5, Baykonur, Kazakstan",
            "LC1/5, PU5, GIK-5, Baykonur, Kazakstan",
        ]
        assert _pad_labels(names) == ["LC200/39, PU39", "LC1/5, PU5"]

    def test_a_row_that_shares_no_tail_keeps_its_name(self):
        # Baikonur's oddly punctuated Buran row is why the vote is majority, not
        # unanimous — requiring agreement would leave the site's name on all 120 others.
        names = [
            "LC200/39, PU39, GIK-5, Baykonur",
            "LC1/5, PU5, GIK-5, Baykonur",
            "Buran runway, GIK-5 Baykonur",
        ]
        assert _pad_labels(names) == [
            "LC200/39, PU39",
            "LC1/5, PU5",
            "Buran runway, GIK-5 Baykonur",
        ]

    def test_a_pad_never_gives_up_its_whole_name(self):
        assert _pad_labels(["Kourou", "Kourou"]) == ["Kourou", "Kourou"]

    def test_a_site_with_one_pad_has_no_shared_tail_to_find(self):
        assert _pad_labels(["Wallops Island LA-0A"]) == ["Wallops Island LA-0A"]

    def test_no_pads(self):
        assert _pad_labels([]) == []
