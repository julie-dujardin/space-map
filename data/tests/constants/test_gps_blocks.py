"""GPS/NAVSTAR generations modeled as per-block satellite buses.

Block assignments are keyed off the USA/OPS designator (not the NAVSTAR
ordinal). Names are taken verbatim from CelesTrak SATCAT. Exercises the real
matching logic so the manufacturer follows the resolved bus.
"""

from space_map_data.constants.earth_sats.satellite_models import bus_for_satellite
from space_map_data.ingest.providers.objects.enrichment import (
    resolve_manufacturer_qids,
)

ROCKWELL = "Q1348664"
LOCKHEED = "Q7240"
BOEING = "Q66"

# (SATCAT OBJECT_NAME, expected bus slug, expected manufacturer QID)
CASES = [
    ("NAVSTAR 1 (OPS 5111)", "gps-block-i", ROCKWELL),
    ("NAVSTAR 11 (USA 10)", "gps-block-i", ROCKWELL),
    ("NAVSTAR 13 (USA 35)", "gps-block-ii", ROCKWELL),
    ("NAVSTAR 20 (USA 63)", "gps-block-ii", ROCKWELL),
    ("NAVSTAR 21 (USA 64)", "gps-block-iia", ROCKWELL),
    ("NAVSTAR 39 (USA 128)", "gps-block-iia", ROCKWELL),
    ("NAVSTAR 46 (USA 145)", "gps-block-iir", LOCKHEED),
    ("NAVSTAR 56 (USA 180)", "gps-block-iir", LOCKHEED),
    ("NAVSTAR 57 (USA 183)", "gps-block-iir-m", LOCKHEED),
    ("NAVSTAR 64 (USA 206)", "gps-block-iir-m", LOCKHEED),
    ("NAVSTAR 65 (USA 213)", "gps-block-iif", BOEING),
    ("NAVSTAR 76 (USA 266)", "gps-block-iif", BOEING),
    # GPS III rides the Lockheed a2100 bus.
    ("NAVSTAR 77 (USA 289)", "a2100", LOCKHEED),
]


class TestGpsBlockBuses:
    """Each NAVSTAR resolves to its block bus and that bus's prime."""

    def test_bus_and_manufacturer(self):
        for name, slug, mfr in CASES:
            bus = bus_for_satellite(name)
            assert bus is not None and bus.slug == slug, name
            assert mfr in resolve_manufacturer_qids("gps", name), name

    def test_iia_iir_designator_swap(self):
        """The IIA/IIR boundary follows USA-id, not launch order: NAVSTAR 43
        (USA-132, IIR-2) is Block IIR while the later-launched NAVSTAR 44
        (USA-135, IIA-19) is the last Block IIA."""
        iir = bus_for_satellite("NAVSTAR 43 (USA 132)")
        iia = bus_for_satellite("NAVSTAR 44 (USA 135)")
        assert iir is not None and iir.slug == "gps-block-iir"
        assert iia is not None and iia.slug == "gps-block-iia"

    def test_word_boundary_no_prefix_bleed(self):
        """A block entry must not bleed across NAVSTAR numbers (7 vs 70/76)."""
        iif = bus_for_satellite("NAVSTAR 70 (USA 251)")
        assert iif is not None and iif.slug == "gps-block-iif"
        # NAVSTAR 7 (a launch failure) isn't modeled; must not match NAVSTAR 70.
        assert bus_for_satellite("NAVSTAR 7") is None
