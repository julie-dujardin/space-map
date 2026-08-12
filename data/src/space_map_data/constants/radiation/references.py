"""Citable sources behind the radiation facts, for the /credits page.

One entry per work a number or a classification actually comes from, keyed by
the `source` strings used in `environments.py` and `belts.py`. Per-value
provenance stays as comments next to each constant; this is what gets
exported.

Several are not journal papers. Apollo 11's mission report is here because it
holds the only flown dosimetry of a Van Allen crossing anyone has published as
a crew dose, UNSCEAR's survey because Earth's own background is a global
average of measurements rather than anybody's result, and SIDC's cycle listing
because the epoch a solar cycle is counted from is an observatory's call.

Two keys need explaining. `garrett_2015` and `garrett_2017` also appear in
`activity/references.py`, where the same two JPL model reports supply Uranus's
and Neptune's dipole offsets; the keys and URLs match so the credits exporter
folds them into one row, and only the contribution sentences differ, because
what a credits page owes a reader is what the work was used *for*. And
`roussos_2020` and `roussos_2020_gcr` are two different works by the same first
author in the same year — the belt structure of the giant planets in one, the
radial gradient of cosmic rays between 1 and 9.5 au in the other.
"""

from typing import NamedTuple


class RadiationReference(NamedTuple):
    title: str
    url: str
    contribution: str
    note: str = ""


