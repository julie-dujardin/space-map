"""Citable sources behind the temperature constants, for the /credits page.

Keyed so each constant names the works it came from; the full per-value
provenance lives as comments next to the value. Exported into credits.json.

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
        "day/night extremes cross-checked against the fact sheets",
    ),
    "iau2015b3": TemperatureReference(
        "IAU 2015 Resolution B3",
        "https://www.iau.org/static/resolutions/IAU2015_English.pdf",
        "nominal solar effective temperature",
    ),
    # --- mission and laboratory measurements ------------------------------
    "seiff1985": TemperatureReference(
        "Seiff et al. 1985 — VIRA (Adv. Space Res. 5)",
        "https://doi.org/10.1016/0273-1177(85)90197-8",
        "Venus cloud-top reference temperature",
    ),
    "fulchignoni2005": TemperatureReference(
        "Fulchignoni et al. 2005 (Nature 438)",
        "https://doi.org/10.1038/nature04314",
        "Titan surface temperature (Huygens HASI)",
    ),
    "conrath1989": TemperatureReference(
        "Conrath et al. 1989 (Science 246)",
        "https://doi.org/10.1126/science.246.4936.1454",
        "Triton surface temperature (Voyager 2 IRIS)",
    ),
    "hinson2017": TemperatureReference(
        "Hinson et al. 2017 (Icarus 290)",
        "https://doi.org/10.1016/j.icarus.2017.02.031",
        "Pluto near-surface temperatures (New Horizons REX occultation)",
    ),
    "earle2017": TemperatureReference(
        "Earle et al. 2017 (Icarus 287)",
        "https://doi.org/10.1016/j.icarus.2016.09.036",
        "Pluto's albedo-driven surface temperature spread",
    ),
    "holler2017": TemperatureReference(
        "Holler et al. 2017 (Icarus 284)",
        "https://doi.org/10.1016/j.icarus.2016.12.003",
        "Charon surface ice temperature (Keck/OSIRIS)",
    ),
    "tosi2015": TemperatureReference(
        "Tosi et al. 2015 (LPSC XLVI, 1745)",
        "https://www.hou.usra.edu/meetings/lpsc2015/pdf/1745.pdf",
        "Ceres peak subsolar temperature (Dawn VIR)",
    ),
    "wmo_extremes": TemperatureReference(
        "WMO Archive of Weather and Climate Extremes",
        "https://wmo.asu.edu/content/world-meteorological-organization-global-weather-climate-extremes-archive",
        "Earth's record surface extremes",
    ),
    "us_std_atm_1976": TemperatureReference(
        "US Standard Atmosphere 1976",
        "https://www.ngdc.noaa.gov/stp/space-weather/online-publications/miscellaneous/us-standard-atmosphere-1976/us-standard-atmosphere_st76-1562_noaa.pdf",
        "Earth sea-level reference temperature",
    ),
    # --- interior models (cores) ------------------------------------------
    # Cores are model output, so these are reviews and bracketing studies
    # rather than measurements — see cores.py.
    "guillot2005": TemperatureReference(
        "Guillot 2005 (Annu. Rev. Earth Planet. Sci. 33)",
        "https://doi.org/10.1146/annurev.earth.32.101802.120325",
        "giant-planet interior adiabats",
    ),
    "helled2024": TemperatureReference(
        "Helled 2024 (AGU Advances 5)",
        "https://doi.org/10.1029/2024AV001171",
        "post-Juno fuzzy-core interiors of Jupiter and Saturn",
    ),
    "scheibe2019": TemperatureReference(
        "Scheibe, Nettelmann & Redmer 2019 (A&A 632)",
        "https://doi.org/10.1051/0004-6361/201936378",
        "adiabatic thermal evolution models of Uranus and Neptune",
    ),
    "anzellini2013": TemperatureReference(
        "Anzellini et al. 2013 (Science 340)",
        "https://doi.org/10.1126/science.1233514",
        "Earth inner-core boundary temperature from iron melting",
    ),
    "stahler2021": TemperatureReference(
        "Stähler et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abi7730",
        "Mars core size and state (InSight seismology)",
    ),
    "hauck2013": TemperatureReference(
        "Hauck et al. 2013 (JGR Planets 118)",
        "https://doi.org/10.1002/jgre.20091",
        "Mercury core-mantle boundary temperature range",
    ),
    "weber2011": TemperatureReference(
        "Weber et al. 2011 (Science 331)",
        "https://doi.org/10.1126/science.1199375",
        "lunar core detection from Apollo seismology",
    ),
    "dumoulin2017": TemperatureReference(
        "Dumoulin et al. 2017 (JGR Planets 122)",
        "https://doi.org/10.1002/2016JE005249",
        "Venus interior structure from tidal constraints",
    ),
    "bahcall2005": TemperatureReference(
        "Bahcall, Serenelli & Basu 2005 (ApJ 621)",
        "https://doi.org/10.1086/428929",
        "standard solar model central conditions",
    ),
}
