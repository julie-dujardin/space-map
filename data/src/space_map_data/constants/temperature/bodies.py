"""Measured temperatures per body, in kelvin.

Only bodies where a published measurement beats what Wikidata carries are
listed here; everything else keeps flowing from Wikidata, or falls back to the
computed equilibrium estimate. Values are kelvin because the frontend plots
them on a shared scale whose stellar segment is logarithmic.

Gas and ice giants have no surface, so their headline reading is the visible
cloud deck. The level is the same ~0.3 bar the atmosphere shell renders
against (constants/atmosphere/bodies.py) so the two blocks cannot disagree —
test_temperature_constants.py pins them together.
"""

from typing import NamedTuple


class Reading(NamedTuple):
    """One temperature at one place on a body.

    ``condition`` names what produces an extreme, where the bare min/max
    framing would mislead: Mercury's extremes are its night and day sides,
    Earth's are single weather records, and those are not the same claim.
    """

    kind: str  # "min" | "mean" | "max"
    kelvin: float
    condition: str | None = None  # "night" | "day" | "record"


class PartTemperature(NamedTuple):
    part: str  # "surface" | "cloud_top" | "photosphere" | "corona"
    readings: tuple[Reading, ...]
    sources: tuple[str, ...]  # keys into TEMPERATURE_SOURCES


TEMPERATURE_BODIES: dict[str, tuple[PartTemperature, ...]] = {
    # Sun. The photosphere is the IAU's nominal effective temperature, which
    # is the number every other stellar comparison is built on. The core is
    # not here — it is a model result attached to a boundary, and lives with
    # the boundary in constants/interior/bodies.py.
    "naif-10": (
        PartTemperature("photosphere", (Reading("mean", 5772.0),), ("iau2015b3",)),
        PartTemperature("corona", (Reading("mean", 2.0e6),), ("nasa_temperatures",)),
    ),
    # Mercury: no atmosphere to move heat, so the extremes are simply the lit
    # and unlit sides. NSSDCA gives 440 K mean and 590-725 K sunward; the
    # 700 K peak is the perihelion subsolar case, 100 K the equatorial night.
    "naif-199": (
        PartTemperature(
            "surface",
            (
                Reading("min", 100.0, "night"),
                Reading("mean", 440.0),
                Reading("max", 700.0, "day"),
            ),
            ("nssdca", "nasa_temperatures"),
        ),
    ),
    # Venus. The surface reading is the one people expect, but the cloud top
    # is what the map actually shows, so both ship. 245 K at ~60-65 km is the
    # VIRA tropopause the atmosphere shell also references.
    "naif-299": (
        PartTemperature("surface", (Reading("mean", 737.0),), ("nssdca",)),
        PartTemperature("cloud_top", (Reading("mean", 245.0),), ("seiff1985",)),
    ),
    # Earth. Min/max are single-station weather records (Vostok 1983-07-21,
    # Death Valley 1913-07-10), not a climatology — hence the record marker.
    "naif-399": (
        PartTemperature(
            "surface",
            (
                Reading("min", 183.95, "record"),
                Reading("mean", 288.15),
                Reading("max", 329.85, "record"),
            ),
            ("us_std_atm_1976", "wmo_extremes"),
        ),
    ),
    # Moon: equatorial diurnal range, plus the global mean the fact sheets
    # publish. Same airless day/night split as Mercury.
    "naif-301": (
        PartTemperature(
            "surface",
            (
                Reading("min", 95.0, "night"),
                Reading("mean", 253.0),
                Reading("max", 390.0, "day"),
            ),
            ("nssdca",),
        ),
    ),
    # Mars: diurnal range at the Viking 1 lander site; the mean is global.
    "naif-499": (
        PartTemperature(
            "surface",
            (
                Reading("min", 184.0, "night"),
                Reading("mean", 210.0),
                Reading("max", 242.0, "day"),
            ),
            ("nssdca",),
        ),
    ),
    # The four giants, at the ~0.3 bar visible deck. Jupiter had no
    # temperature at all before this; the others disagreed about which
    # pressure level they meant, which put Uranus and Saturn on incomparable
    # footings. Values mirror constants/atmosphere/bodies.py.
    "naif-599": (PartTemperature("cloud_top", (Reading("mean", 125.0),), ("nssdca",)),),
    "naif-699": (PartTemperature("cloud_top", (Reading("mean", 110.0),), ("nssdca",)),),
    "naif-799": (PartTemperature("cloud_top", (Reading("mean", 58.0),), ("nssdca",)),),
    "naif-899": (PartTemperature("cloud_top", (Reading("mean", 55.0),), ("nssdca",)),),
    # Titan, Huygens HASI at the landing site.
    "naif-606": (
        PartTemperature("surface", (Reading("mean", 93.65),), ("fulchignoni2005",)),
    ),
    # Triton, in N2-ice vapour equilibrium at the Voyager 2 epoch.
    "naif-801": (
        PartTemperature("surface", (Reading("mean", 38.0),), ("conrath1989",)),
    ),
    # Pluto. NSSDCA's "24-38 K" sits under its Atmosphere heading and is not a
    # surface figure — the apparent conflict with the ~33-55 K usually quoted
    # is two different quantities. The spread is albedo-driven (Earle et al.
    # put it near 20 K): N2 ice in Sputnik Planitia is the cold end, dark
    # tholin terrain the warm end. REX measured 38.9-57 K near the surface.
    "naif-999": (
        PartTemperature(
            "surface",
            (
                Reading("min", 37.0),
                Reading("mean", 44.0),
                Reading("max", 55.0),
            ),
            ("earle2017", "hinson2017"),
        ),
    ),
    # Charon: 45 +/- 14 K from Keck/OSIRIS, consistent with the 43.7 K ALMA
    # brightness temperature.
    "naif-901": (
        PartTemperature("surface", (Reading("mean", 45.0),), ("holler2017",)),
    ),
    # Ceres: fact-sheet mean, with Dawn's measured peak subsolar reading
    # (235 +/- 4 K at 2.77 AU) as the maximum.
    "naif-2000001": (
        PartTemperature(
            "surface",
            (Reading("mean", 168.0), Reading("max", 235.0, "day")),
            ("nssdca", "tosi2015"),
        ),
    ),
}
