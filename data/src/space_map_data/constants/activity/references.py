"""Citable sources behind the activity facts, for the /credits page.

One entry per work a number actually comes from, keyed by the `source` strings
used in `volcanism.py`, `tidal.py` and `magnetism.py`. Per-value provenance
stays as comments next to each constant; this is what gets exported.

`contribution` is the credits page's sentence; `note` is the two or three words
the object panel's credit line has room for, in the style of its provider roles
("sizes, albedos & spectral types").

Two entries are databases rather than papers — the Smithsonian's volcano
catalogue and the IGRF — and both are cited at a version, because both restate
their numbers on a schedule.
"""

from typing import NamedTuple


class ActivityReference(NamedTuple):
    title: str
    url: str
    contribution: str
    note: str = ""


ACTIVITY_SOURCES: dict[str, ActivityReference] = {
    # --- volcanism and tectonics -------------------------------------------
    "gvp_votw": ActivityReference(
        "Global Volcanism Program, Volcanoes of the World v5.3.4 (Smithsonian Institution)",
        "https://doi.org/10.5479/si.GVP.VOTW5-2025.5.3",
        "Earth's Holocene volcano catalogue and eruption record — counts of "
        "known, continuing and annually active volcanoes",
        "Earth volcano counts",
    ),
    "davies_2010": ActivityReference(
        "Davies & Davies 2010 (Solid Earth 1)",
        "https://doi.org/10.5194/se-1-5-2010",
        "Earth's global surface heat flux from 38,347 heat-flow measurements",
        "Earth heat flow",
    ),
    "bird_2003": ActivityReference(
        "Bird 2003 (Geochemistry, Geophysics, Geosystems 4)",
        "https://doi.org/10.1029/2001GC000252",
        "PB2002 plate model — the count of Earth's plates and the global rate "
        "of lithosphere production",
        "Earth plate model",
    ),
    "herrick_2023": ActivityReference(
        "Herrick & Hensley 2023 (Science 379)",
        "https://doi.org/10.1126/science.abm7735",
        "A volcanic vent at Maat Mons that grew from 2.2 to 4.0 km² between two "
        "Magellan passes — the first direct sign of ongoing volcanism on Venus",
        "Venus vent change",
    ),
    "sulcanese_2024": ActivityReference(
        "Sulcanese, Mitri & Mastrogiuseppe 2024 (Nature Astronomy 8)",
        "https://doi.org/10.1038/s41550-024-02272-1",
        "New lava flows at Sif Mons and Niobe Planitia identified from Magellan "
        "radar backscatter changes",
        "Venus lava flows",
    ),
    "byrne_2022": ActivityReference(
        "Byrne & Krishnamoorthy 2022 (JGR Planets 127)",
        "https://doi.org/10.1029/2021JE007040",
        "Expected frequency of volcanic eruptions on Venus, scaled from Earth's "
        "1980-2021 eruption record; Venus surface crater-retention age",
        "Venus eruption rate",
    ),
    "gillmann_2024": ActivityReference(
        "Gillmann et al. 2024 (Treatise on Geochemistry, 3rd ed.)",
        "https://doi.org/10.1016/B978-0-323-99762-1.00110-2",
        "Review of Venus — global volcanic production rate, the spread of "
        "crater-derived surface ages, and the unsettled state of its tectonic "
        "regime",
        "Venus review",
    ),
    "gulcher_2020": ActivityReference(
        "Gülcher et al. 2020 (Nature Geoscience 13)",
        "https://doi.org/10.1038/s41561-020-0606-1",
        "Coronae as plume-lithosphere interactions, and evidence for ongoing "
        "plume activity beneath Venus",
        "Venus coronae",
    ),
    "byrne_2014": ActivityReference(
        "Byrne et al. 2014 (Nature Geoscience 7)",
        "https://doi.org/10.1038/ngeo2097",
        "Mercury's total radial contraction from the shortening recorded in its "
        "thrust faults",
        "Mercury contraction",
    ),
    "byrne_2016": ActivityReference(
        "Byrne et al. 2016 (Geophysical Research Letters 43)",
        "https://doi.org/10.1002/2016GL069412",
        "Crater ages showing Mercury's widespread effusive volcanism ended by "
        "about 3.5 Ga",
        "Mercury volcanism age",
    ),
    "watters_2016": ActivityReference(
        "Watters et al. 2016 (Nature Geoscience 9)",
        "https://doi.org/10.1038/ngeo2814",
        "Small thrust-fault scarps on Mercury young enough to imply the planet "
        "is still contracting",
        "Mercury young scarps",
    ),
    "watters_2019": ActivityReference(
        "Watters et al. 2019 (Nature Geoscience 12)",
        "https://doi.org/10.1038/s41561-019-0362-2",
        "Shallow moonquakes associated with young lunar thrust faults",
        "Moon thrust faults",
    ),
    "braden_2014": ActivityReference(
        "Braden et al. 2014 (Nature Geoscience 7)",
        "https://doi.org/10.1038/ngeo2252",
        "Irregular mare patches dated to within the last 100 Myr — the case for "
        "young lunar basaltic volcanism",
        "Moon young volcanism",
    ),
    "horvath_2021": ActivityReference(
        "Horvath et al. 2021 (Icarus 365)",
        "https://doi.org/10.1016/j.icarus.2021.114499",
        "A pyroxene-rich deposit at Cerberus Fossae dated to 53-210 ka, the "
        "youngest volcanic candidate on Mars",
        "Mars youngest eruption",
    ),
    "giardini_2020": ActivityReference(
        "Giardini et al. 2020 (Nature Geoscience 13)",
        "https://doi.org/10.1038/s41561-020-0539-8",
        "InSight's marsquake catalogue, locating Mars's seismicity at Cerberus Fossae",
        "Mars seismicity",
    ),
    "davies_2024": ActivityReference(
        "Davies et al. 2024 (Planetary Science Journal 5)",
        "https://doi.org/10.3847/PSJ/ad4346",
        "Global map of Io's volcanic thermal emission — 343 thermal sources and "
        "their combined 57.7 TW",
        "Io hot-spot map",
    ),
    "veeder_1994": ActivityReference(
        "Veeder et al. 1994 (JGR Planets 99)",
        "https://doi.org/10.1029/94JE00637",
        "Io's total heat flow from a decade of ground-based infrared radiometry",
        "Io heat flow",
    ),
    "porco_2014": ActivityReference(
        "Porco, DiNino & Nimmo 2014 (Astronomical Journal 148)",
        "https://doi.org/10.1088/0004-6256/148/3/45",
        "Locations of 101 individual geysers along Enceladus's tiger stripes and "
        "their relation to tidal stress",
        "Enceladus geysers",
    ),
    "hansen_2020": ActivityReference(
        "Hansen et al. 2020 (Icarus 344)",
        "https://doi.org/10.1016/j.icarus.2019.113461",
        "Water-vapour source rate of the Enceladus plume from the complete set of "
        "Cassini ultraviolet occultations",
        "Enceladus plume rate",
    ),
    "paganini_2019": ActivityReference(
        "Paganini et al. 2019 (Nature Astronomy 4)",
        "https://doi.org/10.1038/s41550-019-0933-6",
        "A single water-vapour detection in seventeen nights of Europa "
        "observations — the case that its plumes are sporadic",
        "Europa water vapour",
    ),
    "lopes_2013": ActivityReference(
        "Lopes et al. 2013 (JGR Planets 118)",
        "https://doi.org/10.1002/jgre.20062",
        "Sotra Patera and Doom Mons as Titan's strongest cryovolcanic candidate, "
        "from Cassini radar and infrared together",
        "Titan cryovolcano",
    ),
    "soderblom_1990": ActivityReference(
        "Soderblom et al. 1990 (Science 250)",
        "https://doi.org/10.1126/science.250.4979.410",
        "Discovery of four active geyser-like plumes on Triton in Voyager 2 imaging",
        "Triton plumes",
    ),
    "singer_2022": ActivityReference(
        "Singer et al. 2022 (Nature Communications 13)",
        "https://doi.org/10.1038/s41467-022-29056-3",
        "Wright and Piccard Montes as a large-scale cryovolcanic resurfacing of "
        "Pluto, with no impact craters on the deposit",
        "Pluto cryovolcanism",
    ),
    "sori_2018": ActivityReference(
        "Sori et al. 2018 (Nature Astronomy 2)",
        "https://doi.org/10.1038/s41550-018-0574-1",
        "Ceres's average cryomagma extrusion rate, from the viscous "
        "flattening of 22 domes",
        "Ceres cryovolcanic rate",
    ),
    "mcsween_2013": ActivityReference(
        "McSween et al. 2013 (Meteoritics & Planetary Science 48)",
        "https://doi.org/10.1111/maps.12108",
        "The Vesta-HED connection — eucrite basalts dating Vesta's volcanism to "
        "the first few Myr of the solar system",
        "Vesta volcanism age",
    ),
    # --- tidal heating ------------------------------------------------------
    "matsuyama_2022": ActivityReference(
        "Matsuyama, Steinke & Nimmo 2022 (Elements 18)",
        "https://doi.org/10.2138/gselements.18.6.374",
        "Tidal heating in Io and the Laplace resonance that sustains it",
        "Io tidal heating",
    ),
    "park_2025": ActivityReference(
        "Park et al. 2025 (Nature 638)",
        "https://doi.org/10.1038/s41586-024-08442-5",
        "Io's tidal Love number and dissipation factor from Juno and Galileo "
        "Doppler tracking",
        "Io tidal response",
    ),
    "nimmo_2025": ActivityReference(
        "Nimmo 2025 (Proc. R. Soc. A 481)",
        "https://doi.org/10.1098/rspa.2024.0806",
        "Review of moon interiors and evolution — tidal heat fluxes, ice-shell "
        "thicknesses and surface ages across the outer solar system",
        "moon heat fluxes",
    ),
    "nimmo_2018": ActivityReference(
        "Nimmo et al. 2018 (Enceladus and the Icy Moons of Saturn)",
        "https://doi.org/10.2458/azu_uapress_9780816537075-ch005",
        "Enceladus's thermal and orbital evolution — its radiogenic budget "
        "against its observed heat loss, and the Dione resonance",
        "Enceladus heat budget",
    ),
    "howett_2011": ActivityReference(
        "Howett et al. 2011 (JGR Planets 116)",
        "https://doi.org/10.1029/2010JE003718",
        "Endogenic power of Enceladus's south polar terrain from Cassini "
        "far-infrared spectra",
        "Enceladus heat output",
    ),
    "spencer_2013": ActivityReference(
        "Spencer et al. 2013 (EPSC Abstracts 8, EPSC2013-840)",
        "https://meetingorganizer.copernicus.org/EPSC2013/EPSC2013-840-1.pdf",
        "Enceladus south polar heat flow from Cassini scans that resolve the "
        "tiger stripes",
        "Enceladus heat output",
    ),
    "lainey_2024": ActivityReference(
        "Lainey et al. 2024 (Nature 626)",
        "https://doi.org/10.1038/s41586-023-06975-9",
        "A recently formed global ocean inside Mimas, from the precession of its orbit",
        "Mimas young ocean",
    ),
    "munk_1998": ActivityReference(
        "Munk & Wunsch 1998 (Deep-Sea Research I 45)",
        "https://doi.org/10.1016/S0967-0637(98)00070-3",
        "The energy budget of Earth's astronomical tides",
        "Earth tidal power",
    ),
    # --- magnetic fields ----------------------------------------------------
    "wso_polar": ActivityReference(
        "Wilcox Solar Observatory polar field observations (Stanford University)",
        "http://wso.stanford.edu/Polar.html",
        "The Sun's line-of-sight polar magnetic field, measured every ten days "
        "since 1976 (Svalgaard, Duvall & Scherrer 1978)",
        "solar polar field",
    ),
    "anderson_2012": ActivityReference(
        "Anderson et al. 2012 (JGR Planets 117)",
        "https://doi.org/10.1029/2012JE004159",
        "Mercury's dipole moment, northward offset and tilt bound from MESSENGER "
        "magnetometer observations",
        "Mercury dipole",
    ),
    "phillips_1987": ActivityReference(
        "Phillips & Russell 1987 (JGR Space Physics 92)",
        "https://doi.org/10.1029/JA092iA03p02253",
        "Upper limit on Venus's intrinsic magnetic moment from 18,000 Pioneer "
        "Venus nightside measurements",
        "Venus field limit",
    ),
    "igrf_14": ActivityReference(
        "IGRF-14 (IAGA Working Group V-MOD, 2024)",
        "https://doi.org/10.5281/zenodo.14218973",
        "Spherical-harmonic model of Earth's main field — the dipole moment, "
        "tilt and surface intensity at epoch 2025.0",
        "Earth field model",
    ),
    "tsunakawa_2015": ActivityReference(
        "Tsunakawa et al. 2015 (JGR Planets 120)",
        "https://doi.org/10.1002/2014JE004785",
        "Surface vector maps of the Moon's crustal magnetic anomalies from "
        "Kaguya and Lunar Prospector",
        "Moon crustal field",
    ),
    "mighani_2020": ActivityReference(
        "Mighani et al. 2020 (Science Advances 6)",
        "https://doi.org/10.1126/sciadv.aax0883",
        "Apollo breccias that cooled in a near-zero field, bracketing the end of "
        "the lunar dynamo",
        "lunar dynamo end",
    ),
    "mittelholz_2022": ActivityReference(
        "Mittelholz & Johnson 2022 (Frontiers in Astronomy and Space Sciences 9)",
        "https://doi.org/10.3389/fspas.2022.895362",
        "Review of Mars's crustal magnetic field — the InSight surface "
        "measurement and the age of the Martian dynamo",
        "Mars crustal field",
    ),
    "connerney_2022": ActivityReference(
        "Connerney et al. 2022 (JGR Planets 127)",
        "https://doi.org/10.1029/2021JE007055",
        "JRM33 — Jupiter's dipole moment, tilt and surface field range at the "
        "completion of Juno's prime mission",
        "Jupiter field model",
    ),
    "khurana_2011": ActivityReference(
        "Khurana et al. 2011 (Science 332)",
        "https://doi.org/10.1126/science.1201425",
        "Galileo magnetometer signature at Io, read as induction in a global "
        "magma ocean",
        "Io induction",
    ),
    "khurana_1998": ActivityReference(
        "Khurana et al. 1998 (Nature 395)",
        "https://doi.org/10.1038/27394",
        "Induced magnetic fields at Europa and Callisto, and the conductive "
        "layers they require",
        "Galilean induction",
    ),
    "kivelson_2002": ActivityReference(
        "Kivelson, Khurana & Volwerk 2002 (Icarus 157)",
        "https://doi.org/10.1006/icar.2002.6834",
        "Ganymede's permanent and induced magnetic moments from five Galileo flybys",
        "Ganymede dipole",
    ),
    "cao_2020": ActivityReference(
        "Cao et al. 2020 (Icarus 344)",
        "https://doi.org/10.1016/j.icarus.2019.113541",
        "Saturn's internal field from the Cassini Grand Finale — dipole "
        "strength, the arcsecond tilt bound and the northward offset",
        "Saturn field model",
    ),
    "wei_2010": ActivityReference(
        "Wei et al. 2010 (JGR Planets 115)",
        "https://doi.org/10.1029/2009JE003538",
        "Upper limit on Titan's permanent magnetic moment from 25 Cassini flybys",
        "Titan field limit",
    ),
    "connerney_1987": ActivityReference(
        "Connerney, Acuña & Ness 1987 (JGR Space Physics 92)",
        "https://doi.org/10.1029/JA092iA13p15329",
        "The Q3 model of Uranus's magnetic field — dipole strength, 59° tilt and "
        "off-centre position",
        "Uranus field model",
    ),
    "connerney_1991": ActivityReference(
        "Connerney, Acuña & Ness 1991 (JGR Space Physics 96)",
        "https://doi.org/10.1029/91JA01165",
        "The O8 model of Neptune's magnetic field from Voyager 2",
        "Neptune field model",
    ),
    "garrett_2015": ActivityReference(
        "Garrett et al. 2015 (JPL Publication 15-7)",
        "https://ntrs.nasa.gov/citations/20160009378",
        "Offset tilted-dipole parameters for Uranus, tabulated from Connerney's "
        "Q3 model",
        "Uranus dipole offset",
    ),
    "garrett_2017": ActivityReference(
        "Garrett et al. 2017 (JPL Publication 17-2)",
        "https://ntrs.nasa.gov/citations/20170006886",
        "Offset tilted-dipole parameters for Jupiter, compared against the "
        "spherical-harmonic models",
        "Jupiter dipole offset",
    ),
}
