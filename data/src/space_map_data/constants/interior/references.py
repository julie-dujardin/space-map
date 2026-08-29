"""Citable sources behind the interior facts, for the /credits page.

One entry per work a number actually comes from, keyed by the `source`
strings used in `bodies.py` and `taxonomy.py`. Per-value provenance stays as
comments next to each constant; this is what gets exported.

Two works are deliberately absent: SsODNet, which supplies the spectral
classes rather than any interior number, and Mahlke, whose scheme and albedo
cut decide the class letter. They're credited under object metadata on
/credits and reach the panel through `interior.taxonomy_sources`, which
ships ids rather than citations because 171,000 asteroids carry them.

`contribution` is the credits page's sentence; `note` is the two or three
words the object panel's credit line has room for, styled like its
provider roles ("sizes, albedos & spectral types").
"""

from typing import NamedTuple


class InteriorReference(NamedTuple):
    title: str
    url: str
    contribution: str
    note: str = ""


INTERIOR_SOURCES: dict[str, InteriorReference] = {
    # --- per-body interiors ------------------------------------------------
    "mcdonough_2003": InteriorReference(
        "McDonough 2003 (Treatise on Geochemistry 2.15)",
        "https://doi.org/10.1016/B0-08-043751-6/02015-6",
        "Earth's inner core, outer core and mantle masses; core element budget",
        "Earth layer masses",
    ),
    "hirose_2021": InteriorReference(
        "Hirose, Wood & Vočadlo 2021 (Nature Reviews Earth & Environment 2)",
        "https://doi.org/10.1038/s43017-021-00203-6",
        "Light-element budget of Earth's inner core",
        "Earth inner-core alloy",
    ),
    "mcdonough_1995": InteriorReference(
        "McDonough & Sun 1995 (Chemical Geology 120)",
        "https://doi.org/10.1016/0009-2541(94)00140-4",
        "Bulk silicate Earth oxide composition",
        "Earth mantle chemistry",
    ),
    "dziewonski_1981": InteriorReference(
        "Dziewonski & Anderson 1981 (Phys. Earth Planet. Inter. 25)",
        "https://doi.org/10.1016/0031-9201(81)90046-7",
        "Preliminary Reference Earth Model — layer boundaries",
        "Earth layer depths",
    ),
    "stahler_2021": InteriorReference(
        "Stähler et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abi7730",
        "Mars core radius and density from InSight seismic reflections",
        "Mars core size",
    ),
    "knapmeyer_endrun_2021": InteriorReference(
        "Knapmeyer-Endrun et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf8966",
        "Mars crustal thickness and density from InSight receiver functions",
        "Mars crust thickness",
    ),
    "hauck_2013": InteriorReference(
        "Hauck et al. 2013 (JGR Planets 118)",
        "https://doi.org/10.1002/jgre.20091",
        "Mercury core radius, outer-shell thickness and density from MESSENGER",
        "Mercury core size",
    ),
    "garcia_2011": InteriorReference(
        "Garcia et al. 2011 (Phys. Earth Planet. Inter. 188)",
        "https://doi.org/10.1016/j.pepi.2011.06.015",
        "VPREMOON — lunar core radius and density from core-reflected shear phases",
        "Moon core size",
    ),
    "wieczorek_2013": InteriorReference(
        "Wieczorek et al. 2013 (Science 339)",
        "https://doi.org/10.1126/science.1231530",
        "Lunar crustal thickness, bulk density and porosity from GRAIL",
        "Moon crust thickness",
    ),
    "iess_2014": InteriorReference(
        "Iess et al. 2014 (Science 344)",
        "https://doi.org/10.1126/science.1250551",
        "Enceladus gravity field, ice-shell and ocean densities, core size",
        "Enceladus ocean & core",
    ),
    "khan_2021": InteriorReference(
        "Khan et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf2966",
        "Mars upper-mantle structure from InSight",
        "Mars mantle structure",
    ),
    "weber_2011": InteriorReference(
        "Weber et al. 2011 (Science 331)",
        "https://doi.org/10.1126/science.1199375",
        "Lunar inner and outer core radii and densities from Apollo seismograms",
        "Moon core layers",
    ),
    "anderson_2001_io": InteriorReference(
        "Anderson et al. 2001 (J. Geophys. Res. 106 E12)",
        "https://doi.org/10.1029/2000JE001367",
        "Io gravity field, moment of inertia and core-radius bounds from Galileo",
        "Io core size",
    ),
    "anderson_1998": InteriorReference(
        "Anderson et al. 1998 (Science 281)",
        "https://doi.org/10.1126/science.281.5385.2019",
        "Europa moment of inertia and water-shell thickness from Galileo",
        "Europa water shell",
    ),
    "garcia_2007": InteriorReference(
        "García et al. 2007 (Science 316)",
        "https://doi.org/10.1126/science.1140598",
        "The solar core as the region below 0.2 R☉, and its faster rotation",
        "solar core extent",
    ),
    "howell_2021": InteriorReference(
        "Howell 2021 (Planetary Science Journal 2)",
        "https://doi.org/10.3847/PSJ/abfe10",
        "Europa ice-shell thickness distribution from a steady-state heat balance",
        "Europa ice-shell thickness",
    ),
    "taylor_mclennan_2009": InteriorReference(
        "Taylor & McLennan 2009 (Planetary Crusts, Cambridge)",
        "https://doi.org/10.1017/CBO9780511575358",
        "Bulk oxide compositions of the Martian, lunar highland and "
        "terrestrial continental crusts, and the continental crust's "
        "thickness, area and share of Earth's mass; the andesitic, "
        "anorthositic and basaltic rock types of the terrestrial, lunar "
        "and Venusian crusts",
        "rocky crust chemistry",
    ),
    "white_klein_2014": InteriorReference(
        "White & Klein 2014 (Treatise on Geochemistry 4.13)",
        "https://doi.org/10.1016/B978-0-08-095975-7.00315-6",
        "Thickness, bulk oxide composition and basalt-over-gabbro structure "
        "of Earth's oceanic crust",
        "oceanic crust chemistry",
    ),
    "mcsween_2009": InteriorReference(
        "McSween, Taylor & Wyatt 2009 (Science 324)",
        "https://doi.org/10.1126/science.1165871",
        "Tholeiitic basalt as the rock type of the Martian crust",
        "Mars crust rock type",
    ),
    "carlson_raskin_1984": InteriorReference(
        "Carlson & Raskin 1984 (Nature 311)",
        "https://doi.org/10.1038/311555a0",
        "Mean density of Earth's oceanic crust",
        "oceanic crust density",
    ),
    "charette_smith_2010": InteriorReference(
        "Charette & Smith 2010 (Oceanography 23)",
        "https://doi.org/10.5670/oceanog.2010.51",
        "Volume, area and mean depth of Earth's ocean from satellite altimetry",
        "Earth ocean volume",
    ),
    "millero_2008": InteriorReference(
        "Millero et al. 2008 (Deep-Sea Research I 55)",
        "https://doi.org/10.1016/j.dsr.2007.10.001",
        "Reference Composition of seawater",
        "seawater composition",
    ),
    "hayes_2016": InteriorReference(
        "Hayes 2016 (Annu. Rev. Earth Planet. Sci. 44)",
        "https://doi.org/10.1146/annurev-earth-060115-012247",
        "Volume, area and ternary composition of Titan's lakes and seas",
        "Titan sea volumes",
    ),
    "nist_webbook": InteriorReference(
        "NIST Chemistry WebBook (SRD 69)",
        "https://webbook.nist.gov/chemistry/fluid/",
        "Liquid methane and ethane densities at Titan's surface conditions",
        "hydrocarbon densities",
    ),
    "iapso_2010": InteriorReference(
        "IOC, SCOR & IAPSO 2010 (TEOS-10, IOC Manuals and Guides 56)",
        "https://www.teos-10.org/pubs/TEOS-10_Manual.pdf",
        "Seawater equation of state, for the ocean's mean in-situ density",
        "seawater density",
    ),
    "margot_2021": InteriorReference(
        "Margot et al. 2021 (Nature Astronomy 5)",
        "https://doi.org/10.1038/s41550-021-01339-7",
        "Venus moment of inertia from radar speckle tracking, and the "
        "two-layer core radius that follows",
        "Venus core size",
    ),
    "dumoulin_2017": InteriorReference(
        "Dumoulin et al. 2017 (JGR Planets 122)",
        "https://doi.org/10.1002/2016JE005249",
        "Venus core density and the tidal models behind it",
        "Venus core density",
    ),
    "taylor_2013": InteriorReference(
        "Taylor 2013 (Chemie der Erde 73)",
        "https://doi.org/10.1016/j.chemer.2013.09.006",
        "Bulk silicate Mars oxide composition and the core's sulphur fraction",
        "Mars mantle chemistry",
    ),
    "nittler_2018": InteriorReference(
        "Nittler et al. 2018 (Mercury: The View after MESSENGER, Cambridge)",
        "https://doi.org/10.1017/9781316650684.003",
        "Mercury mantle silicate composition reconstructed from MESSENGER lavas",
        "Mercury mantle chemistry",
    ),
    "gomez_casajus_2021": InteriorReference(
        "Gomez Casajus et al. 2021 (Icarus 358)",
        "https://doi.org/10.1016/j.icarus.2020.114187",
        "Europa gravity field and moment of inertia, reanalysed from Galileo tracking",
        "Europa layer sizes",
    ),
    "goossens_2024": InteriorReference(
        "Goossens et al. 2024 (Nature Astronomy 8)",
        "https://doi.org/10.1038/s41550-024-02253-4",
        "Titan's core radius and density, and the low-density ocean above it",
        "Titan core & ocean",
    ),
    "gomez_casajus_2022": InteriorReference(
        "Gomez Casajus et al. 2022 (Geophysical Research Letters 49)",
        "https://doi.org/10.1029/2022GL099475",
        "Ganymede's moment of inertia from Juno, solved without the "
        "hydrostatic assumption, and the interior family it allows",
        "Ganymede layer sizes",
    ),
    "vance_2018": InteriorReference(
        "Vance et al. 2018 (JGR Planets 123)",
        "https://doi.org/10.1002/2017JE005341",
        "Ice-shell, ocean and core structure of the icy ocean worlds from "
        "self-consistent thermodynamics",
        "icy-moon layer models",
    ),
    "anderson_1996": InteriorReference(
        "Anderson et al. 1996 (Nature 384)",
        "https://doi.org/10.1038/384541a0",
        "Ganymede moment of inertia, core mass range and ice-rock interface",
        "Ganymede core mass",
    ),
    "anderson_2001_callisto": InteriorReference(
        "Anderson et al. 2001 (Icarus 153)",
        "https://doi.org/10.1006/icar.2001.6664",
        "Callisto radius, moment of inertia and partially differentiated interior",
        "Callisto rock-ice mix",
    ),
    "iess_2012": InteriorReference(
        "Iess et al. 2012 (Science 337)",
        "https://doi.org/10.1126/science.1219631",
        "Titan tidal Love number — evidence for a global subsurface ocean",
        "Titan ocean evidence",
    ),
    "beghin_2012": InteriorReference(
        "Béghin et al. 2012 (Icarus 218)",
        "https://doi.org/10.1016/j.icarus.2012.02.005",
        "Titan's Schumann resonance — a conducting layer 55-80 km down",
        "Titan ocean depth",
    ),
    "petricca_2025": InteriorReference(
        "Petricca et al. 2025 (Nature 648)",
        "https://doi.org/10.1038/s41586-025-09818-x",
        "Titan's dissipative tidal response, and the case against its ocean",
        "Titan tidal dissipation",
    ),
    "aygun_2026": InteriorReference(
        "Aygün, Kihoulou & Čadek 2026 (preprint)",
        "https://doi.org/10.22541/essoar.177307884.44798188/v1",
        "Titan's heat budget against an ocean-free interior",
        "Titan heat budget",
    ),
    "tajeddine_2014": InteriorReference(
        "Tajeddine et al. 2014 (Science 346)",
        "https://doi.org/10.1126/science.1255299",
        "Mimas libration amplitude from Cassini imaging",
        "Mimas libration",
    ),
    "lainey_2024": InteriorReference(
        "Lainey et al. 2024 (Nature 626)",
        "https://doi.org/10.1038/s41586-023-06975-9",
        "Mimas ice-shell thickness and ocean, from libration and periapsis drift",
        "Mimas ocean",
    ),
    "hartkorn_2017": InteriorReference(
        "Hartkorn & Saur 2017 (J. Geophys. Res. Space Physics 122)",
        "https://doi.org/10.1002/2017JA024269",
        "Callisto's ionosphere as an alternative source of the induction signal",
        "Callisto ionosphere",
    ),
    "cochrane_2025": InteriorReference(
        "Cochrane et al. 2025 (AGU Advances 6)",
        "https://doi.org/10.1029/2024AV001237",
        "Multifrequency Galileo induction favouring an ocean inside Callisto",
        "Callisto ocean evidence",
    ),
    "hussmann_2006": InteriorReference(
        "Hussmann, Sohl & Spohn 2006 (Icarus 185)",
        "https://doi.org/10.1016/j.icarus.2006.06.005",
        "Two-layer rock/ice mass fractions for the medium-sized icy satellites",
        "icy-moon rock fractions",
    ),
    "ermakov_2014": InteriorReference(
        "Ermakov et al. 2014 (Icarus 240)",
        "https://doi.org/10.1016/j.icarus.2014.05.015",
        "Vesta core radius and density, and crustal thickness, from Dawn",
        "Vesta core & crust",
    ),
    "park_2016": InteriorReference(
        "Park et al. 2016 (Nature 537)",
        "https://doi.org/10.1038/nature18955",
        "Ceres core size and shell density from Dawn gravity and shape",
        "Ceres core size",
    ),
    "zannoni_2020": InteriorReference(
        "Zannoni et al. 2020 (Icarus 345)",
        "https://doi.org/10.1016/j.icarus.2020.113713",
        "Dione gravity field, core size and floating ice shell from Cassini",
        "Dione core & ice shell",
    ),
    "wahl_2017": InteriorReference(
        "Wahl et al. 2017 (Geophys. Res. Lett. 44)",
        "https://doi.org/10.1002/2017GL073160",
        "Jupiter dilute-core heavy-element mass and envelope composition from Juno",
        "Jupiter core mass",
    ),
    "iess_2019": InteriorReference(
        "Iess et al. 2019 (Science 364)",
        "https://doi.org/10.1126/science.aat2965",
        "Saturn core mass and radius, and envelope abundances, from the Grand Finale",
        "Saturn core mass",
    ),
    "helled_2011": InteriorReference(
        "Helled, Anderson, Podolak & Schubert 2011 (Astrophys. J. 726)",
        "https://doi.org/10.1088/0004-637X/726/1/15",
        "Uranus and Neptune bulk hydrogen, helium and heavy-element fractions",
        "ice-giant bulk makeup",
    ),
    "bahcall_2005": InteriorReference(
        "Bahcall, Serenelli & Basu 2005 (Astrophys. J. 621)",
        "https://doi.org/10.1086/428929",
        "Standard solar model — surface and central abundances, convective-zone depth",
        "solar model layers",
    ),
    "durante_2019": InteriorReference(
        "Durante et al. 2019 (Icarus 326)",
        "https://doi.org/10.1016/j.icarus.2019.03.003",
        "Titan gravity field, moment of inertia and two-layer interior from Cassini",
        "Titan layer sizes",
    ),
    "genova_2019": InteriorReference(
        "Genova et al. 2019 (Geophys. Res. Lett. 46)",
        "https://doi.org/10.1029/2018GL081135",
        "Mercury crustal thickness and density, and outer- and inner-core radii",
        "Mercury crust & core",
    ),
    "bierson_2022": InteriorReference(
        "Bierson & Nimmo 2022 (Icarus 373)",
        "https://doi.org/10.1016/j.icarus.2021.114776",
        "Uranian satellite core radii and rock fractions on post-Voyager masses",
        "Uranian moon cores",
    ),
    "nimmo_2025": InteriorReference(
        "Nimmo, Bierson & McKinnon 2025 (in Triton and Pluto, IOP Publishing)",
        "https://doi.org/10.1088/2514-3433/ad5278ch2",
        "Pluto, Charon and Triton radii, densities and rock mass fractions, "
        "and the thermal models behind Pluto's ice-shell and ocean thicknesses",
        "Pluto-system interiors",
    ),
    "saur_2015": InteriorReference(
        "Saur et al. 2015 (JGR Space Physics 120)",
        "https://doi.org/10.1002/2014JA020778",
        "Ganymede's subsurface ocean, from the damping of its auroral ovals",
        "Ganymede ocean evidence",
    ),
    "zimmer_2000": InteriorReference(
        "Zimmer, Khurana & Kivelson 2000 (Icarus 147)",
        "https://doi.org/10.1006/icar.2000.6456",
        "Europa's and Callisto's oceans, from Galileo's induced magnetic fields",
        "Europa & Callisto oceans",
    ),
    "beuthe_2016": InteriorReference(
        "Beuthe, Rivoldini & Trinh 2016 (Geophys. Res. Lett. 43)",
        "https://doi.org/10.1002/2016GL070650",
        "Enceladus's and Dione's ice-shell and ocean thicknesses from "
        "minimum-stress isostasy",
        "Enceladus & Dione shells",
    ),
    "khan_2023": InteriorReference(
        "Khan et al. 2023 (Nature 622)",
        "https://doi.org/10.1038/s41586-023-06586-4",
        "Mars's molten silicate layer, and the smaller, denser core beneath it",
        "Mars magma layer",
    ),
    "bi_2025": InteriorReference(
        "Bi et al. 2025 (Nature 645)",
        "https://doi.org/10.1038/s41586-025-09361-9",
        "Mars's solid inner core, from PKKP and PKiKP arrivals",
        "Mars inner core",
    ),
    "park_2025_io": InteriorReference(
        "Park et al. 2025 (Nature 638)",
        "https://doi.org/10.1038/s41586-024-08442-5",
        "Io's tidal Love number, which excludes a global magma ocean",
        "Io magma-ocean limit",
    ),
    "park_2025_vesta": InteriorReference(
        "Park et al. 2025 (Nature Astronomy 9)",
        "https://doi.org/10.1038/s41550-025-02533-7",
        "Vesta's moment of inertia, and the crust, mantle and small core it allows",
        "Vesta layer sizes",
    ),
    "pamerleau_2024": InteriorReference(
        "Pamerleau, Sori & Scully 2024 (Nature Astronomy 8)",
        "https://doi.org/10.1038/s41550-024-02350-4",
        "Ceres's ice content, from crater relaxation under an impure ice rheology",
        "Ceres ice content",
    ),
    "james_2013": InteriorReference(
        "James, Zuber & Phillips 2013 (JGR Planets 118)",
        "https://doi.org/10.1029/2012JE004237",
        "Venus's mean crustal thickness from gravity and topography",
        "Venus crust thickness",
    ),
    "nettelmann_2012": InteriorReference(
        "Nettelmann et al. 2012 (Astrophys. J. 750)",
        "https://doi.org/10.1088/0004-637X/750/1/52",
        "Jupiter's molecular/metallic hydrogen boundary and the mass inside it",
        "Jupiter hydrogen boundary",
    ),
    "militzer_2022": InteriorReference(
        "Militzer et al. 2022 (Planetary Science Journal 3)",
        "https://doi.org/10.3847/PSJ/ac7ec8",
        "Jupiter's layer boundaries and the helium enrichment below its rain layer",
        "Jupiter layer depths",
    ),
    "mankovich_2021": InteriorReference(
        "Mankovich & Fuller 2021 (Nature Astronomy 5)",
        "https://doi.org/10.1038/s41550-021-01448-3",
        "Saturn's diffuse core, from gravity modes seen in its rings",
        "Saturn core extent",
    ),
    # --- boundary temperatures ---------------------------------------------
    # Gravity sizes a layer; none of it says how hot the layer is. These are
    # the works that put a number on a boundary, and they are separate papers
    # from the ones above almost every time.
    "anzellini_2013": InteriorReference(
        "Anzellini et al. 2013 (Science 340)",
        "https://doi.org/10.1126/science.1233514",
        "Earth's inner-core boundary temperature, from the iron melting curve",
        "Earth inner-core temperature",
    ),
    "nomura_2014": InteriorReference(
        "Nomura et al. 2014 (Science 343)",
        "https://doi.org/10.1126/science.1248186",
        "Earth's core-mantle boundary temperature, bounded by the pyrolite solidus",
        "Earth core-mantle temperature",
    ),
    "wilson_2025": InteriorReference(
        "Wilson et al. 2025 (Nature Reviews Earth & Environment 6)",
        "https://doi.org/10.1038/s43017-024-00639-6",
        "Temperature at the centre of the Earth",
        "Earth centre temperature",
    ),
    "jaupart_2007": InteriorReference(
        "Jaupart & Mareschal 2007 (Treatise on Geophysics 6.05)",
        "https://doi.org/10.1016/B978-044452748-6.00104-8",
        "Temperature at the base of the continental crust, across eight "
        "Canadian Shield provinces",
        "Earth crust-base temperature",
    ),
    "guillot_2005": InteriorReference(
        "Guillot 2005 (Annu. Rev. Earth Planet. Sci. 33)",
        "https://doi.org/10.1146/annurev.earth.32.101802.120325",
        "Giant-planet interior adiabats and central temperatures",
        "giant-planet temperatures",
    ),
    "helled_2024": InteriorReference(
        "Helled 2024 (AGU Advances 5)",
        "https://doi.org/10.1029/2024AV001171",
        "Post-Juno fuzzy-core interiors of Jupiter and Saturn",
        "Jupiter & Saturn cores",
    ),
    "scheibe_2019": InteriorReference(
        "Scheibe, Nettelmann & Redmer 2019 (A&A 632)",
        "https://doi.org/10.1051/0004-6361/201936378",
        "Thermal evolution models of Uranus and Neptune",
        "ice-giant temperatures",
    ),
    # --- taxonomy → meteorite analogue ------------------------------------
    "demeo_2009": InteriorReference(
        "DeMeo et al. 2009 (Icarus 202)",
        "https://doi.org/10.1016/j.icarus.2009.02.005",
        "Bus-DeMeo taxonomy — the class definitions the estimates key off",
        "asteroid class definitions",
    ),
    "neeley_2014": InteriorReference(
        "Neeley et al. 2014 (Icarus 238)",
        "https://doi.org/10.1016/j.icarus.2014.05.008",
        "M-type asteroid analogues — metal-with-silicate rather than clean iron",
        "M-type analogues",
    ),
    "sunshine_2008": InteriorReference(
        "Sunshine et al. 2008 (Science 320)",
        "https://doi.org/10.1126/science.1154340",
        "L-type asteroids enriched in refractory inclusions",
        "L-type analogues",
    ),
    "krot_2014": InteriorReference(
        "Krot et al. 2014 (Treatise on Geochemistry 1.1)",
        "https://doi.org/10.1016/B978-0-08-095975-7.00102-9",
        "Meteorite classification and modal metal/sulphide/silicate abundances",
        "meteorite mineral makeup",
    ),
    "jarosewich_1990": InteriorReference(
        "Jarosewich 1990 (Meteoritics 25)",
        "https://doi.org/10.1111/j.1945-5100.1990.tb00717.x",
        "Bulk chemical analyses of stony and iron meteorites",
        "meteorite bulk chemistry",
    ),
    "wasson_1988": InteriorReference(
        "Wasson & Kallemeyn 1988 (Phil. Trans. R. Soc. A 325)",
        "https://doi.org/10.1098/rsta.1988.0066",
        "Chondrite compositions — carbonaceous water and carbon contents",
        "chondrite water & carbon",
    ),
}
