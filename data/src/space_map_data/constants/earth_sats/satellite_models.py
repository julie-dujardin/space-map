"""
Catalog of satellite buses / spacecraft platforms, for grouping satellites by
the hardware they fly and locating a 3D model.

Membership comes from GCAT: ``satcat.tsv`` states a Bus per catalogued object,
so a bus here is a set of GCAT bus strings rather than a list of satellites.
GCAT splits sub-variants that read as one platform to a reader (16 strings for
SSL-1300, 9 for Eurostar-3000), which is what ``gcat_buses`` folds back
together. What GCAT does not carry is a Wikidata entity per bus, and that plus
the display name is what this file exists for.

``norad_ids`` is the escape hatch, for the two cases GCAT's Bus column cannot
express: a generation split GCAT files under one platform lineage (GPS Block
IIR vs IIR-M are both "Series 4000"), and the rare object GCAT has wrong.
"""

from dataclasses import dataclass

from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_BY_SLUG,
    ManufacturerSpec,
)

# Group slug namespace: bus group slugs are ``f"{BUS_SLUG_PREFIX}{bus.slug}"`` so
# they don't collide with bare constellation slugs.
BUS_SLUG_PREFIX = "bus-"


@dataclass(frozen=True)
class SatelliteBusSpec:
    slug: str
    wikidata_qid: str | None
    manufacturer: ManufacturerSpec
    # First entry is the display name wherever Wikidata has no label for the
    # bus, so it must be the canonical form even when that repeats the slug.
    also_known_as: tuple[str, ...] = ()
    first_launch: str | None = None
    mass_kg_range: tuple[int, int] | None = None
    solar_span_m: float | None = None
    # GCAT satcat.tsv Bus strings that resolve to this bus.
    gcat_buses: tuple[str, ...] = ()
    # NORAD ids that take this bus whatever GCAT's Bus column says.
    norad_ids: tuple[int, ...] = ()
    model_url: str | None = None
    model_format: str | None = None
    model_license: str | None = None
    # Model bundle slug (EXPORT_DIR/v1/models/) applied to every satellite on the
    # bus, as a post-pass after explicit per-mission assignments win first.
    model_slug: str | None = None
    # NORAD ids that keep the bus membership but not its mesh, because the bus
    # model reads as the wrong spacecraft for them.
    model_excludes: tuple[int, ...] = ()
    notes: str | None = None


