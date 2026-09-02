"""Bus resolution from GCAT's Bus column, and the splits it cannot express.

GCAT files GPS Block I and IIA under one "GPS" string, IIR with IIR-M under
"Series 4000", GLONASS-M with the first generation under "Uragan", and Galileo
IOV with FOC under "GalileoSat" — it classifies by platform lineage, not by
generation. The per-generation buses shown here survive only through the
``norad_ids`` overrides, which is what these cases guard.
"""

import pytest

from space_map_data.constants.earth_sats.satellite_models import (
    SATELLITE_BUSES,
    bus_for_object,
)
from space_map_data.ingest.providers.objects.enrichment import (
    resolve_bus_slug,
    resolve_manufacturer_qids,
)

ROCKWELL = "Q1348664"
AIRBUS = "Q15529123"
MATRA = "Q6787769"

# (NORAD, GCAT Bus string, expected bus slug)
GENERATION_SPLITS = [
    (10684, "GPS", "gps-block-i"),  # NAVSTAR 1
    (22231, "GPS", "gps-block-iia"),  # NAVSTAR 28, same GCAT string
    (25933, "GPS IIR", "gps-block-iir"),  # NAVSTAR 46
    (28874, "Series 4000", "gps-block-iir-m"),  # NAVSTAR 57
    (13603, "Uragan", "uragan"),  # Kosmos-1413
    (26987, "Uragan", "uragan-m"),  # Kosmos-2382, the first GLONASS-M
    (37846, "GalileoSat", "galileo-iov"),  # GSAT0101
    (40128, "GalileoSat", "smartmeo"),  # GSAT0201, FOC on the same string
]

# (GCAT Bus string, expected bus slug) — no override involved
STRAIGHT = [
    ("ARROW", "arrow"),
    ("LS-400", "ls-400"),
    ("SN-100A", "sn-100a"),
    ("Starlink", "starlink-v1"),
    ("Starlink V2MD", "starlink-v2-mini-dtc"),
    ("SSL-1300", "ssl-1300"),
    ("FS-1300", "ssl-1300"),  # one of 16 GCAT strings for the same platform
]


class TestBusResolution:
    @pytest.mark.parametrize(("norad", "gcat_bus", "slug"), GENERATION_SPLITS)
    def test_override_wins_over_gcat(self, norad, gcat_bus, slug):
        bus = bus_for_object(norad, gcat_bus)
        assert bus is not None and bus.slug == slug

    @pytest.mark.parametrize(("gcat_bus", "slug"), STRAIGHT)
    def test_gcat_string_maps_to_bus(self, gcat_bus, slug):
        bus = bus_for_object(None, gcat_bus)
        assert bus is not None and bus.slug == slug

    @pytest.mark.parametrize("gcat_bus", ["Cubesat 3U", "STS OV", "", None])
    def test_unclaimed_string_gets_no_bus(self, gcat_bus):
        """A form-factor bucket or an unnamed platform is not a bus here."""
        assert bus_for_object(None, gcat_bus) is None
        assert resolve_bus_slug(None, gcat_bus) is None

    def test_no_gcat_string_claimed_twice(self):
        seen: dict[str, str] = {}
        for bus in SATELLITE_BUSES:
            for gcat in bus.gcat_buses:
                assert gcat not in seen, f"{gcat} on {seen.get(gcat)} and {bus.slug}"
                seen[gcat] = bus.slug


class TestManufacturerResolution:
    def test_org_code_resolves(self):
        """North American Aviation built Block I; GCAT files it as NAASB."""
        assert ROCKWELL in resolve_manufacturer_qids(None, ("NAASB",), ("NAASB",))

    def test_code_beats_ucode(self):
        """GCAT's UCode folds Airbus into Matra, its oldest name in the
        lineage; the as-filed code is what dates the build."""
        qids = resolve_manufacturer_qids(None, ("ADST",), ("MATT",))
        assert qids == [AIRBUS]
        assert resolve_manufacturer_qids(None, ("MATT",), ("MATT",)) == [MATRA]

    def test_joint_build_keeps_both(self):
        qids = resolve_manufacturer_qids(None, ("ADST", "MATT"), ("MATT", "MATT"))
        assert sorted(qids) == sorted({AIRBUS, MATRA})

    def test_unknown_code_is_not_an_error(self):
        assert resolve_manufacturer_qids(None, ("NOSUCHORG",), ("NOSUCHORG",)) == []
