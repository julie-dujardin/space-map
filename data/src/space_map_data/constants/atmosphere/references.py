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


# Sources behind the per-body atmospheric facts in `facts.py` and the vertical
# layers in `structure.py`, keyed so each value can cite one. One registry for
# both: a body's panel credits its conditions and its cross-section together,
# and several works back numbers in each. These also ship per body in the
# object bundles, so the
# panel can credit exactly the works its numbers came from — hence the split
# from the render literature above, which is credited globally.
#
# NSSDCA fact sheets link Internet Archive snapshots: the site has been offline
# since early 2025, and the snapshot is what was actually read.
ATMOSPHERE_FACT_SOURCES: dict[str, AtmosphereReference] = {
    "nssdc_sun": AtmosphereReference(
        "NASA Sun Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240608182027/https://nssdc.gsfc.nasa.gov/planetary/factsheet/sunfact.html",
        "photospheric pressure and temperature",
    ),
    "stanford_solar": AtmosphereReference(
        "The Sun's Vital Statistics (Stanford Solar Center)",
        "https://web.archive.org/web/20240129234549/http://solar-center.stanford.edu/vitalstats.html",
        "solar photospheric abundances by mass",
    ),
    "nssdc_mercury": AtmosphereReference(
        "NASA Mercury Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20241130091522/https://nssdc.gsfc.nasa.gov/planetary/factsheet/mercuryfact.html",
        "Mercury exospheric pressure and column abundances",
    ),
    "wiki_mercury_atm": AtmosphereReference(
        "Atmosphere of Mercury (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Mercury",
        "Mercury helium and calcium columns",
    ),
    "nssdc_venus": AtmosphereReference(
        "NASA Venus Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20241130090017/https://nssdc.gsfc.nasa.gov/planetary/factsheet/venusfact.html",
        "Venus surface pressure and composition",
    ),
    "nssdc_earth": AtmosphereReference(
        "NASA Earth Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20241201104126/https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html",
        "Earth sea-level pressure and dry-air composition",
    ),
    "nssdc_mars": AtmosphereReference(
        "NASA Mars Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20250603204342/https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html",
        "Mars surface pressure and composition",
    ),
    "webster_2018": AtmosphereReference(
        "Webster et al. 2018 (Science 360)",
        "https://doi.org/10.1126/science.aaq0131",
        "Mars background methane abundance",
    ),
    "nssdc_jupiter": AtmosphereReference(
        "NASA Jupiter Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240528013855/https://nssdc.gsfc.nasa.gov/planetary/factsheet/jupiterfact.html",
        "Jupiter reference levels and minor species",
    ),
    "von_zahn_1998": AtmosphereReference(
        "von Zahn et al. 1998 (JGR 103)",
        "https://doi.org/10.1029/98JE00695",
        "Jupiter helium abundance (Galileo probe)",
    ),
    "nssdc_saturn": AtmosphereReference(
        "NASA Saturn Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240605165339/https://nssdc.gsfc.nasa.gov/planetary/factsheet/saturnfact.html",
        "Saturn reference levels and minor species",
    ),
    "conrath_gautier_2000": AtmosphereReference(
        "Conrath & Gautier 2000 (Icarus 144)",
        "https://doi.org/10.1006/icar.1999.6265",
        "Saturn helium abundance (Voyager reanalysis)",
    ),
    "nssdc_uranus": AtmosphereReference(
        "NASA Uranus Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240602195651/https://nssdc.gsfc.nasa.gov/planetary/factsheet/uranusfact.html",
        "Uranus reference levels and composition",
    ),
    "nssdc_neptune": AtmosphereReference(
        "NASA Neptune Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240530201330/https://nssdc.gsfc.nasa.gov/planetary/factsheet/neptunefact.html",
        "Neptune reference levels and composition",
    ),
    "nssdc_moon": AtmosphereReference(
        "NASA Moon Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240601000000/https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html",
        "lunar nighttime exospheric densities and pressure",
    ),
    "wiki_moon_atm": AtmosphereReference(
        "Atmosphere of the Moon (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_the_Moon",
        "lunar daytime sodium and potassium densities",
    ),
    "kuppers_2014": AtmosphereReference(
        "Küppers et al. 2014 (Nature 505)",
        "https://doi.org/10.1038/nature12918",
        "Ceres water-vapour detection",
    ),
    "nssdc_pluto": AtmosphereReference(
        "NASA Pluto Fact Sheet (NSSDCA)",
        "https://web.archive.org/web/20240601000000/https://nssdc.gsfc.nasa.gov/planetary/factsheet/plutofact.html",
        "Pluto atmospheric nitrogen fraction",
    ),
    "hinson_2017": AtmosphereReference(
        "Hinson et al. 2017 (Icarus 290)",
        "https://doi.org/10.1016/j.icarus.2017.02.031",
        "Pluto surface pressure (New Horizons radio occultation)",
    ),
    "young_2018": AtmosphereReference(
        "Young et al. 2018 (Icarus 300)",
        "https://doi.org/10.1016/j.icarus.2017.09.006",
        "Pluto methane abundance (New Horizons UV occultation)",
    ),
    "wiki_pluto_atm": AtmosphereReference(
        "Atmosphere of Pluto (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Pluto",
        "Pluto carbon monoxide and hydrocarbon fractions",
    ),
    "wiki_triton_atm": AtmosphereReference(
        "Atmosphere of Triton (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Triton",
        "Triton atmospheric nitrogen fraction",
    ),
    "lellouch_2010": AtmosphereReference(
        "Lellouch et al. 2010 (A&A 512)",
        "https://doi.org/10.1051/0004-6361/201014339",
        "Triton carbon monoxide and methane abundances",
    ),
    "sicardy_2024": AtmosphereReference(
        "Sicardy et al. 2024 (A&A 682)",
        "https://doi.org/10.1051/0004-6361/202348756",
        "Triton surface pressure through 2022",
    ),
    "sicardy_2011": AtmosphereReference(
        "Sicardy et al. 2011 (Nature 478)",
        "https://doi.org/10.1038/nature10550",
        "Eris atmospheric upper limit",
    ),
    "ortiz_2012": AtmosphereReference(
        "Ortiz et al. 2012 (Nature 491)",
        "https://doi.org/10.1038/nature11597",
        "Makemake atmospheric upper limit",
    ),
    "ortiz_2017": AtmosphereReference(
        "Ortiz et al. 2017 (Nature 550)",
        "https://doi.org/10.1038/nature24051",
        "Haumea atmospheric upper limit",
    ),
    "huygens_hasi": AtmosphereReference(
        "Fulchignoni et al. 2005 (Nature 438)",
        "https://doi.org/10.1038/nature04314",
        "Titan surface pressure and temperature",
    ),
    "niemann_2010": AtmosphereReference(
        "Niemann et al. 2010 (JGR 115)",
        "https://doi.org/10.1029/2010JE003659",
        "Titan lower-atmosphere composition",
    ),
    "dekok_2007": AtmosphereReference(
        "de Kok et al. 2007 (Icarus 186)",
        "https://doi.org/10.1016/j.icarus.2006.09.016",
        "Titan carbon monoxide abundance",
    ),
    "waite_2017": AtmosphereReference(
        "Waite et al. 2017 (Science 356)",
        "https://doi.org/10.1126/science.aai8703",
        "Enceladus plume composition",
    ),
    "hansen_2020": AtmosphereReference(
        "Hansen et al. 2020 (Icarus 344)",
        "https://doi.org/10.1016/j.icarus.2019.113461",
        "Enceladus plume structure and source rate",
    ),
    "teolis_2010": AtmosphereReference(
        "Teolis et al. 2010 (Science 330)",
        "https://doi.org/10.1126/science.1198366",
        "Rhea oxygen-carbon dioxide exosphere",
    ),
    "teolis_waite_2016": AtmosphereReference(
        "Teolis & Waite 2016 (Icarus 272)",
        "https://doi.org/10.1016/j.icarus.2016.02.031",
        "Dione and Rhea exospheric densities",
    ),
    "tokar_2012": AtmosphereReference(
        "Tokar et al. 2012 (GRL 39)",
        "https://doi.org/10.1029/2011GL050452",
        "Dione exospheric oxygen detection",
    ),
    "wiki_io": AtmosphereReference(
        "Io (moon) (Wikipedia)",
        "https://en.wikipedia.org/wiki/Io_(moon)",
        "Io dayside surface pressure",
    ),
    "wiki_io_atm": AtmosphereReference(
        "Atmosphere of Io (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Io",
        "Io sulphur dioxide and sulphur monoxide fractions",
    ),
    "mcgrath_2009": AtmosphereReference(
        "McGrath et al. 2009 (Europa, University of Arizona Press)",
        "https://ui.adsabs.harvard.edu/abs/2009euro.book..485M/abstract",
        "Europa equivalent surface pressure",
    ),
    "cervantes_2022": AtmosphereReference(
        "Cervantes & Saur 2022 (JGR Space Physics 127)",
        "https://doi.org/10.1029/2022JA030472",
        "Europa subsolar O₂ and H₂O columns",
    ),
    "roth_2021_europa": AtmosphereReference(
        "Roth 2021 (GRL 48)",
        "https://doi.org/10.1029/2021GL094289",
        "Europa atomic oxygen column",
    ),
    "hall_1998": AtmosphereReference(
        "Hall et al. 1998 (ApJ 499)",
        "https://doi.org/10.1086/305604",
        "Ganymede O₂ column and exospheric pressure",
    ),
    "roth_2021_ganymede": AtmosphereReference(
        "Roth et al. 2021 (Nature Astronomy 5)",
        "https://doi.org/10.1038/s41550-021-01426-9",
        "Ganymede sublimated water column",
    ),
    "dekleer_2023": AtmosphereReference(
        "de Kleer et al. 2023 (Planet. Sci. J. 4)",
        "https://doi.org/10.3847/PSJ/acb53c",
        "Ganymede and Callisto oxygen columns from aurora",
    ),
    "carlson_1999": AtmosphereReference(
        "Carlson 1999 (Science 283)",
        "https://doi.org/10.1126/science.283.5403.820",
        "Callisto carbon dioxide atmosphere and pressure",
    ),
    "cartwright_2024": AtmosphereReference(
        "Cartwright et al. 2024 (Planet. Sci. J. 5)",
        "https://doi.org/10.3847/PSJ/ad23e6",
        "Callisto carbon dioxide column",
    ),
    # --- vertical structure (structure.py) --------------------------------
    "val_c_1981": AtmosphereReference(
        "Vernazza, Avrett & Loeser 1981 (ApJS 45)",
        "https://doi.org/10.1086/190731",
        "solar photosphere height scale and temperature minimum (VAL-C)",
    ),
    "wiki_solar_atm": AtmosphereReference(
        "Sun (Wikipedia)",
        "https://en.wikipedia.org/wiki/Sun#Atmosphere",
        "solar chromosphere, transition region and corona boundaries",
    ),
    "seiff_1985": AtmosphereReference(
        "Seiff et al. 1985 — VIRA (Adv. Space Res. 5)",
        "https://doi.org/10.1016/0273-1177(85)90197-8",
        "Venus troposphere depth and tropopause conditions",
    ),
    "limaye_2018": AtmosphereReference(
        "Limaye et al. 2018 (Space Sci. Rev. 214)",
        "https://doi.org/10.1007/s11214-018-0525-2",
        "Venus mesosphere, thermosphere and exosphere boundaries",
    ),
    "niemann_1980_venus": AtmosphereReference(
        "Niemann et al. 1980 (JGR 85)",
        "https://doi.org/10.1029/JA085iA13p07817",
        "Venus homopause and thermospheric species separation (Pioneer Venus ONMS)",
    ),
    "us_standard_1976": AtmosphereReference(
        "US Standard Atmosphere 1976 (NOAA/NASA/USAF)",
        "https://www.ngdc.noaa.gov/stp/space-weather/online-publications/miscellaneous/us-standard-atmosphere-1976/us-standard-atmosphere_st76-1562_noaa.pdf",
        "Earth tropopause, stratopause and mesopause breakpoints",
    ),
    "wiki_earth_atm": AtmosphereReference(
        "Atmosphere of Earth (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Earth",
        "Earth thermosphere, exosphere and turbopause altitudes",
    ),
    "haberle_2015": AtmosphereReference(
        "Haberle 2015 (Encyclopedia of Atmospheric Sciences, 2nd ed.)",
        "https://doi.org/10.1016/B978-0-12-382225-3.00312-1",
        "Mars layer boundaries and mesopause pressure band",
    ),
    "millour_2015": AtmosphereReference(
        "Millour et al. 2015 — Mars Climate Database v5.3 (EPSC)",
        "https://ui.adsabs.harvard.edu/abs/2015EPSC...10..438M/abstract",
        "Mars pressure at the layer boundaries",
    ),
    "mahaffy_2015": AtmosphereReference(
        "Mahaffy et al. 2015 (GRL 42)",
        "https://doi.org/10.1002/2015GL065329",
        "Mars homopause altitude (MAVEN NGIMS)",
    ),
    "seiff_1998": AtmosphereReference(
        "Seiff et al. 1998 (JGR 103)",
        "https://doi.org/10.1029/98JE01766",
        "Jupiter tropopause conditions (Galileo probe ASI)",
    ),
    "yelle_miller_2004": AtmosphereReference(
        "Yelle & Miller 2004 (Jupiter, Cambridge University Press)",
        "https://ui.adsabs.harvard.edu/abs/2004jpsm.book..185Y/abstract",
        "Jupiter thermosphere and homopause",
    ),
    "wiki_jupiter_atm": AtmosphereReference(
        "Atmosphere of Jupiter (Wikipedia)",
        "https://en.wikipedia.org/wiki/Atmosphere_of_Jupiter",
        "Jupiter stratosphere and exosphere extent",
    ),
    "fletcher_2018": AtmosphereReference(
        "Fletcher et al. 2018 (Saturn in the 21st Century, Cambridge)",
        "https://arxiv.org/abs/1510.05690",
        "Saturn tropopause and middle-atmosphere pressure range",
    ),
    "koskinen_2013": AtmosphereReference(
        "Koskinen et al. 2013 (Icarus 226)",
        "https://doi.org/10.1016/j.icarus.2013.07.037",
        "Saturn exobase altitude and temperature (Cassini/UVIS)",
    ),
    "lunine_1993": AtmosphereReference(
        "Lunine 1993 (ARA&A 31)",
        "https://doi.org/10.1146/annurev.aa.31.090193.001245",
        "Uranus troposphere and stratosphere extent",
    ),
    "herbert_sandel_1999": AtmosphereReference(
        "Herbert & Sandel 1999 (Planet. Space Sci. 47)",
        "https://doi.org/10.1016/S0032-0633(98)00142-1",
        "Uranus thermosphere temperature and exobase",
    ),
    "wiki_neptune": AtmosphereReference(
        "Neptune (Wikipedia)",
        "https://en.wikipedia.org/wiki/Neptune#Atmosphere",
        "Neptune layer boundaries and thermosphere temperature",
    ),
    "robinson_catling_2014": AtmosphereReference(
        "Robinson & Catling 2014 (Nature Geoscience 7)",
        "https://doi.org/10.1038/ngeo2020",
        "the common 0.1 bar tropopause of thick atmospheres",
    ),
    "gladstone_2016": AtmosphereReference(
        "Gladstone et al. 2016 (Science 351)",
        "https://doi.org/10.1126/science.aad8866",
        "Pluto thermal structure, haze layering and exobase (New Horizons)",
    ),
    "strobel_zhu_2017": AtmosphereReference(
        "Strobel & Zhu 2017 (Icarus 291)",
        "https://doi.org/10.1016/j.icarus.2017.03.013",
        "Triton thermospheric temperature structure",
    ),
    "wiki_thermopause": AtmosphereReference(
        "Thermopause (Wikipedia)",
        "https://en.wikipedia.org/wiki/Thermopause",
        "Earth thermopause altitude and temperature over the solar cycle",
    ),
    "lindal_1985": AtmosphereReference(
        "Lindal, Sweetnam & Eshleman 1985 (AJ 90)",
        "https://doi.org/10.1086/113820",
        "Saturn tropopause height, pressure and temperature (Voyager 2)",
    ),
    "lindal_1992": AtmosphereReference(
        "Lindal 1992 (AJ 103)",
        "https://doi.org/10.1086/116119",
        "Neptune tropopause height, pressure and temperature (Voyager 2)",
    ),
    "strobel_2018": AtmosphereReference(
        "Strobel, Koskinen & Müller-Wodarg 2018 "
        "(Saturn in the 21st Century, Cambridge)",
        "https://doi.org/10.1017/9781316227220.009",
        "Saturn homopause level and thermosphere base temperature",
    ),
    "moses_2018": AtmosphereReference(
        "Moses et al. 2018 (Icarus 307)",
        "https://doi.org/10.1016/j.icarus.2018.02.004",
        "Uranus and Neptune methane homopause levels",
    ),
    "broadfoot_1989": AtmosphereReference(
        "Broadfoot et al. 1989 (Science 246)",
        "https://doi.org/10.1126/science.246.4936.1459",
        "Neptune thermospheric temperature (Voyager 2 UVS occultation)",
    ),
}