# AI disclosure: deep research, then every QID checked against Wikidata and
# every gcat_buses string against GCAT's own catalogue. A bus with no member in
# GCAT keeps an empty gcat_buses (not launched, or GCAT files its members under
# a string this file does not claim).
SATELLITE_BUSES: tuple[SatelliteBusSpec, ...] = (
    # ---------- Hughes / Boeing (spin-stabilized drums, then 3-axis) ----------
    SatelliteBusSpec(
        slug="hs-333",
        wikidata_qid="Q5635829",
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("Hughes 333",),
        first_launch="1972",
        mass_kg_range=(146, 574),
        gcat_buses=("HS-333",),
        notes="Spin-stabilized cylinder, 1.8 m dia x 3.3 m, 300 W, 12 C-band channels. "
        "First commercial GEO commsat series; retired 1979.",
    ),
    SatelliteBusSpec(
        slug="hs-376",
        wikidata_qid="Q10293459",
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("BSS-376", "Boeing 376", "Hughes 376"),
        first_launch="1980",
        mass_kg_range=(540, 1757),
        solar_span_m=8.0,
        gcat_buses=(
            "HS-376",
            "HS-376HP",
            "HS-376L",
            "HS-376W",
            "HS-383",
            "HS-389?",
        ),
        notes="Spin-stabilized telescoping dual-cylinder drum, 2.16 m dia stowed / 6.6-8 m deployed. "
        "58 built 1980-2003. Variants: base, L (long-life), HP (high-power), W (wide). "
        "No free Sketchfab model found.",
    ),
    SatelliteBusSpec(
        slug="hs-381",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("HS-381", "Leasat bus", "Syncom IV bus"),
        first_launch="1984",
        mass_kg_range=(1315, 3400),
        gcat_buses=("HS-381",),
        notes="Wide-body spin-stabilized cylinder, 4.26 m dia x 4.29 m stowed. "
        "Shuttle payload-bay only; 'Frisbee' deployment. Covered under Q545738 (Syncom).",
    ),
    SatelliteBusSpec(
        slug="hs-393",
        wikidata_qid="Q28446578",
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("Hughes 393", "Boeing 393"),
        first_launch="1989",
        mass_kg_range=(1346, 2500),
        solar_span_m=10.0,
        gcat_buses=("HS-393",),
        notes="Scaled-up HS-376; spin-stabilized telescoping drum, 3.7 m dia x 10 m deployed. "
        "Only 3 satellites built.",
    ),
    SatelliteBusSpec(
        slug="intelsat-vi",
        wikidata_qid="Q6044256",
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("HS-389", "Intelsat VI bus"),
        first_launch="1989",
        mass_kg_range=(4215, 4296),
        solar_span_m=11.7,
        gcat_buses=("HS-389",),
        notes="Spin-stabilized wide-body, 3.6 m dia x 5.2 m stowed / 11.7 m deployed. "
        "Intelsat 603 famously rescued by STS-49 (1992).",
    ),
    SatelliteBusSpec(
        slug="boeing-601",
        wikidata_qid="Q16632420",
        manufacturer=MANUFACTURER_BY_SLUG["boeing"],
        also_known_as=("HS-601", "BSS-601", "Hughes 601", "601HP", "601M"),
        first_launch="1992",
        mass_kg_range=(1700, 3900),
        solar_span_m=26.0,
        gcat_buses=(
            "BSS-601HP",
            "HS-601",
            "HS-601HP",
            "HS-601M",
            "Star 63",
        ),
        model_url="https://nasa3d.arc.nasa.gov/detail/eoss-tdrs",
        model_format="glTF",
        model_license="NASA Public Domain",
        model_slug="tracking-and-data-relay-satellites-tdrs-a",
        notes="First Hughes 3-axis-stabilized commsat; modular propulsion+payload boxes. "
        "76 launched 1992-2017. NASA 3D Resources TDRS model represents the 601HP variant. "
        "Sketchfab mirror: sketchfab.com/3d-models/tracking-and-data-relay-satellite-3d-printable-ae3ac90c4eff404bbe914838d7b5f29b",
    ),
    SatelliteBusSpec(
        slug="boeing-702",
        wikidata_qid="Q890161",
        manufacturer=MANUFACTURER_BY_SLUG["boeing"],
        also_known_as=(
            "HS-702",
            "BSS-702",
            "702HP",
            "702MP",
            "702SP",
            "702X",
            "BSS-GEM",
        ),
        first_launch="1999",
        mass_kg_range=(1500, 6100),
        solar_span_m=40.0,
        gcat_buses=(
            "702X",
            "BSS-702HP",
            "BSS-702MP",
            "BSS-702MP+",
            "BSS-702SP",
            "HS-702",
            "HS-GEM",
        ),
        notes="3-axis box bus, power 3-18 kW in sub-models. 702HP originally had concentrator "
        "solar troughs (later replaced by conventional GaAs). 702SP is all-electric. "
        "Paid CGTrader INMARSAT 5-F4 model exists (not free).",
    ),
    # ---------- Lockheed Martin ----------
    # ---------- GPS / NAVSTAR blocks (one bus per generation) ----------
    # Numbers keyed off the USA/OPS designator, not the NAVSTAR ordinal.
    # GPS III (NAVSTAR 77+) rides the Lockheed a2100 bus below.
    SatelliteBusSpec(
        slug="gps-block-i",
        wikidata_qid="Q121831552",
        manufacturer=MANUFACTURER_BY_SLUG["rockwell"],
        also_known_as=("Navstar Block I", "GPS Block 1"),
        first_launch="1978",
        gcat_buses=("GPS",),
    ),
    SatelliteBusSpec(
        slug="gps-block-ii",
        wikidata_qid="Q121831554",
        manufacturer=MANUFACTURER_BY_SLUG["rockwell"],
        also_known_as=("Navstar Block II", "GPS Block 2"),
        first_launch="1989",
        gcat_buses=("GPS II",),
    ),
    SatelliteBusSpec(
        slug="gps-block-iia",
        wikidata_qid="Q121831557",
        manufacturer=MANUFACTURER_BY_SLUG["rockwell"],
        also_known_as=("Navstar Block IIA", "GPS Block 2A"),
        first_launch="1990",
        # NAVSTAR 44 (USA-135 = IIA-19) is the last IIA, launched after the first IIR.
        gcat_buses=("GPS IIA",),
        # GCAT files these under GPS, GPS II, which is the platform lineage
        # rather than the generation shown here.
        norad_ids=(
            20830,
            22231,
            22275,
            22446,
            22581,
            22657,
            22700,
            22779,
            22877,
            23027,
            23833,
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iir",
        wikidata_qid="Q121831559",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=("Navstar Block IIR", "GPS Block 2R"),
        first_launch="1997",
        # NAVSTAR 43 (USA-132 = IIR-2) is the first successful IIR.
        gcat_buses=(
            "GPS IIR",
            "Series 4000",
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iir-m",
        wikidata_qid="Q121831561",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=("GPS Block IIRM", "Navstar Block IIR-M", "GPS Block 2R-M"),
        first_launch="2005",
        gcat_buses=(),
        # GCAT files these under Series 4000, which is the platform lineage
        # rather than the generation shown here.
        norad_ids=(28874, 29486, 29601, 32260, 32384, 32711, 34661, 35752),
    ),
    SatelliteBusSpec(
        slug="gps-block-iif",
        wikidata_qid="Q5514327",
        manufacturer=MANUFACTURER_BY_SLUG["boeing"],
        also_known_as=("Navstar-2F", "GPS Block 2F", "GPS IIF"),
        first_launch="2010",
        gcat_buses=("GPS IIF",),
    ),
    SatelliteBusSpec(
        slug="a2100",
        wikidata_qid="Q279910",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=(
            "AS 2100",
            "A2100A",
            "A2100AX",
            "A2100AXS",
            "A2100M",
            "LM 2100",
            "LM2100",
            "LM2100 Combat Bus",
        ),
        first_launch="1996-09-08",
        mass_kg_range=(2015, 4692),
        gcat_buses=(
            "A2100",
            "A2100A",
            "A2100AX",
            "A2100AXS",
            "A2100AXX",
            "A2100M",
            "A2100TR",
        ),
        model_url="https://www.goes-r.gov/3dModelAR/",
        model_format="glTF",
        model_license="NOAA/NASA (public domain, attribution)",
        notes="3-axis stabilized GEO bus. NOAA GOES-R official 3D model and AR viewer available. "
        "GPS III community model: sketchfab.com/3d-models/space-gps-iii-06ae91c2d22c4a69a43d9a655a31de42",
    ),
    SatelliteBusSpec(
        slug="lm-700",
        wikidata_qid="Q6459000",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=("LM-700", "LM 700", "LM-700A", "LM-700B", "Iridium bus"),
        first_launch="1997-05-05",
        mass_kg_range=(680, 689),
        gcat_buses=("LM700",),
        notes="Original Iridium constellation block-1 bus. 95 launched 1997-2002. "
        "Iridium-NEXT (2017+) uses Thales ELiTeBus, not LM-700. "
        "Physical engineering model on display at Smithsonian NASM.",
    ),
    SatelliteBusSpec(
        slug="elitebus1000",
        wikidata_qid="Q125698667",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=("ELiTeBus-1000",),
        first_launch="2010-10-19",
        gcat_buses=(
            "EliteBus",
            "Prisma?",
        ),
        notes="Also see:"
        "Krebs, Gunter D. &ldquo;Thales Alenia: ELiTeBus-1000&rdquo;. Gunter's Space Page."
        "Retrieved April 19, 2026, from https://space.skyrocket.de/doc_sat/thales-alenia_elite.htm",
    ),
    # ---------- SSL / Loral / Lanteris ----------
    SatelliteBusSpec(
        slug="ssl-1300",
        wikidata_qid="Q4364714",
        manufacturer=MANUFACTURER_BY_SLUG["ssl"],
        also_known_as=(
            "LS-1300",
            "FS-1300",
            "Loral 1300",
            "SSL-1300",
            "Maxar 1300",
            "Lanteris 1300",
            "1300-Class Platform",
        ),
        first_launch="1989-06-05",
        mass_kg_range=(2500, 6700),
        solar_span_m=40.0,
        gcat_buses=(
            "FS-1300",
            "FS-1300HL",
            "FS-1300O",
            "LS-1300",
            "LS-1300-140",
            "LS-1300-O",
            "LS-1300LL",
            "LS-1300S",
            "SSL-1300",
            "SSL-1300-O",
            "SSL-1300E",
            "SSL-1300HL",
            "SSL-1300LL",
            "SSL-1300S",
            "SSL-1300SX",
            "SSL-1300X",
        ),
        model_url="https://science.nasa.gov/3d-resources/space-systems-loral-ssl-1300/",
        model_format="glTF/OBJ",
        model_license="NASA Public Domain",
        model_slug="space-systems-loral-ssl-1300",
        # Psyche flies the 1300 chassis, but the mesh is a GEO commsat with a
        # comms dish; on a deep-space probe that reads as the wrong craft.
        # GOES-I/M are SS/L-built on a bespoke single-wing weather-satellite
        # chassis, so the symmetric two-wing commsat mesh is the wrong shape.
        model_excludes=(23051, 23581, 24786, 26352, 26871, 58049),
        notes="3-axis box + two solar wings, GEO. First Western commsat with electric propulsion "
        "(MBSat 2004). Rebranded Lanteris 1300 Oct 2025 after Intuitive Machines acquisition. "
        "Sketchfab community model: sketchfab.com/3d-models/loral-ssl-1300-satellite-b3fddca0b88346cfad87b2bb0700549f",
    ),
    SatelliteBusSpec(
        slug="ls-400",
        wikidata_qid="Q141114164",
        manufacturer=MANUFACTURER_BY_SLUG["ssl"],
        also_known_as=("LS-400",),
        first_launch="1998-02-14",
        mass_kg_range=(450, 450),
        solar_span_m=12.0,
        # M001-M072 is the whole first generation; 12 of them were lost on the
        # 1998 Zenit-2 failure and never cataloged.
        gcat_buses=("LS-400",),
        notes="Trapezoidal LEO bus with two solar wings, payload by Alenia Spazio. "
        "Globalstar's second generation (M073 onward) is the Thales ELiTeBus-1000.",
    ),
    # ---------- Orbital Sciences / Orbital ATK / Northrop Grumman (STAR family) ----------
    SatelliteBusSpec(
        slug="star-bus",
        wikidata_qid="Q1131474",
        manufacturer=MANUFACTURER_BY_SLUG["northrop-grumman"],
        also_known_as=("Star-1", "Star-2", "STARBus", "STAR Bus family"),
        first_launch="1997-11-12",
        gcat_buses=("OSC Star 1",),
        notes="Parent family umbrella; see GEOStar/LEOStar/MicroStar for variants. "
        "These 4 are STAR-1 craft (CTA heritage); Q1131474 is the umbrella Star Bus item. "
        "Originally CTA Space Systems, acquired by Orbital Sciences 1997.",
    ),
    SatelliteBusSpec(
        slug="geostar-1",
        wikidata_qid="Q96378941",
        manufacturer=MANUFACTURER_BY_SLUG["orbital-sciences"],
        also_known_as=("Aquila",),
        first_launch="2006-06-21",
        gcat_buses=(
            "GeoStar-1",
            "OSC-Micro",
        ),
        notes="Small sub-5 kW GEO bus, primarily US government/military (MiTEx-A, GSSAP).",
    ),
    SatelliteBusSpec(
        slug="geostar-2",
        wikidata_qid="Q17083126",
        manufacturer=MANUFACTURER_BY_SLUG["orbital-sciences"],
        also_known_as=("STAR-2", "Star-2 bus", "GEOStar-2.4"),
        first_launch="2002-07-05",
        mass_kg_range=(1500, 3500),
        gcat_buses=(
            "GeoStar 2",
            "Geostar-2",
            "Geostar-2.4E",
            "OSC Star 2",
            "OSC Star 2.4",
            "OSC Star 2.4e",
            "Star 2",
            "Star-2.3",
            "Star-2.3?",
            "Star-2.4",
            "Star-2.4E",
        ),
        notes="Modular rectangular body with central composite thrust cylinder, 2 articulated "
        "solar wings, payload up to 5.5 kW; 15-18 yr design life.",
    ),
    SatelliteBusSpec(
        slug="geostar-3",
        wikidata_qid="Q96378944",
        manufacturer=MANUFACTURER_BY_SLUG["northrop-grumman"],
        also_known_as=("Star-3",),
        first_launch="2018-01-25",
        mass_kg_range=(3500, 4500),
        gcat_buses=("Geostar-3",),
        notes="Evolutionary growth of GEOStar-2 with larger solar arrays and hybrid propulsion option. "
        "Supports dual-launch stacking (MEV/MRV, Galaxy 33+34).",
    ),
    SatelliteBusSpec(
        slug="leostar",
        wikidata_qid=None,  # No dedicated item for the umbrella; Q133286575 covers only LEOStar-3
        manufacturer=MANUFACTURER_BY_SLUG["orbital-sciences"],
        also_known_as=("LEOStar", "LEOStar-1", "LEOStar-2", "LEOStar-3"),
        first_launch="2003",  # OrbView-4 (2001) was the first LEOStar flight but failed to orbit
        mass_kg_range=(300, 4000),
        gcat_buses=(
            "LeoStar-2",
            "Leostar-2",
            "Leostar-2/750",
            "Leostar-3",
            "SA-200",
            "SA-200S",
        ),
        notes="NASA SMEx/Earth-science LEO platform. LEOStar-2 hexagonal prism; LEOStar-3 is 4,000 kg class. "
        "No standalone English Wikipedia article (covered under Star Bus). "
        "Pruned: RXTE (GSFC bus), SeaStar (PegaStar), DART (HAPS), NOAA-20 (Ball BCP-2000).",
    ),
    SatelliteBusSpec(
        slug="microstar",
        wikidata_qid=None,  # No dedicated item; Q1131474 is the umbrella Star Bus, not MicroStar
        manufacturer=MANUFACTURER_BY_SLUG["orbital-sciences"],
        also_known_as=("Microstar", "MicroStar-1", "MicroStar-2"),
        first_launch="1995-04-03",  # Orbcomm FM01/FM02 (Orbcomm-X 1991 prototype predates the bus)
        mass_kg_range=(43, 68),
        solar_span_m=2.2,
        gcat_buses=(
            "Microstar",
            "Sterkh",
        ),
        notes="Flat disk stowed (~1 m dia x 16 cm), deploys butterfly. First Orbcomm LEO constellation. "
        "No dedicated Wikidata/enwiki bus article. IBEX is the MicroStar-2 variant. "
        "Orbcomm-X (1991 prototype) and the OG2/Sterkh sats are different buses (excluded).",
    ),
    # ---------- Thales Alenia Space (Spacebus family + PRIMA + Proteus) ----------
    SatelliteBusSpec(
        slug="spacebus",
        wikidata_qid="Q2091683",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=("Spacebus family", "Eurosatellite Spacebus"),
        first_launch="1985-02-08",
        notes="Umbrella family: Spacebus-100/300/2000/3000/4000 + Neo. 92+ built. "
        "See subtype entries for details.",
    ),
    SatelliteBusSpec(
        slug="spacebus-100",
        wikidata_qid="Q125680103",  # Spacebus-1000 (no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["aerospatiale"],
        also_known_as=("Spacebus 1000", "Eurosatellite Spacebus 100"),
        first_launch="1985-02-08",
        mass_kg_range=(1170, 1500),
        solar_span_m=21.0,
        gcat_buses=("Spacebus 100",),  # Arabsat-1C sold to India
        notes="Franco-German Eurosatellite consortium (Aerospatiale + MBB).",
    ),
    SatelliteBusSpec(
        slug="spacebus-300",
        wikidata_qid="Q125680104",  # Spacebus-300 (no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["aerospatiale"],
        also_known_as=("SB-300",),
        first_launch="1987-11-21",
        mass_kg_range=(2077, 2144),
        gcat_buses=("Spacebus 300",),
        notes="Eurosatellite DBS bus for TV-Sat/TDF/Tele-X programs.",
    ),
    SatelliteBusSpec(
        slug="spacebus-2000",
        wikidata_qid="Q125680105",  # Spacebus-2000 (no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["aerospatiale"],
        also_known_as=("Spacebus-2000",),
        first_launch="1990-08-30",
        mass_kg_range=(1800, 2500),
        solar_span_m=22.4,
        gcat_buses=("Spacebus 2000",),
    ),
    SatelliteBusSpec(
        slug="spacebus-3000",
        wikidata_qid="Q2091683",
        manufacturer=MANUFACTURER_BY_SLUG["alcatel-space"],
        also_known_as=(
            "Spacebus 3000A",
            "Spacebus 3000B2",
            "Spacebus 3000B3",
            "Spacebus 3000B3S",
        ),
        first_launch="1996-07-09",
        mass_kg_range=(2000, 6000),
        gcat_buses=(
            "Spacebus 3000",
            "Spacebus 3000A",
            "Spacebus 3000B2",
            "Spacebus 3000B3",
            "Spacebus 3000B3S",
        ),
        notes="5-16 kW power, 50 V bus + Ni-H2 batteries. "
        "Spans sub-variants 3000A/B2/B3/B3S (distinct Wikidata items exist); Q2091683 is the umbrella.",
    ),
    SatelliteBusSpec(
        slug="spacebus-4000",
        wikidata_qid="Q2091683",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=(
            "Spacebus 4000B2",
            "Spacebus 4000B3",
            "Spacebus 4000C1",
            "Spacebus 4000C2",
            "Spacebus 4000C3",
            "Spacebus 4000C4",
        ),
        first_launch="2005-02-03",
        mass_kg_range=(3000, 5900),
        gcat_buses=(
            "Spacebus 4000B2",
            "Spacebus 4000B3",
            "Spacebus 4000C1",
            "Spacebus 4000C2",
            "Spacebus 4000C3",
            "Spacebus 4000C4",
        ),
        # GCAT files these under Ekspress-2000?, which is the platform lineage
        # rather than the generation shown here.
        norad_ids=(44307,),
        notes="100 V bus, Li-ion batteries, integrated OBC; first GEO platform with in-GEO star tracker. "
        "Spans 4000B2/B3/C1-C4 sub-variants (distinct Wikidata items exist); Q2091683 is the umbrella.",
    ),
    SatelliteBusSpec(
        slug="spacebus-neo",
        wikidata_qid="Q21711928",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=(
            "Spacebus Neo",
            "Spacebus-Neo-100",
            "Spacebus-Neo-200",
            "SB-Neo",
        ),
        first_launch="2020-01-16",
        mass_kg_range=(3600, 6500),
        gcat_buses=(
            "Spacebus NEO100",
            "Spacebus NEO200",
        ),
        notes="All-electric / flexible-propulsion GEO telecom platform (ESA/CNES Neosat), up to ~20 kW. "
        "Sub-variants Neo-100 (Q125680118) / Neo-200 (Q125698171).",
    ),
    SatelliteBusSpec(
        slug="prima",
        wikidata_qid="Q125698747",  # PRIMA (Alenia Spazio / Thales Alenia Space; no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=("Piattaforma Riconfigurabile Italiana Multi-Applicativa",),
        first_launch="2007-06-08",
        gcat_buses=(
            "PRIMA",
            "Prima",
        ),
        notes="Italian modular LEO/MEO/GEO platform (Service+Propulsion+Payload modules). "
        "Pointing accuracy 0.025 deg. Also proposed for NASA Rapid IV (with ELiTeBUS).",
    ),
    SatelliteBusSpec(
        slug="proteus",
        wikidata_qid="Q1127075",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        also_known_as=("PROTEUS", "Astrosat-1000 (commonly conflated)"),
        first_launch="2001-12-07",
        mass_kg_range=(500, 700),
        gcat_buses=("Proteus",),
        notes="CNES + Thales Alenia Space LEO mini-sat platform. Technically outside the "
        "English Wikipedia 'Category:Satellite buses' but has its own article "
        "Proteus_(satellite). Different platform from Airbus Astrosat-1000.",
    ),
    # ---------- Airbus Defence and Space (Eurostar family + Astrosat) ----------
    SatelliteBusSpec(
        slug="eurostar",
        wikidata_qid="Q3060865",
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=(
            "Eurostar 1000",
            "Eurostar 2000",
            "Eurostar 2000+",
            "Eurostar Neo",
            "E-Neo",
        ),
        first_launch="1990-10",
        mass_kg_range=(1310, 6400),
        solar_span_m=45.0,
        gcat_buses=(
            "Eurostar 2000",
            "Eurostar 2000+",
        ),
        model_url="https://sketchfab.com/3d-models/communication-satellite-eurostar-3000-07f3c3573afe49fb8c8257af6e608eec",
        model_format="glTF",
        model_license="Sketchfab free / CC BY (elliptic studio)",
        notes="See also Eurostar E3000 (Q15122464) for high-power variant. "
        "Second Astra-livery model: sketchfab.com/3d-models/satellite-eurostar-3000-508d012ff339489aabb00034d3db1b52",
    ),
    SatelliteBusSpec(
        slug="eurostar-e3000",
        wikidata_qid="Q15122464",
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=("Eurostar 3000", "E3000", "E3000EOR", "E3000e"),
        first_launch="2004",
        mass_kg_range=(4500, 6400),
        solar_span_m=45.0,
        gcat_buses=(
            "Eurostar 3000",
            "Eurostar 3000e",
            "Eurostar 3000EOR",
            "Eurostar 3000GM",
            "Eurostar 3000LS",
            "Eurostar 3000LX",
            "Eurostar 3000M",
            "Eurostar 3000S",
            "Italsat 3000",
        ),
        model_url="https://sketchfab.com/3d-models/communication-satellite-eurostar-3000-07f3c3573afe49fb8c8257af6e608eec",
        model_format="glTF",
        model_license="Sketchfab free / CC BY (elliptic studio)",
        notes="First commercial bus with Li-ion batteries; 3D-printed TTC brackets (2015). "
        "E3000EOR adds Safran PPS5000 Hall thrusters for electric orbit raising.",
    ),
    SatelliteBusSpec(
        slug="astrosat-1000",
        wikidata_qid="Q4811708",
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=("AstroSat-1000",),
        first_launch="2011-12-17",
        mass_kg_range=(800, 1200),
        gcat_buses=("Astrosat-1000",),
        notes="Large option in Airbus Astrosat family; used for CNES Pleiades-HR. "
        "Not to be confused with Proteus (CNES/Thales).",
    ),
    SatelliteBusSpec(
        slug="alphabus",
        wikidata_qid="Q1359245",
        manufacturer=MANUFACTURER_BY_SLUG[
            "airbus-ds"
        ],  # joint with Thales Alenia Space (Q128356)
        also_known_as=("Alphabus Extended", "Alphasat platform"),
        first_launch="2013-07-25",
        mass_kg_range=(6000, 8800),
        gcat_buses=("AlphaBus",),  # sole Alphabus flight unit (= Inmarsat-4A F4)
        notes="Heavy GEO platform (12-18 kW payload) developed under ESA ARTES-8 with CNES. "
        "Pruned (wrong bus): Syracuse 4A (Spacebus-Neo-100), Syracuse 4B + Inmarsat-6 F1/F2 "
        "(Eurostar E3000), Eutelsat 10B (Spacebus-Neo-200). Spacebus-Neo has no catalog entry yet.",
    ),
    SatelliteBusSpec(
        slug="myriade",
        wikidata_qid="Q3331500",
        manufacturer=MANUFACTURER_BY_SLUG["cnes"],
        also_known_as=("AstroSat-100", "Myriade-Evolutions"),
        first_launch="2004-06-28",
        mass_kg_range=(120, 400),
        gcat_buses=(
            "AstroSat-100",
            "Myriade",
        ),
        notes="French ~125 kg microsat platform (CNES + Airbus). Myriade-Evolutions is 350-400 kg.",
    ),
    SatelliteBusSpec(
        slug="arrow",
        wikidata_qid=None,  # no Wikidata item for the platform
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=("Arrow", "Arrow 150", "Arrow 450"),
        first_launch="2019-02-27",
        mass_kg_range=(147, 150),
        solar_span_m=5.0,
        # OneWeb runs ONEWEB-0006..ONEWEB-0721 with gaps; Loft Orbital's YAM-8
        # onward fly the larger Arrow 450 from Airbus US.
        gcat_buses=("ARROW",),
        notes="Assembly-line LEO smallsat platform designed for OneWeb and built by "
        "OneWeb Satellites, the Airbus joint venture. The ~500 kg OneWeb Gen 2 is a "
        "different platform and is not covered here.",
    ),
    SatelliteBusSpec(
        slug="eurostar-neo",
        wikidata_qid="Q115406849",
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=("Eurostar-Neo", "Eurostar E3000neo", "Neosat"),
        first_launch="2022-10-15",
        mass_kg_range=(4476, 6100),
        solar_span_m=40.0,
        gcat_buses=("Eurostar NEO",),
        notes="ESA Neosat successor to Eurostar-3000: electric orbit raising, higher payload "
        "power. Listed ahead of ssl-1300 so SPAINSAT NG does not read as the 2006 Spainsat.",
    ),
    SatelliteBusSpec(
        slug="galileo-iov",
        wikidata_qid=None,  # the IOV platform was never marketed under a name
        manufacturer=MANUFACTURER_BY_SLUG["airbus-ds"],
        also_known_as=("Galileo IOV", "GalileoSat"),
        first_launch="2011-10-21",
        mass_kg_range=(700, 700),
        solar_span_m=14.5,
        gcat_buses=(),
        # GCAT files these under GalileoSat, which is the platform lineage
        # rather than the generation shown here.
        norad_ids=(37846, 37847, 38857, 38858),
        notes="Four-satellite Astrium GmbH design that validated Galileo in orbit; Thales "
        "Alenia integrated the payload. The FOC fleet that followed is OHB SmartMEO.",
    ),
    SatelliteBusSpec(
        slug="small-geo",
        wikidata_qid="Q48755064",
        manufacturer=MANUFACTURER_BY_SLUG["ohb"],
        also_known_as=("SGEO", "Luxor"),
        first_launch="2017-01-28",
        mass_kg_range=(1600, 3200),
        gcat_buses=(
            "Luxor",
            "SmallGEO",
        ),
        notes="German/ESA ARTES-11 3-ton GEO platform; classic, hybrid, or all-electric propulsion.",
    ),
    SatelliteBusSpec(
        slug="smartmeo",
        wikidata_qid="Q125660504",
        manufacturer=MANUFACTURER_BY_SLUG["ohb"],
        also_known_as=("SmartMEO",),
        first_launch="2014-08-22",
        mass_kg_range=(700, 800),
        solar_span_m=14.5,
        gcat_buses=(
            "Galileo",
            "GalileoSat",
        ),
        notes="OHB navigation platform carrying SSTL payloads; the whole Galileo FOC fleet. "
        "GSAT0201/0202 reached the wrong orbit on the 2014 Fregat anomaly and still broadcast.",
    ),
    # ---------- Asian buses (China / Japan / India / Korea) ----------
    SatelliteBusSpec(
        slug="dfh-3",
        wikidata_qid="Q97219471",
        manufacturer=MANUFACTURER_BY_SLUG["cast"],
        also_known_as=(
            "Dong Fang Hong 3",
            "\u4e1c\u65b9\u7ea2\u4e09\u53f7",
            "DFH-3A",
            "DFH-3B",
        ),
        first_launch="1994",
        mass_kg_range=(1100, 3800),
        solar_span_m=18.1,
        gcat_buses=(
            "DFH-3",
            "DFH-3B",
        ),
        notes="Box-shaped 3-axis GEO bus, MBB design assistance. 2-5.5 kW across A/B variants.",
    ),
    SatelliteBusSpec(
        slug="dfh-4",
        wikidata_qid="Q97219489",
        manufacturer=MANUFACTURER_BY_SLUG["cast"],
        also_known_as=(
            "Dong Fang Hong 4",
            "\u4e1c\u65b9\u7ea2\u56db\u53f7",
            "DFH-4S",
            "DFH-4E",
            "DFH-4SP",
        ),
        first_launch="2006-10-28",
        mass_kg_range=(4600, 5400),
        gcat_buses=(
            "DFH-3E",
            "DFH-4",
            "DFH-4?",
            "DFH-4E",
            "FY-4?",
            "YT-PKM",
        ),
        notes="10.5 kW solar, 8 kW payload, 15 yr life. DFH-4E adds electric propulsion; "
        "DFH-4S 'Small but Smart' uses plasma propulsion. Marketed via CGWIC.",
    ),
    SatelliteBusSpec(
        slug="dfh-5",
        wikidata_qid="Q97219511",
        manufacturer=MANUFACTURER_BY_SLUG["cast"],
        also_known_as=("Dong Fang Hong 5", "\u4e1c\u65b9\u7ea2\u4e94\u53f7"),
        first_launch="2019-12-27",
        mass_kg_range=(6500, 9000),
        gcat_buses=("DFH-5",),  # sole operational DFH-5 to date
        notes="Large 4th-gen GEO bus, 28 kW power, LIPS-300 electric propulsion, deployable radiators. "
        "Apstar-6D / ChinaSat 19 / ChinaSat 26 are DFH-4E (moved to dfh-4).",
    ),
    SatelliteBusSpec(
        slug="cast968",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["cast"],
        also_known_as=("CAST-968",),
        first_launch="1999-05-10",
        mass_kg_range=(300, 500),
        gcat_buses=(
            "CAST-968",
            "CAST-968?",
        ),
        notes="Small sun-synchronous LEO bus, 1.4 m x 1.1 m x 0.95 m, 250-1000 W.",
    ),
    SatelliteBusSpec(
        slug="cast2000",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["cast"],
        also_known_as=("CAST-2000",),
        first_launch="2003",
        mass_kg_range=(400, 900),
        gcat_buses=("CAST-2000",),
        notes="Minisat 3-axis platform, 1 kW BOL, LEO/MEO/HEO/formation flight.",
    ),
    SatelliteBusSpec(
        slug="ds2000",
        wikidata_qid="Q8353343",
        manufacturer=MANUFACTURER_BY_SLUG["mitsubishi-electric"],
        also_known_as=("DS-2000", "Melco DS2000"),
        first_launch="2002-09-10",
        mass_kg_range=(3000, 5000),
        solar_span_m=30.0,
        gcat_buses=("DS-2000",),
        notes="Carbon-fiber central cylinder, cuboid body, derived from DRTS/ETS-VIII.",
    ),
    SatelliteBusSpec(
        slug="nextar",
        wikidata_qid="Q11234905",
        manufacturer=MANUFACTURER_BY_SLUG["nec"],
        also_known_as=("NX-100L", "NX-300L", "NX-500L", "NX-1500L"),
        first_launch="2014-11-06",
        mass_kg_range=(250, 500),
        gcat_buses=("Nextar-300L",),  # ASNARO = ASNARO-1; LOTUSat-1 not yet launched
        notes="Modular small-sat bus (JAXA/USEF collaboration); SpaceWire + SpaceCube-2 computer.",
    ),
    SatelliteBusSpec(
        slug="i-1k",
        wikidata_qid="Q17028555",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-1000", "I-1000"),
        first_launch="2002-09-12",
        mass_kg_range=(500, 1100),
        gcat_buses=(
            "I1K",
            "IRS",
            "IRS?",
        ),
        notes="1.5 m cuboid. Hosts IRNSS/NavIC constellation, Mangalyaan, Chandrayaan-1, Aditya-L1.",
    ),
    SatelliteBusSpec(
        slug="i-2k",
        wikidata_qid="Q17038983",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-2000", "I-2000"),
        first_launch="2001-04-18",
        mass_kg_range=(1500, 2500),
        gcat_buses=(
            "I2K",
            "I4K?",
        ),
    ),
    SatelliteBusSpec(
        slug="i-3k",
        wikidata_qid="Q17028575",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-3000", "I-3000"),
        first_launch="2005-12-21",
        mass_kg_range=(3000, 3400),
        gcat_buses=("I3K",),
    ),
    SatelliteBusSpec(
        slug="i-4k",
        wikidata_qid="Q16991488",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-4000", "I-4000"),
        first_launch=None,
        gcat_buses=("I4K",),
        notes="In development. 4000-6500 kg class, 10-15 kW. Bus assignment varies; check NSIL.",
    ),
    SatelliteBusSpec(
        slug="i-6k",
        wikidata_qid="Q60760760",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-6000", "I-6000"),
        first_launch="2018-12-04",
        mass_kg_range=(4000, 6500),
        gcat_buses=("I6K",),
        notes="India's heaviest commsat bus, 15 kW DC.",
    ),
    SatelliteBusSpec(
        slug="ims",
        wikidata_qid="Q17056247",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("IMS", "IMS-1", "IMS-2"),
        first_launch="2008-04-28",
        mass_kg_range=(80, 450),
        gcat_buses=(
            "IMS-1",
            "IMS-2",
            "SSB-2",
        ),
        notes="Microsat (IMS-1 ~100 kg) and minisat (IMS-2 ~400 kg) variants. "
        "Pruned (RISAT bus, not IMS): RISAT-2B/2BR1/2BR2 (= EOS-01), EOS-04, Microsat-R.",
    ),
    SatelliteBusSpec(
        slug="insat-bus",
        wikidata_qid="Q136171554",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT bus family",),
        first_launch="2001-04-18",
        notes="Umbrella article covering I-1K through I-6K; see individual entries.",
    ),
    SatelliteBusSpec(
        slug="poem",
        wikidata_qid="Q121238986",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=(
            "POEM",
            "PS4-OP",
            "PSLV Stage 4 Orbital Platform",
            "PSLV Orbital Experiment Module",
        ),
        first_launch="2019-01-24",
        gcat_buses=("POEM",),
        notes="Repurposed PSLV 4th stage as short-duration orbital platform (~6 months). "
        "Hosts non-separable payloads on recent PSLV flights (POEM-1 = 2022, POEM-4 = 2024-12-30).",
    ),
    SatelliteBusSpec(
        slug="si-200",
        wikidata_qid="Q17125153",
        manufacturer=MANUFACTURER_BY_SLUG["satrec"],
        also_known_as=("SI-300 (extended)",),
        first_launch="2009-07-14",
        mass_kg_range=(180, 300),
        gcat_buses=(
            "Deimos-2",
            "Satrec",
            "SI-200",
            "SI-300",
        ),
        notes="Korean hexagonal Earth-observation bus, 1.2 m dia x 1.35 m high, 3-axis. "
        "DubaiSat-2 and Deimos-2 use the extended SI-300 variant.",
    ),
    # ---------- Russian buses ----------
    SatelliteBusSpec(
        slug="kaur",
        wikidata_qid="Q4206256",
        manufacturer=MANUFACTURER_BY_SLUG["iss-reshetnev"],
        also_known_as=(
            "\u041a\u0410\u0423\u0420",
            "KAUR-1",
            "KAUR-2",
            "KAUR-3",
            "KAUR-4",
            "KAUR-4N",
        ),
        first_launch="1965",
        mass_kg_range=(800, 2000),
        gcat_buses=(
            "Ekran",
            "Globus",
            "Globus?",
            "Gorizont",
            "KAUR-1",
            "KAUR-1 11F617",
            "KAUR-1 11F621",
            "KAUR-1 11F627",
            "KAUR-1 11F643",
            "KAUR-1 11F643N",
            "KAUR-1 11F666",
            "KAUR-1 17F118",
            "KAUR-1 17F118M",
            "KAUR-4",
            "KAUR-4 Al'tair",
            "KAUR-4N",
            "Molniya-1",
            "Molniya-1T",
            "Molniya-2",
            "Molniya-3",
            "Raduga",
        ),
        notes="Soviet 'Universal Spacecraft Series' - 4 generations spanning 1965-2009, 400+ built.",
    ),
    SatelliteBusSpec(
        slug="uragan",
        wikidata_qid="Q20744047",
        manufacturer=MANUFACTURER_BY_SLUG["iss-reshetnev"],
        also_known_as=("Uragan", "\u0423\u0440\u0430\u0433\u0430\u043d", "11F654"),
        first_launch="1982-10-12",
        mass_kg_range=(1300, 1450),
        solar_span_m=7.8,
        # satcat tags the generation in the name: "COSMOS NNNN [GLONASS]".
        gcat_buses=("Uragan",),
        notes="Pressurized cylinder with two wings, designed by NPO PM (now Reshetnev) and "
        "largely assembled by Polyot. First GLONASS generation; all retired by 2009.",
    ),
    SatelliteBusSpec(
        slug="uragan-m",
        wikidata_qid="Q4139977",
        manufacturer=MANUFACTURER_BY_SLUG["iss-reshetnev"],
        also_known_as=("Uragan-M", "GLONASS-M", "11F654M", "14F113"),
        first_launch="2001-12-01",
        mass_kg_range=(1415, 1450),
        solar_span_m=7.8,
        gcat_buses=(),
        # GCAT files these under Uragan, which is the platform lineage rather
        # than the generation shown here.
        norad_ids=(
            26987,
            28112,
            28509,
            28915,
            28916,
            29670,
            29671,
            29672,
            32275,
            32276,
            32277,
            32393,
            32394,
            32395,
            33378,
            33379,
            33380,
            33466,
            33467,
            33468,
            36111,
            36112,
            36113,
            36400,
            36401,
            36402,
            37137,
            37138,
            37139,
            37829,
            37867,
            37868,
            37869,
            37938,
            39155,
            39620,
            40001,
            41330,
            41554,
            42939,
            43508,
            43687,
            44299,
            44850,
            45358,
            54377,
        ),
        notes="Same pressurized platform as Uragan with more power and a longer life. "
        "GLONASS-K moved to the unpressurized Ekspress-1000K, and the two K2 prototypes "
        "flown so far use KAUR-4N.",
    ),
    SatelliteBusSpec(
        slug="usp",
        wikidata_qid="Q22084823",
        manufacturer=MANUFACTURER_BY_SLUG["energia"],
        also_known_as=("Universal Space Platform", "\u0423\u041a\u041f", "Viktoria"),
        first_launch="1999-09-06",
        gcat_buses=(
            "14F142 EKS",
            "Yamal",
            "Yamal 100",
        ),
        notes="3-axis unpressurized LEO-to-GEO platform; SPT-70 electric thrusters for stationkeeping.",
    ),
    SatelliteBusSpec(
        slug="yakhta",
        wikidata_qid="Q4539748",
        manufacturer=MANUFACTURER_BY_SLUG["khrunichev"],
        also_known_as=("\u042f\u0445\u0442\u0430",),
        first_launch="2005-08-26",
        mass_kg_range=(700, 1380),
        gcat_buses=(
            "Briz",
            "Kazsat",
            "Yachta",
            "Yakhta",
        ),
        notes="Small 3-axis bus; proposed for RAMOS.",
    ),
    SatelliteBusSpec(
        slug="ekspress",
        wikidata_qid="Q4530647",
        manufacturer=MANUFACTURER_BY_SLUG["iss-reshetnev"],
        also_known_as=(
            "\u042d\u043a\u0441\u043f\u0440\u0435\u0441\u0441",
            "Ekspress-1000",
            "Ekspress-1000K",
            "Ekspress-1000H",
            "Ekspress-1000HT",
            "Ekspress-1000HTA",
            "Ekspress-2000",
            "Ekspress-4000",
        ),
        first_launch="2011-02-26",
        mass_kg_range=(1200, 3500),
        gcat_buses=(
            "Ekspress",
            "Ekspress-1000",
            "Ekspress-1000H",
            "Ekspress-1000HTB",
            "Ekspress-1000K",
            "Ekspress-1000N",
            "Ekspress-2000",
            "Ekspress-2000?",
        ),
        notes="Modern 3-axis GEO/MEO platform replacing older MSS-2500/KAUR. Li-ion, "
        "electric or chemical propulsion. Category contains 21 pages.",
    ),
    SatelliteBusSpec(
        slug="navigator",
        wikidata_qid="Q67944760",
        manufacturer=MANUFACTURER_BY_SLUG["npo-lavochkin"],
        also_known_as=(
            "\u041d\u0430\u0432\u0438\u0433\u0430\u0442\u043e\u0440",
            "BMSS Navigator",
        ),
        first_launch="2011-01-20",
        mass_kg_range=(850, 3500),
        gcat_buses=("Navigator",),
        notes="Lavochkin modular service module for meteorology and deep space (RadioAstron, Spektr-RG).",
    ),
    SatelliteBusSpec(
        slug="yamal",
        wikidata_qid="Q3656794",
        manufacturer=MANUFACTURER_BY_SLUG["energia"],
        also_known_as=("\u042f\u043c\u0430\u043b",),
        first_launch="1999-09-06",
        gcat_buses=(),  # series, not a bus: members live on usp / ekspress / spacebus-4000
        notes="Yamal name refers to the satellite series (Gazprom Space Systems); hardware built "
        "on USP (Energia), Ekspress-2000 (Reshetnev), and Spacebus-4000 (Thales) platforms. "
        "Wikipedia article is about the series, not a distinct bus. "
        "Yamal 101/102/201/202 -> usp; 300K/401 -> ekspress; 402/601 -> spacebus-4000.",
    ),
    # ---------- Constellation platforms (one operator, one design) ----------
    SatelliteBusSpec(
        slug="starlink-v1",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["spacex"],
        also_known_as=("Starlink v1", "Starlink first generation"),
        first_launch="2019-05-24",
        mass_kg_range=(227, 306),
        solar_span_m=8.1,
        # One GCAT string for the whole first generation: the v0.9 demo batch,
        # v1.0, VisorSat and the v1.5 laser-link satellites are not split.
        gcat_buses=("Starlink", "Starlink?"),
        notes="Flat-panel bus, single solar wing, krypton Hall thruster. "
        "STARLINK-21 through STARLINK-6380 in the catalogue.",
    ),
    SatelliteBusSpec(
        slug="starlink-v2-mini",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["spacex"],
        also_known_as=("Starlink V2 Mini",),
        first_launch="2023-02-27",
        mass_kg_range=(800, 800),
        solar_span_m=30.0,
        gcat_buses=("Starlink V2M",),
        notes="Roughly twice the v1.5 body with two solar wings, argon Hall thrusters and "
        "E-band backhaul. Sized for Falcon 9 until Starship flies the full V2.",
    ),
    SatelliteBusSpec(
        slug="starlink-v2-mini-optimized",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["spacex"],
        also_known_as=("Starlink V2 Mini Optimized",),
        first_launch="2024-11-?",
        mass_kg_range=(800, 800),
        solar_span_m=30.0,
        gcat_buses=("Starlink V2MO",),
        notes="Lighter V2 Mini that fits more satellites per launch; now the bulk of the "
        "fleet.",
    ),
    SatelliteBusSpec(
        slug="starlink-v2-mini-dtc",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["spacex"],
        also_known_as=("Starlink V2 Mini Direct-to-Cell",),
        first_launch="2024-01-03",
        mass_kg_range=(800, 800),
        solar_span_m=30.0,
        gcat_buses=("Starlink V2MD",),
        notes="V2 Mini plus a cellular-band phased array that works as a cell tower for "
        "unmodified handsets. Catalogued with a [DTC] suffix.",
    ),
    SatelliteBusSpec(
        slug="kuiper",
        wikidata_qid=None,  # Amazon has not published a platform name
        manufacturer=MANUFACTURER_BY_SLUG["kuiper-systems"],
        also_known_as=("Kuiper",),
        first_launch="2023-10-06",
        mass_kg_range=(490, 600),
        solar_span_m=5.0,
        gcat_buses=("Kuiper",),
        notes="Flat-panel bus with Ka-band phased arrays and optical crosslinks. GCAT names "
        "the platform after the programme, which is all Amazon has disclosed.",
    ),
    SatelliteBusSpec(
        slug="qianfan",
        wikidata_qid=None,  # no platform name published
        manufacturer=MANUFACTURER_BY_SLUG["secm"],
        also_known_as=("Qianfan", "Thousand Sails"),
        first_launch="2024-08-06",
        mass_kg_range=(267, 300),
        solar_span_m=10.0,
        gcat_buses=("Qianfan",),
        notes="Stackable flat-panel bus, 18 per Long March 6A. Built by the Innovation "
        "Academy for Microsatellites with Shanghai Gesi.",
    ),
    # ---------- Other / misc ----------
    SatelliteBusSpec(
        slug="sn-100a",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["sierra-nevada"],
        also_known_as=("SN-100A", "SN-100"),
        first_launch="2012-10-08",
        mass_kg_range=(165, 172),
        gcat_buses=("SN-100A",),
        notes="Box bus with one deployable wing from Sierra Nevada's MicroSat Systems line, "
        "flown as Orbcomm's second generation with an Argon ST AIS/M2M payload. "
        "The first generation (FM01-FM36) is Orbital's MicroStar.",
    ),
    SatelliteBusSpec(
        slug="starshield",
        wikidata_qid="Q115576467",
        manufacturer=MANUFACTURER_BY_SLUG["spacex"],
        also_known_as=("Starshield",),
        first_launch="2024-03-19",
        mass_kg_range=(730, 800),
        solar_span_m=29.0,
        # Catalogued only as USA numbers; GCAT's identification agrees with
        # Gunter's launch by launch, which is as firm as this gets publicly.
        gcat_buses=(
            "Starshield",
            "Starshield?",
        ),
        notes="Starlink-derived bus flying NRO payloads. No public TLEs for most of the "
        "fleet, and the identification is analysts' work rather than an official list.",
    ),
    SatelliteBusSpec(
        slug="amos",
        wikidata_qid="Q28195917",
        manufacturer=MANUFACTURER_BY_SLUG["iai"],
        also_known_as=(
            "Affordable Modular Optimized Satellite",
            "\u05e2\u05de\u05d5\u05e1",
            "AMOS-2000",
            "AMOS-3000",
            "AMOS-4000",
            "AMOS-6000",
            "AMOS-E",
        ),
        first_launch="1996-05-16",
        gcat_buses=(
            "Amos",
            "Amos-HP",
        ),
        notes="IAI GEO commsat family derived from Ofeq. AMOS-5 is ISS Reshetnev; AMOS-17 is "
        "reportedly Boeing 702MP per Wikipedia (sources conflict); AMOS-6 lost pre-launch 2016.",
    ),
    SatelliteBusSpec(
        slug="arsat-3k",
        wikidata_qid="Q22084804",
        manufacturer=MANUFACTURER_BY_SLUG["invap"],
        also_known_as=("ARSAT-3K",),
        first_launch="2014-10-16",
        mass_kg_range=(2900, 3000),
        gcat_buses=("ARSAT-Bus",),  # ARSAT-SG1 not yet in satcat
        notes="Argentine 3-axis GEO bus, 4.2 kW, 350 kg payload. Comparable to Spacebus 3000B2. "
        "TKSAT-1 (Tupac Katari) is CAST DFH-4, not ARSAT.",
    ),
    SatelliteBusSpec(
        slug="aprizesat",
        wikidata_qid="Q17512448",
        manufacturer=MANUFACTURER_BY_SLUG["spacequest"],
        also_known_as=("LatinSat",),
        first_launch="2002-12-20",
        mass_kg_range=(12, 14),
        gcat_buses=("Aprize",),
        notes="US microsat bus (~12-14 kg) for AIS/M2M. Now AAC SpaceQuest (since 2020).",
    ),
    SatelliteBusSpec(
        slug="arkyd-3",
        wikidata_qid="Q18520405",
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Arkyd 3", "Arkyd-3R"),
        first_launch="2015-04-14",
        mass_kg_range=(4, 5),
        # GCAT files Arkyd 3R under the generic "Cubesat 3U", which every other
        # 3U in the catalogue shares, so membership is by NORAD here.
        gcat_buses=(),
        norad_ids=(40742,),  # Arkyd 3 lost in 2014 Antares failure; not in satcat
        notes="3U CubeSat testbed for larger Arkyd-100. Arkyd 3 lost in Antares Orb-3 failure (2014); "
        "Arkyd 3R deployed from ISS 2015.",
    ),
    SatelliteBusSpec(
        slug="arkyd-100",
        wikidata_qid="Q25449222",
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Arkyd-100", "Leo Space Telescope", "Ceres"),
        first_launch=None,
        mass_kg_range=(11, 15),
        notes="Planned LEO space telescope; only ground-test prototypes; cancelled after 2018 ConsenSys acquisition.",
    ),
    SatelliteBusSpec(
        slug="arkyd-200",
        wikidata_qid=None,  # Q17620827 is the generic "Arkyd" series item, not the 200; no dedicated item
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Arkyd-200", "Interceptor"),
        first_launch=None,
        notes="Planned asteroid interceptor; full-size prototype built 2016; never launched.",
    ),
    SatelliteBusSpec(
        slug="arkyd-300",
        wikidata_qid=None,  # Q17620827 is the generic "Arkyd" series item, not the 300; no dedicated item
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Arkyd-300", "Rendezvous Prospector", "Arkyd-301"),
        first_launch=None,
        notes="Concept only; cancelled 2018.",
    ),
    SatelliteBusSpec(
        slug="mcsb",
        wikidata_qid="Q6889690",
        manufacturer=MANUFACTURER_BY_SLUG["nasa-ames"],
        also_known_as=("MCSB",),
        first_launch="2013-09-06",
        gcat_buses=("MCSB",),
        notes="Modular octagonal carbon-composite stack for low-cost interplanetary missions. "
        "Only LADEE flown to date.",
    ),
    SatelliteBusSpec(
        slug="photon",
        wikidata_qid="Q106610366",
        manufacturer=MANUFACTURER_BY_SLUG["rocket-lab"],
        also_known_as=("Photon", "Explorer", "Lightning", "Pioneer"),
        first_launch="2020-08-31",
        mass_kg_range=(200, 300),
        gcat_buses=(
            "Photon",
            "RL Pioneer",
        ),
        notes="Derived from Electron kick stage with Curie/HyperCurie engines. 2024 rebrand "
        "split into Explorer (deep space), Lightning (LEO, 3 kW), Pioneer (re-entry/custom), Photon.",
    ),
    SatelliteBusSpec(
        slug="rs-300",
        wikidata_qid="Q106457215",
        manufacturer=MANUFACTURER_BY_SLUG["ball-aerospace"],
        also_known_as=("BCP-300 (related)",),
        first_launch="2007-03-09",
        mass_kg_range=(125, 200),
        gcat_buses=(
            "BCP-300",
            "SphereX",
        ),
        notes="Small low-cost LEO bus; ASPEN avionics from Deep Impact heritage. "
        "Succeeded/renamed to BCP-300. Now BAE Systems Space & Mission Systems (2024).",
    ),
)


BUS_BY_SLUG: dict[str, SatelliteBusSpec] = {b.slug: b for b in SATELLITE_BUSES}
assert len(BUS_BY_SLUG) == len(SATELLITE_BUSES), "Duplicate bus slug"


BUS_BY_GCAT: dict[str, SatelliteBusSpec] = {}
for _bus in SATELLITE_BUSES:
    for _gcat in _bus.gcat_buses:
        assert _gcat not in BUS_BY_GCAT, (
            f"GCAT bus {_gcat!r} claimed by {BUS_BY_GCAT[_gcat].slug} and {_bus.slug}"
        )
        BUS_BY_GCAT[_gcat] = _bus

BUS_BY_NORAD: dict[int, SatelliteBusSpec] = {}
for _bus in SATELLITE_BUSES:
    for _norad in _bus.norad_ids:
        assert _norad not in BUS_BY_NORAD, f"NORAD {_norad} claimed twice"
        BUS_BY_NORAD[_norad] = _bus


def bus_for_object(norad: int | None, gcat_bus: str | None) -> SatelliteBusSpec | None:
    """Resolve a catalogued object's bus from its GCAT Bus string.

    An explicit ``norad_ids`` entry wins, because it exists to say something
    GCAT's Bus column cannot. Anything GCAT files under a string no bus claims
    (form-factor buckets like "Cubesat 3U", one-off platforms) gets no bus.
    """
    if norad is not None:
        bus = BUS_BY_NORAD.get(norad)
        if bus is not None:
            return bus
    if not gcat_bus:
        return None
    return BUS_BY_GCAT.get(gcat_bus)


def buses_by_manufacturer(manufacturer_qid: str) -> tuple[SatelliteBusSpec, ...]:
    return tuple(
        b for b in SATELLITE_BUSES if b.manufacturer.wikidata_qid == manufacturer_qid
    )
