"""Citable sources behind the atmosphere pipeline, for the /credits page.

One entry per work we actually take numbers from (constants or reference
checks), with a one-line "what we get" — the full per-value provenance lives
as comments next to each constant. Exported verbatim into credits.json.
"""

from typing import NamedTuple


class AtmosphereReference(NamedTuple):
    title: str
    url: str
    contribution: str


ATMOSPHERE_REFERENCES: tuple[AtmosphereReference, ...] = (
    # --- gas optics -------------------------------------------------------
    AtmosphereReference(
        "Peck & Khanna 1966 (JOSA 56)",
        "https://doi.org/10.1364/JOSA.56.001059",
        "N₂ refractivity dispersion",
    ),
    AtmosphereReference(
        "Zhang, Lu & Wang 2008 (Appl. Opt. 47)",
        "https://doi.org/10.1364/AO.47.003143",
        "O₂ refractivity dispersion",
    ),
    AtmosphereReference(
        "Bideau-Méhu et al. 1973 (Opt. Commun. 9)",
        "https://doi.org/10.1016/0030-4018(73)90289-7",
        "CO₂ refractivity dispersion",
    ),
    AtmosphereReference(
        "He et al. 2021 (ACP 21)",
        "https://doi.org/10.5194/acp-21-14927-2021",
        "CH₄ refractivity + measured Rayleigh cross sections used as checks",
    ),
    AtmosphereReference(
        "Peck & Huang 1977 (JOSA 67)",
        "https://doi.org/10.1364/JOSA.67.001550",
        "H₂ refractivity dispersion",
    ),
    AtmosphereReference(
        "Mansfield & Peck 1969 (JOSA 59)",
        "https://doi.org/10.1364/JOSA.59.000199",
        "He refractivity dispersion",
    ),
    AtmosphereReference(
        "Peck & Fisher 1964 (JOSA 54)",
        "https://doi.org/10.1364/JOSA.54.001362",
        "Ar refractivity dispersion",
    ),
    AtmosphereReference(
        "Bates 1984 (Planet. Space Sci. 32)",
        "https://doi.org/10.1016/0032-0633(84)90102-8",
        "King depolarisation factors for N₂ and O₂",
    ),
    AtmosphereReference(
        "Sneep & Ubachs 2005 (JQSRT 92)",
        "https://doi.org/10.1016/j.jqsrt.2004.07.025",
        "CO₂ King factor + measured Rayleigh cross sections used as checks",
    ),
    AtmosphereReference(
        "Dalgarno & Williams 1962 (ApJ 136)",
        "https://doi.org/10.1086/147428",
        "ab-initio H₂ Rayleigh cross sections used as checks",
    ),
    AtmosphereReference(
        "Bodhaine et al. 1999 (J. Atmos. Ocean. Tech. 16)",
        "https://journals.ametsoc.org/view/journals/atot/16/11/1520-0426_1999_016_1854_orodc_2_0_co_2.xml",
        "dry-air Rayleigh cross sections + molar mass used as checks",
    ),
    # --- reference atmospheres --------------------------------------------
    # NSSDCA has been offline since early 2025 — link the Wayback Machine's
    # last pre-outage snapshot of the fact-sheet index (2025+ snapshots only
    # capture the redirect to nasa.gov's outage notice).
    AtmosphereReference(
        "NSSDCA planetary fact sheets",
        "https://web.archive.org/web/20241228030846/https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
        "reference conditions, compositions and published scale heights",
    ),
    AtmosphereReference(
        "US Standard Atmosphere 1976",
        "https://www.ngdc.noaa.gov/stp/space-weather/online-publications/miscellaneous/us-standard-atmosphere-1976/us-standard-atmosphere_st76-1562_noaa.pdf",
        "Earth sea-level reference conditions",
    ),
    AtmosphereReference(
        "Seiff et al. 1985 — VIRA (Adv. Space Res. 5)",
        "https://doi.org/10.1016/0273-1177(85)90197-8",
        "Venus reference atmosphere",
    ),
    AtmosphereReference(
        "Fulchignoni et al. 2005 (Nature 438)",
        "https://doi.org/10.1038/nature04314",
        "Titan surface pressure and temperature (Huygens HASI)",
    ),
    AtmosphereReference(
        "Niemann et al. 2010 (JGR 115)",
        "https://doi.org/10.1029/2010JE003659",
        "Titan composition (Huygens GCMS)",
    ),
    AtmosphereReference(
        "Lindal et al. 1981 (JGR 86)",
        "https://doi.org/10.1029/JA086iA10p08721",
        "Jupiter thermal profile (Voyager radio occultation)",
    ),
    AtmosphereReference(
        "von Zahn, Hunten & Lehmacher 1998 (JGR 103)",
        "https://doi.org/10.1029/98JE00695",
        "Jupiter helium abundance (Galileo probe)",
    ),
    AtmosphereReference(
        "Tyler et al. 1982 (Science 215)",
        "https://doi.org/10.1126/science.215.4532.553",
        "Saturn thermal profile (Voyager 2)",
    ),
    AtmosphereReference(
        "Conrath & Gautier 2000 (Icarus 144)",
        "https://doi.org/10.1006/icar.1999.6265",
        "Saturn helium abundance",
    ),
    AtmosphereReference(
        "Lindal et al. 1987 (JGR 92)",
        "https://doi.org/10.1029/JA092iA13p14987",
        "Uranus profile and 1-bar radius (Voyager 2)",
    ),
    AtmosphereReference(
        "Conrath et al. 1987 (JGR 92)",
        "https://doi.org/10.1029/JA092iA13p15003",
        "Uranus helium abundance",
    ),
    AtmosphereReference(
        "Lindal 1992 (AJ 103)",
        "https://doi.org/10.1086/116119",
        "Neptune profile and 1-bar radius (Voyager 2)",
    ),
    AtmosphereReference(
        "Conrath et al. 1991 (JGR 96)",
        "https://doi.org/10.1029/91JA01703",
        "Neptune helium abundance",
    ),
    AtmosphereReference(
        "Karkoschka & Tomasko 2009 (Icarus 202)",
        "https://doi.org/10.1016/j.icarus.2009.02.010",
        "Uranus methane abundance",
    ),
    AtmosphereReference(
        "Hinson et al. 2017 (Icarus 290)",
        "https://doi.org/10.1016/j.icarus.2017.02.031",
        "Pluto surface pressure (New Horizons REX)",
    ),
    AtmosphereReference(
        "Meza et al. 2019 (A&A 625)",
        "https://arxiv.org/abs/1903.02315",
        "Pluto pressure evolution (epoch context)",
    ),
    AtmosphereReference(
        "Tyler et al. 1989 (Science 246)",
        "https://doi.org/10.1126/science.246.4936.1466",
        "Triton surface pressure + Neptune occultation (Voyager 2)",
    ),
    AtmosphereReference(
        "Conrath et al. 1989 (Science 246)",
        "https://doi.org/10.1126/science.246.4936.1454",
        "Triton surface temperature (Voyager IRIS)",
    ),
    AtmosphereReference(
        "Marques Oliveira et al. 2022 (A&A 659)",
        "https://arxiv.org/abs/2201.10450",
        "Triton pressure stability (2017 occultation)",
    ),
    # --- aerosols ---------------------------------------------------------
    AtmosphereReference(
        "Hess, Koepke & Schult 1998 — OPAC (BAMS 79)",
        "https://journals.ametsoc.org/view/journals/bams/79/5/1520-0477_1998_079_0831_opoaac_2_0_co_2.xml",
        "Earth aerosol mixtures (extinction, albedo, Ångström slope)",
    ),
    AtmosphereReference(
        "Shettle & Fenn 1979 (AFGL-TR-79-0214)",
        "https://web.gps.caltech.edu/~vijay/Papers/Aerosol/SF79-Aerosol-Models-part1of4.PDF",
        "aerosol refractive indices",
    ),
    AtmosphereReference(
        "Gorshelev et al. 2014 + Serdyuchenko dataset (AMT 7)",
        "https://doi.org/10.5281/zenodo.5793206",
        "ozone Chappuis-band cross sections",
    ),
    AtmosphereReference(
        "Wolff et al. 2009 (JGR 114)",
        "https://doi.org/10.1029/2009JE003350",
        "Mars dust single-scattering properties",
    ),
    AtmosphereReference(
        "Tomasko et al. 1999 (JGR 104)",
        "https://doi.org/10.1029/1998JE900016",
        "Mars dust particle size (Pathfinder)",
    ),
    AtmosphereReference(
        "Chen-Chen et al. 2019 (Icarus 330)",
        "https://arxiv.org/abs/1905.01074",
        "Mars dust phase-function fit (MSL cameras)",
    ),
    AtmosphereReference(
        "Conrath 1975 (Icarus 24)",
        "https://doi.org/10.1016/0019-1035(75)90156-6",
        "Mars dust vertical profile parameterisation",
    ),
    AtmosphereReference(
        "Hansen & Hovenier 1974 (J. Atmos. Sci. 31)",
        "https://journals.ametsoc.org/view/journals/atsc/31/4/1520-0469_1974_031_1137_iotpov_2_0_co_2.xml",
        "Venus cloud droplet size and refractive index",
    ),
    AtmosphereReference(
        "Palmer & Williams 1975 (Appl. Opt. 14)",
        "https://opg.optica.org/ao/abstract.cfm?uri=ao-14-1-208",
        "H₂SO₄ refractive index dispersion",
    ),
    AtmosphereReference(
        "Knollenberg & Hunten 1980 (JGR 85)",
        "https://doi.org/10.1029/JA085iA13p08039",
        "Venus cloud structure (Pioneer Venus LCPS)",
    ),
    AtmosphereReference(
        "Titov et al. 2018 (Space Sci. Rev. 214)",
        "https://link.springer.com/article/10.1007/s11214-018-0552-z",
        "Venus cloud/haze layer table + upper-haze scale height",
    ),
    AtmosphereReference(
        "Tomasko et al. 2008 (Planet. Space Sci. 56)",
        "https://doi.org/10.1016/j.pss.2007.11.019",
        "Titan haze model (Huygens DISR)",
    ),
    AtmosphereReference(
        "Doose et al. 2016 (Icarus 270)",
        "https://doi.org/10.1016/j.icarus.2015.09.039",
        "Titan haze vertical profile revision",
    ),
    AtmosphereReference(
        "Bazzon et al. 2014 (A&A 572)",
        "https://arxiv.org/abs/1409.3421",
        "Titan haze extinction slopes and albedo",
    ),
    AtmosphereReference(
        "Khare et al. 1984 (Icarus 60)",
        "https://doi.org/10.1016/0019-1035(84)90142-8",
        "tholin optical constants (Titan, Pluto)",
    ),
    AtmosphereReference(
        "Lavvas, Yelle & Vuitton 2009 (Icarus 201)",
        "https://www.sciencedirect.com/science/article/abs/pii/S0019103509000086",
        "Titan detached haze layer",
    ),
    AtmosphereReference(
        "West et al. 2011 (GRL 38)",
        "https://doi.org/10.1029/2011GL046843",
        "Titan detached haze seasonal descent",
    ),
    AtmosphereReference(
        "Zhang et al. 2013 (Icarus 226)",
        "https://doi.org/10.1016/j.icarus.2013.05.020",
        "Jupiter stratospheric haze particles",
    ),
    AtmosphereReference(
        "Pérez-Hoyos et al. 2005 (Icarus 176)",
        "https://doi.org/10.1016/j.icarus.2005.01.014",
        "Saturn haze structure",
    ),
    AtmosphereReference(
        "Irwin et al. 2022 (JGR Planets 127)",
        "https://doi.org/10.1029/2022JE007189",
        "Uranus/Neptune aerosol layer structure",
    ),
    AtmosphereReference(
        "Gladstone et al. 2016 (Science 351)",
        "https://doi.org/10.1126/science.aad8866",
        "Pluto atmosphere and haze (New Horizons)",
    ),
    AtmosphereReference(
        "Cheng et al. 2017 (Icarus 290)",
        "https://arxiv.org/abs/1702.07771",
        "Pluto haze microphysics and optical depth",
    ),
    AtmosphereReference(
        "Rages & Pollack 1992 (Icarus 99)",
        "https://ntrs.nasa.gov/citations/19930030901",
        "Triton haze particle size, scale height and optical depth",
    ),
    AtmosphereReference(
        "Thomason et al. 2018 — GloSSAC (ESSD 10)",
        "https://doi.org/10.5194/essd-10-469-2018",
        "Earth stratospheric background aerosol",
    ),
    # --- photometry + render model ----------------------------------------
    AtmosphereReference(
        "Hestroffer & Magnan 1998 (A&A 333)",
        "https://ui.adsabs.harvard.edu/abs/1998A%26A...333..338H/abstract",
        "solar limb-darkening law",
    ),
    AtmosphereReference(
        "Stephens et al. 2015 (Rev. Geophys. 53)",
        "https://doi.org/10.1002/2014RG000449",
        "Earth albedo split (surface vs clouds)",
    ),
    AtmosphereReference(
        "Nelson et al. 1990 (GRL 17)",
        "https://ui.adsabs.harvard.edu/abs/1990GeoRL..17.1761N/abstract",
        "Triton spectral albedos",
    ),
    AtmosphereReference(
        "Schröder & Keller 2008 (Planet. Space Sci. 56)",
        "https://www.sciencedirect.com/science/article/abs/pii/S0032063307003583",
        "Titan surface reflectance",
    ),
    AtmosphereReference(
        "Bruneton & Neyret 2008 (EGSR)",
        "https://inria.hal.science/inria-00288758/document",
        "reference scattering model (render wavelengths, ozone tent)",
    ),
    AtmosphereReference(
        "Maxime Heckel — On Rendering the Sky, Sunsets, and Planets",
        "https://blog.maximeheckel.com/posts/on-rendering-the-sky-sunsets-and-planets/",
        "the real-time shell shader recipe this renderer follows",
    ),
)