RADIATION_SOURCES: dict[str, RadiationReference] = {
    # --- measured dose rates -----------------------------------------------
    "hassler_2014": RadiationReference(
        "Hassler et al. 2014 (Science 343)",
        "https://doi.org/10.1126/science.1244797",
        "The dose equivalent rate MSL/RAD measured over its first 300 sols on "
        "the surface of Mars — the first such measurement made on another "
        "planet",
        "Mars surface dose",
    ),
    "guo_2021": RadiationReference(
        "Guo et al. 2021 (The Astronomy and Astrophysics Review 29)",
        "https://doi.org/10.1007/s00159-021-00136-5",
        "A full solar cycle of MSL/RAD dose measurements: the revised "
        "free-space cruise rate, and the factor of four the Martian surface "
        "dose moves through as solar activity rises and falls",
        "cruise dose & solar cycle",
    ),
    "zhang_2020": RadiationReference(
        "Zhang et al. 2020 (Science Advances 6)",
        "https://doi.org/10.1126/sciadv.aaz1334",
        "The first dose measurement on the lunar surface, from Chang'e-4's "
        "Lunar Lander Neutrons and Dosimetry experiment, and the ISS "
        "comparison it is quoted against",
        "lunar surface dose",
    ),
    "unscear_2008": RadiationReference(
        "UNSCEAR 2008 Report, Annex B: Exposures of the public and workers "
        "from various sources of radiation",
        "https://www.unscear.org/unscear/en/publications/2008_1.html",
        "The worldwide average effective dose from cosmic radiation at "
        "Earth's surface, which is the figure the other bodies here compare "
        "against",
        "Earth background",
    ),
    "apollo_11_report": RadiationReference(
        "Apollo 11 Mission Report (NASA MSC-00171, 1969)",
        "https://www.nasa.gov/wp-content/uploads/static/history/alsj/a11/"
        "A11_MissionReport.pdf",
        "Crew dosimetry for the mission, including the Van Allen belt "
        "dosimeter reading that remains the only published crew dose for a "
        "belt crossing",
        "Apollo belt dose",
    ),
    # --- modelled environments ---------------------------------------------
    "europa_lander_sdt_2016": RadiationReference(
        "Europa Lander Study 2016 Report (NASA/JPL, Science Definition Team)",
        "https://europa.nasa.gov/resources/58/europa-lander-study-2016-report/",
        "The unshielded surface radiation environment at Europa and the "
        "shielding budget a lander would need to survive it",
        "Europa surface dose",
    ),
    "paranicas_2007": RadiationReference(
        "Paranicas et al. 2007 (Geophysical Research Letters 34)",
        "https://doi.org/10.1029/2007GL030834",
        "How much of the incoming electron flux a site on Europa's surface is "
        "spared by the moon itself blocking the sky, against a spacecraft in "
        "the same orbit",
        "Europa self-shielding",
    ),
    "johnson_2004": RadiationReference(
        "Johnson, Carlson, Cooper et al. 2004, 'Radiation Effects on the "
        "Surfaces of the Galilean Satellites', in Jupiter: The Planet, "
        "Satellites and Magnetosphere (Cambridge University Press)",
        "https://lasp.colorado.edu/mop/files/2015/08/jupiter_ch20-1.pdf",
        "Globally averaged particle energy fluxes to the surfaces of Io, "
        "Europa, Ganymede and Callisto, which is what sets the two hundred "
        "and fifty-fold spread across the four",
        "Galilean surface fluxes",
    ),
    "gronoff_2011": RadiationReference(
        "Gronoff et al. 2011 (Astronomy & Astrophysics 529)",
        "https://doi.org/10.1051/0004-6361/201015675",
        "Where cosmic rays stop in Titan's atmosphere — an ionization peak "
        "65 km up, with the whole troposphere still below it",
        "Titan's cosmic-ray depth",
    ),
    "herbst_2020": RadiationReference(
        "Herbst et al. 2020 (Astronomy & Astrophysics 633)",
        "https://doi.org/10.1051/0004-6361/201936968",
        "Altitude-resolved cosmic-ray dose rates through Venus's atmosphere, "
        "showing how little survives its column",
        "Venus atmospheric dose",
    ),
    # --- belts and magnetospheres ------------------------------------------
    "roussos_2020": RadiationReference(
        "Roussos & Kollmann 2020 (in Magnetospheres in the Solar System, "
        "AGU Geophysical Monograph 259)",
        "https://doi.org/10.48550/arXiv.2006.14682",
        "The structure of Jupiter's and Saturn's radiation belts from the "
        "Galileo, Juno and Cassini records — inner edges, intensity peaks, "
        "and the moons and rings that cut Saturn's into sectors",
        "giant planet belts",
    ),
    "wang_2026": RadiationReference(
        "Wang et al. 2026 (Nature Astronomy)",
        "https://doi.org/10.1038/s41550-026-02925-3",
        "MESSENGER's record of Mercury's intermittent electron radiation "
        "belt, present about half the time near aphelion and largely absent "
        "near perihelion",
        "Mercury's part-time belt",
    ),
    "garrett_2015": RadiationReference(
        "Garrett et al. 2015 (JPL Publication 15-1), Uranus Radiation Model",
        "https://ntrs.nasa.gov/citations/20160009378",
        "The Voyager 2 fit that establishes Uranus has trapped-particle belts "
        "and where they sit",
        "Uranus belt model",
    ),
    "garrett_2017": RadiationReference(
        "Garrett et al. 2017 (JPL Publication 17-3), Neptune Radiation Model",
        "https://ntrs.nasa.gov/citations/20170006886",
        "The Voyager 2 fit that establishes Neptune has trapped-particle "
        "belts and where they sit",
        "Neptune belt model",
    ),
    # --- the field model ----------------------------------------------------
    "miller_1976": RadiationReference(
        "Miller, Kaufman & Maillie 1976 (Life Sciences and Space Research 14)",
        "https://pubmed.ncbi.nlm.nih.gov/12678105/",
        "What the two Pioneers absorbed flying through Jupiter's belts, worked "
        "out for a body rather than for electronics — the only published dose "
        "for a close Jupiter pass, and the finding that even the gentler of the "
        "two would have killed a crew",
        "Pioneer Jupiter flyby doses",
    ),
    "roussos_2020_gcr": RadiationReference(
        "Roussos et al. 2020 (The Astrophysical Journal 904, 165)",
        "https://doi.org/10.3847/1538-4357/abc346",
        "How much cosmic ray intensity climbs with distance from the Sun, "
        "fitted over 1 to 9.5 au against Cassini's high-energy protons — the "
        "term that makes the outer system harsher than the inner one",
        "radial gradient",
    ),
    "smart_shea_2005": RadiationReference(
        "Smart & Shea 2005 (Advances in Space Research 36, 2012)",
        "https://doi.org/10.1016/j.asr.2004.09.015",
        "The geomagnetic cutoff rigidity a planet's dipole imposes on arriving "
        "cosmic rays, which is why low Earth orbit is quieter than free space "
        "by more than the Earth blocking half the sky accounts for",
        "geomagnetic cutoff",
    ),
    "sidc_cycle_minima": RadiationReference(
        "SIDC/SILSO, Royal Observatory of Belgium: solar cycle minima",
        "https://www.sidc.be/SILSO/solar-cycle-minimum-passed-december-2019",
        "The December 2019 minimum and the eleven years back to the last one, "
        "which set the phase and period cosmic ray dose is modelled against",
        "solar cycle epoch",
    ),
}
