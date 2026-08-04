"""Citable sources behind the temperature constants, for the /credits page.

Keyed so each constant names the works it came from; the full per-value
provenance lives as comments next to the value. Keys are `name_year`, the
style the atmosphere and interior registries use, so a work cited by two
packages is recognisably the same key in both. Exported into credits.json,
where a work shared with another package is credited once.

NSSDCA has been offline since early 2025 — its entries link the Wayback
Machine's last pre-outage snapshots.
"""

from typing import NamedTuple


class TemperatureReference(NamedTuple):
    title: str
    url: str
    contribution: str


TEMPERATURE_SOURCES: dict[str, TemperatureReference] = {
    # --- survey sources ---------------------------------------------------
    "nssdca": TemperatureReference(
        "NSSDCA planetary fact sheets",
        "https://web.archive.org/web/20241228030846/https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
        "mean and diurnal surface temperatures for the planets, Moon and Ceres",
    ),
    "nasa_temperatures": TemperatureReference(
        "NASA Science — Temperatures Across Our Solar System",
        "https://science.nasa.gov/solar-system/temperatures-across-our-solar-system/",
        "the solar corona, and day/night extremes cross-checked against the fact sheets",
    ),
    "iau_2015_b3": TemperatureReference(
        "IAU 2015 Resolution B3",
        "https://www.iau.org/static/resolutions/IAU2015_English.pdf",
        "nominal solar effective temperature",
    ),
    # --- mission and laboratory measurements ------------------------------
    # Contributions read as additions to the atmosphere list's line for the
    # same work where there is one: the credits page merges them.
    "seiff_1985": TemperatureReference(
        "Seiff et al. 1985 — VIRA (Adv. Space Res. 5)",
        "https://doi.org/10.1016/0273-1177(85)90197-8",
        "Venus cloud-top reference temperature",
    ),
    "fulchignoni_2005": TemperatureReference(
        "Fulchignoni et al. 2005 (Nature 438)",
        "https://doi.org/10.1038/nature04314",
        "Titan's 93.65 K surface reading",
    ),
    "conrath_1989": TemperatureReference(
        "Conrath et al. 1989 (Science 246)",
        "https://doi.org/10.1126/science.246.4936.1454",
        "Triton's 38 K surface reading",
    ),
    "hinson_2017": TemperatureReference(
        "Hinson et al. 2017 (Icarus 290)",
        "https://doi.org/10.1016/j.icarus.2017.02.031",
        "Pluto near-surface temperatures (New Horizons REX occultation)",
    ),
    "earle_2017": TemperatureReference(
        "Earle et al. 2017 (Icarus 287)",
        "https://doi.org/10.1016/j.icarus.2016.09.036",
        "Pluto's albedo-driven surface temperature spread",
    ),
    "holler_2017": TemperatureReference(
        "Holler et al. 2017 (Icarus 284)",
        "https://doi.org/10.1016/j.icarus.2016.12.003",
        "Charon surface ice temperature (Keck/OSIRIS)",
    ),
    "tosi_2015": TemperatureReference(
        "Tosi et al. 2015 (LPSC XLVI, 1745)",
        "https://www.hou.usra.edu/meetings/lpsc2015/pdf/1745.pdf",
        "Ceres peak subsolar temperature (Dawn VIR)",
    ),
    "wmo_extremes": TemperatureReference(
        "WMO Archive of Weather and Climate Extremes",
        "https://wmo.asu.edu/content/world-meteorological-organization-global-weather-climate-extremes-archive",
        "Earth's record surface extremes",
    ),
    "us_standard_1976": TemperatureReference(
        "US Standard Atmosphere 1976",
        "https://www.ngdc.noaa.gov/stp/space-weather/online-publications/miscellaneous/us-standard-atmosphere-1976/us-standard-atmosphere_st76-1562_noaa.pdf",
        "the 288.15 K sea-level temperature",
    ),
}
