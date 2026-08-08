"""Citable sources behind the spacecraft catalogue, for the /credits page.

Same shape as the atmosphere and interior registries: one entry per work a
number actually comes from, keyed by the `source` strings on each `Measured`.
Per-value provenance stays as comments next to the constants.

Two of these are compilations rather than primary works — Jonathan McDowell's
catalogue and Girija's C3 dataset — and they are here because for their fields
there is no primary source to prefer. Nobody publishes a spacecraft's dry mass
next to its launch mass in the same document, and the launch-vehicle curves
have only ever been public through a NASA query page that no longer answers.
"""

from typing import NamedTuple


class SpacecraftReference(NamedTuple):
    title: str
    url: str
    contribution: str
    # Two or three words for a panel credit line, in the style of the other
    # registries' notes.
    note: str = ""


SPACECRAFT_SOURCES: dict[str, SpacecraftReference] = {
    # --- compilations ------------------------------------------------------
    "gcat_satcat": SpacecraftReference(
        "McDowell, General Catalog of Artificial Space Objects (satcat)",
        "https://planet4589.org/space/gcat/web/cat/index.html",
        "Launch and dry mass of every catalogued spacecraft, on one set of "
        "conventions, so the two subtract to a propellant load",
        "spacecraft masses",
    ),
    "gcat_engines": SpacecraftReference(
        "McDowell, General Catalog of Artificial Space Objects (engines)",
        "https://planet4589.org/space/gcat/web/lvs/index.html",
        "Thrust, specific impulse and propellants per rocket engine",
        "engine performance",
    ),
    "girija_2023": SpacecraftReference(
        "Girija 2023, Launch Vehicle High-Energy Performance Dataset",
        "https://doi.org/10.48550/arXiv.2310.05994",
        "Payload-against-C3 curves for the interplanetary launchers, "
        "digitised from NASA's Launch Services Program performance site, plus "
        "the per-launch price comparison",
        "launch performance",
    ),
    # --- launch vehicles ---------------------------------------------------
    "sls_mpg_2018": SpacecraftReference(
        "NASA 2018, Space Launch System Mission Planner's Guide (ESD 30000 Rev A)",
        "https://explorers.larc.nasa.gov/2019APSMEX/MO/pdf_files/SLS%20mission%20planners%20guide%202018-12-19.pdf",
        "Table 4-1, useful payload system mass to Earth escape for SLS Block "
        "1, 1B and 2",
        "SLS escape performance",
    ),
    "ula_vulcan_2023": SpacecraftReference(
        "United Launch Alliance 2023, Vulcan Launch Systems User's Guide",
        "https://www.ulalaunch.com/docs/default-source/rockets/2023_vulcan_user_guide.pdf",
        "Vulcan Centaur performance to trans-lunar injection and to a C3 of "
        "20 km²/s², used to check the digitised curve",
        "Vulcan performance",
    ),
    "nasa_oig_2021": SpacecraftReference(
        "NASA Office of Inspector General 2021, NASA's Management of the "
        "Artemis Missions (IG-22-003)",
        "https://oig.nasa.gov/docs/IG-22-003.pdf",
        "Production and operating cost of one SLS and one Orion per Artemis flight",
        "SLS & Orion cost",
    ),
    "nasa_lsp_lucy_2019": SpacecraftReference(
        "NASA 2019, NASA Awards Launch Services Contract for Lucy Mission",
        "https://www.nasa.gov/news-release/nasa-awards-launch-services-contract-for-lucy-mission/",
        "Price NASA paid for an Atlas V 401 launch",
        "Atlas V 401 price",
    ),
    "nasa_lsp_clipper_2021": SpacecraftReference(
        "NASA 2021, NASA Awards Launch Services Contract for the Europa "
        "Clipper Mission",
        "https://www.nasa.gov/news-release/nasa-awards-launch-services-contract-for-the-europa-clipper-mission/",
        "Price NASA paid for a Falcon Heavy launch, fully expended",
        "Falcon Heavy price",
    ),
    # --- individual spacecraft --------------------------------------------
    "apollo_11_press_kit": SpacecraftReference(
        "NASA 1969, Apollo 11 Press Kit (release 69-83K)",
        "https://web.archive.org/web/20041118030740/http://history.nasa.gov/alsj/a11/A11_PressKit.pdf",
        "Command, service and lunar module launch weights, the lunar module's "
        "stage-by-stage propellant breakdown, and service propulsion system "
        "thrust",
        "Apollo masses",
    ),
    "nasa_orion_reference_2022": SpacecraftReference(
        "NASA 2022, Orion Reference Guide",
        "https://www.nasa.gov/wp-content/uploads/2023/02/orion-reference-guide-111022.pdf",
        "Orion's usable propellant, trans-lunar injection mass, crew size, "
        "mission duration and atmospheric entry speed",
        "Orion spacecraft",
    ),
    "nasa_psyche_spacecraft": SpacecraftReference(
        "NASA, Psyche Spacecraft",
        "https://science.nasa.gov/mission/psyche/spacecraft/",
        "Psyche's launch mass, xenon load, thruster count and thrust, and "
        "solar array output at 1 AU and at the asteroid",
        "Psyche spacecraft",
    ),
    "snyder_2019_psyche_ep": SpacecraftReference(
        "Snyder et al. 2019, Electric Propulsion for the Psyche Mission "
        "(IEPC-2019-244)",
        "https://electricrocket.org/2019/244.pdf",
        "SPT-140 Hall thruster specific impulse at its nominal operating point",
        "SPT-140 performance",
    ),
    "rayman_2006_dawn": SpacecraftReference(
        "Rayman, Fraschetti, Raymond & Russell 2006, Dawn: A mission in "
        "development for exploration of main belt asteroids Vesta and Ceres "
        "(Acta Astronautica 58)",
        "https://doi.org/10.1016/j.actaastro.2006.01.014",
        "Dawn's NSTAR ion propulsion system: xenon load, thrust and specific "
        "impulse range",
        "Dawn ion propulsion",
    ),
    # --- fiction -----------------------------------------------------------
    # Cited the same way as everything else, because the alternative is a
    # number with no provenance at all. What a novel states about its own ship
    # is the primary source for that ship.
    "corey_2011_leviathan_wakes": SpacecraftReference(
        "Corey 2011, Leviathan Wakes (The Expanse)",
        "https://www.wikidata.org/wiki/Q6535598",
        "The Rocinante's Epstein drive as a constant-acceleration drive, and "
        "the one-third-gravity cruise the crew fly it at",
        "The Expanse",
    ),
    "weir_2021_project_hail_mary": SpacecraftReference(
        "Weir 2021, Project Hail Mary",
        "https://www.wikidata.org/wiki/Q106852836",
        "The Hail Mary's astrophage spin drive acceleration and its crew of three",
        "Project Hail Mary",
    ),
    "weir_2011_the_martian": SpacecraftReference(
        "Weir 2011, The Martian",
        "https://www.wikidata.org/wiki/Q17111624",
        "The Hermes's constant ion acceleration and its crew of six",
        "The Martian",
    ),
    "reynolds_2000_revelation_space": SpacecraftReference(
        "Reynolds 2000, Revelation Space",
        "https://www.wikidata.org/wiki/Q1759977",
        "Lighthugger cruise: one gravity held until the ship is close to the "
        "speed of light",
        "Revelation Space",
    ),
    # Lucasfilm's own databank entry for the Falcon publishes one number, its
    # length. The film is what backs the two who fly it; the six they carry
    # are the capacity every reference work repeats and none of them sources.
    "lucas_1977_star_wars": SpacecraftReference(
        "Lucas 1977, Star Wars: Episode IV – A New Hope",
        "https://www.wikidata.org/wiki/Q17738",
        "The Millennium Falcon's complement of two crew and six passengers",
        "Star Wars",
    ),
    "clarke_1968_2001": SpacecraftReference(
        "Clarke 1968, 2001: A Space Odyssey",
        "https://www.wikidata.org/wiki/Q835341",
        "Discovery One's nuclear plasma drive and its crew of five, three of "
        "them in hibernation",
        "2001: A Space Odyssey",
    ),
}
