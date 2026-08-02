"""Citable sources behind the interior facts, for the /credits page.

One entry per work a number actually comes from, keyed by the `source` strings
used in `bodies.py` and `taxonomy.py`. Per-value provenance stays as comments
next to each constant; this is what gets exported.

Two works are deliberately absent: SsODNet, which supplies the spectral
classes rather than any interior number, and Mahlke, whose scheme and albedo
cut decide the class letter. They are credited under object metadata on the
/credits page and reach the panel through `interior.taxonomy_sources`, which
ships ids rather than citations because 171,000 asteroids carry them.
"""

from typing import NamedTuple


class InteriorReference(NamedTuple):
    title: str
    url: str
    contribution: str


INTERIOR_SOURCES: dict[str, InteriorReference] = {
    # --- per-body interiors ------------------------------------------------
    "mcdonough_2003": InteriorReference(
        "McDonough 2003 (Treatise on Geochemistry 2.15)",
        "https://doi.org/10.1016/B0-08-043751-6/02015-6",
        "Earth's inner core, outer core and mantle masses; core element budget",
    ),
    "mcdonough_1995": InteriorReference(
        "McDonough & Sun 1995 (Chemical Geology 120)",
        "https://doi.org/10.1016/0009-2541(94)00140-4",
        "Bulk silicate Earth oxide composition",
    ),
    "dziewonski_1981": InteriorReference(
        "Dziewonski & Anderson 1981 (Phys. Earth Planet. Inter. 25)",
        "https://doi.org/10.1016/0031-9201(81)90046-7",
        "Preliminary Reference Earth Model — layer boundaries",
    ),
    "stahler_2021": InteriorReference(
        "Stähler et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abi7730",
        "Mars core radius and density from InSight seismic reflections",
    ),
    "knapmeyer_endrun_2021": InteriorReference(
        "Knapmeyer-Endrun et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf8966",
        "Mars crustal thickness and density from InSight receiver functions",
    ),
    "hauck_2013": InteriorReference(
        "Hauck et al. 2013 (JGR Planets 118)",
        "https://doi.org/10.1002/jgre.20091",
        "Mercury core radius, outer-shell thickness and density from MESSENGER",
    ),
    "garcia_2011": InteriorReference(
        "Garcia et al. 2011 (Phys. Earth Planet. Inter. 188)",
        "https://doi.org/10.1016/j.pepi.2011.06.015",
        "VPREMOON — lunar core radius and density from core-reflected shear phases",
    ),
    "wieczorek_2013": InteriorReference(
        "Wieczorek et al. 2013 (Science 339)",
        "https://doi.org/10.1126/science.1231530",
        "Lunar crustal thickness, bulk density and porosity from GRAIL",
    ),
    "iess_2014": InteriorReference(
        "Iess et al. 2014 (Science 344)",
        "https://doi.org/10.1126/science.1250551",
        "Enceladus gravity field, ice-shell and ocean densities, core size",
    ),
    "khan_2021": InteriorReference(
        "Khan et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf2966",
        "Mars upper-mantle structure from InSight",
    ),
    "weber_2011": InteriorReference(
        "Weber et al. 2011 (Science 331)",
        "https://doi.org/10.1126/science.1199375",
        "Lunar inner and outer core radii and densities from Apollo seismograms",
    ),
    "anderson_2001_io": InteriorReference(
        "Anderson et al. 2001 (J. Geophys. Res. 106 E12)",
        "https://doi.org/10.1029/2000JE001367",
        "Io gravity field, moment of inertia and core-radius bounds from Galileo",
    ),
    "anderson_1998": InteriorReference(
        "Anderson et al. 1998 (Science 281)",
        "https://doi.org/10.1126/science.281.5385.2019",
        "Europa moment of inertia and water-shell thickness from Galileo",
    ),
    "anderson_1996": InteriorReference(
        "Anderson et al. 1996 (Nature 384)",
        "https://doi.org/10.1038/384541a0",
        "Ganymede moment of inertia, core mass range and ice-rock interface",
    ),
    "anderson_2001_callisto": InteriorReference(
        "Anderson et al. 2001 (Icarus 153)",
        "https://doi.org/10.1006/icar.2001.6664",
        "Callisto radius, moment of inertia and partially differentiated interior",
    ),
    "iess_2012": InteriorReference(
        "Iess et al. 2012 (Science 337)",
        "https://doi.org/10.1126/science.1219631",
        "Titan tidal Love number — evidence for a global subsurface ocean",
    ),
    "hussmann_2006": InteriorReference(
        "Hussmann, Sohl & Spohn 2006 (Icarus 185)",
        "https://doi.org/10.1016/j.icarus.2006.06.005",
        "Two-layer rock/ice mass fractions for the medium-sized icy satellites",
    ),
    "ermakov_2014": InteriorReference(
        "Ermakov et al. 2014 (Icarus 240)",
        "https://doi.org/10.1016/j.icarus.2014.05.015",
        "Vesta core radius and density, and crustal thickness, from Dawn",
    ),
    "park_2016": InteriorReference(
        "Park et al. 2016 (Nature 537)",
        "https://doi.org/10.1038/nature18955",
        "Ceres core size and shell density from Dawn gravity and shape",
    ),
    "zannoni_2020": InteriorReference(
        "Zannoni et al. 2020 (Icarus 345)",
        "https://doi.org/10.1016/j.icarus.2020.113713",
        "Dione gravity field, core size and floating ice shell from Cassini",
    ),
    "wahl_2017": InteriorReference(
        "Wahl et al. 2017 (Geophys. Res. Lett. 44)",
        "https://doi.org/10.1002/2017GL073160",
        "Jupiter dilute-core heavy-element mass and envelope composition from Juno",
    ),
    "iess_2019": InteriorReference(
        "Iess et al. 2019 (Science 364)",
        "https://doi.org/10.1126/science.aat2965",
        "Saturn core mass and radius, and envelope abundances, from the Grand Finale",
    ),
    "helled_2011": InteriorReference(
        "Helled, Anderson, Podolak & Schubert 2011 (Astrophys. J. 726)",
        "https://doi.org/10.1088/0004-637X/726/1/15",
        "Uranus and Neptune bulk hydrogen, helium and heavy-element fractions",
    ),
    "bahcall_2005": InteriorReference(
        "Bahcall, Serenelli & Basu 2005 (Astrophys. J. 621)",
        "https://doi.org/10.1086/428929",
        "Standard solar model — surface and central abundances, convective-zone depth",
    ),
    "durante_2019": InteriorReference(
        "Durante et al. 2019 (Icarus 326)",
        "https://doi.org/10.1016/j.icarus.2019.03.003",
        "Titan gravity field, moment of inertia and two-layer interior from Cassini",
    ),
    "genova_2019": InteriorReference(
        "Genova et al. 2019 (Geophys. Res. Lett. 46)",
        "https://doi.org/10.1029/2018GL081135",
        "Mercury crustal thickness and density, and outer- and inner-core radii",
    ),
    "bierson_2022": InteriorReference(
        "Bierson & Nimmo 2022 (Icarus 373)",
        "https://doi.org/10.1016/j.icarus.2021.114776",
        "Uranian satellite core radii and rock fractions on post-Voyager masses",
    ),
    "nimmo_2025": InteriorReference(
        "Nimmo, Bierson & McKinnon 2025 (in Triton and Pluto, IOP Publishing)",
        "https://doi.org/10.1088/2514-3433/ad5278ch2",
        "Pluto, Charon and Triton radii, densities and rock mass fractions",
    ),
    # --- taxonomy → meteorite analogue ------------------------------------
    "demeo_2009": InteriorReference(
        "DeMeo et al. 2009 (Icarus 202)",
        "https://doi.org/10.1016/j.icarus.2009.02.005",
        "Bus-DeMeo taxonomy — the class definitions the estimates key off",
    ),
    "neeley_2014": InteriorReference(
        "Neeley et al. 2014 (Icarus 238)",
        "https://doi.org/10.1016/j.icarus.2014.05.008",
        "M-type asteroid analogues — metal-with-silicate rather than clean iron",
    ),
    "sunshine_2008": InteriorReference(
        "Sunshine et al. 2008 (Science 320)",
        "https://doi.org/10.1126/science.1154340",
        "L-type asteroids enriched in refractory inclusions",
    ),
    "krot_2014": InteriorReference(
        "Krot et al. 2014 (Treatise on Geochemistry 1.1)",
        "https://doi.org/10.1016/B978-0-08-095975-7.00102-9",
        "Meteorite classification and modal metal/sulphide/silicate abundances",
    ),
    "jarosewich_1990": InteriorReference(
        "Jarosewich 1990 (Meteoritics 25)",
        "https://doi.org/10.1111/j.1945-5100.1990.tb00717.x",
        "Bulk chemical analyses of stony and iron meteorites",
    ),
    "wasson_1988": InteriorReference(
        "Wasson & Kallemeyn 1988 (Phil. Trans. R. Soc. A 325)",
        "https://doi.org/10.1098/rsta.1988.0066",
        "Chondrite compositions — carbonaceous water and carbon contents",
    ),
}
