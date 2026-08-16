"""
Catalog of satellite buses / spacecraft platforms with Wikipedia articles, for
tagging satellites (by TLE OBJECT_NAME) to their bus and locating a 3D model.

Compiled April 2026 from English Wikipedia (infoboxes + "List of satellites"
and Category:Satellites_using_the_<bus>_bus pages), Wikidata (QIDs), and
Sketchfab / NASA 3D Resources / ESA / CGTrader / TurboSquid for 3D models.

``known_satellites`` uses TLE OBJECT_NAME conventions; where Wikipedia's name
differs from SATCAT's (e.g. "Intelsat VI F-2" vs "INTELSAT 602"), SATCAT wins.
"""

import re
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
    also_known_as: tuple[str, ...] = ()
    first_launch: str | None = None
    mass_kg_range: tuple[int, int] | None = None
    solar_span_m: float | None = None
    known_satellites: tuple[str, ...] = ()
    model_url: str | None = None
    model_format: str | None = None
    model_license: str | None = None
    # Model bundle slug (EXPORT_DIR/v1/models/) applied to every known_satellites
    # entry, as a post-pass after explicit per-mission assignments win first.
    model_slug: str | None = None
    notes: str | None = None


# AI disclosure: deep research, then QIDs and known_satellites checked against
# Wikidata, Wikipedia, Gunter's Space Page, and satcat.csv. Entries that don't
# resolve in satcat are annotated inline (launch failure, not-yet-launched,
# deep-space, decayed-and-removed, or ambiguous name).
SATELLITE_BUSES: tuple[SatelliteBusSpec, ...] = (
    # ---------- Hughes / Boeing (spin-stabilized drums, then 3-axis) ----------
    SatelliteBusSpec(
        slug="hs-333",
        wikidata_qid="Q5635829",
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("Hughes 333",),
        first_launch="1972",
        mass_kg_range=(146, 574),
        known_satellites=(
            "ANIK A1",
            "ANIK A2",
            "ANIK A3",
            "WESTAR 1",
            "WESTAR 2",
            "WESTAR 3",
            "PALAPA 1",
            "PALAPA 2",
        ),
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
        known_satellites=(
            "SBS 1",
            "SBS 2",
            "SBS 3",
            "SBS 4",
            "SBS 5",
            "WESTAR 4",
            "WESTAR 5",
            "WESTAR 6",
            "ANIK C1",
            "ANIK C2",
            "ANIK C3",
            "ANIK D1",
            "ANIK D2",
            "PALAPA B1",
            "PALAPA B2",
            "PALAPA B2P",
            "PALAPA B2R",
            "PALAPA B4",
            "GALAXY 1",
            "GALAXY 1R",  # known as GALAXY 1R2 on wikipedia, 1R failed and 1R2 re-used the name in celestrack
            "GALAXY 2",
            "GALAXY 3",
            "GALAXY 5",
            "GALAXY 6",
            "GALAXY 9",
            "TELSTAR 3A",  # Telstar 301 / Arabsat-1E
            "TELSTAR 302",
            "TELSTAR 303",
            "AUSSAT 1",
            "AUSSAT 2",
            "AUSSAT 3",
            "BRASILSAT 1",
            "BRASILSAT 2",
            "BRASILSAT B1",
            "BRASILSAT B2",
            "BRASILSAT B3",
            "BRASILSAT B4",
            "MORELOS 1",
            "MORELOS 2",
            "MARCOPOLO 1",
            "MARCOPOLO 2",
            "THAICOM 1",
            "THAICOM 2",
            "APSTAR-1",
            "APSTAR-1A",
            "MEASAT-1",
            "MEASAT-2",
            "ASIASAT 1",
            "BSAT-1A",
            "BSAT-1B",
            "THOR II",  # thor 2
            "THOR III",  # thor 3
            "SIRIUS 3",
            "BONUM-1",
            "ASTRA 2D",
            "ASTRA 3A",
            "EUTELSAT 31A",  # eBird 1 / Eurobird 3
            "ZHONGXING-7",  # ZX 7 / Chinasat-7 / HGS 2
            "USA 67",  #  Prowler (Q14940655)
        ),
        notes="Spin-stabilized telescoping dual-cylinder drum, 2.16 m dia stowed / 6.6-8 m deployed. "
        "58 built 1980-2003. Variants: base, L (long-life), HP (high-power), W (wide). "
        "No free Sketchfab model found.",
    ),
    SatelliteBusSpec(
        slug="hs-381",
        wikidata_qid=None,
        manufacturer=MANUFACTURER_BY_SLUG["hughes"],
        also_known_as=("Leasat bus", "Syncom IV bus"),
        first_launch="1984",
        mass_kg_range=(1315, 3400),
        known_satellites=(
            "LEASAT 1",
            "LEASAT 2",
            "LEASAT 3",
            "LEASAT 4",
            "LEASAT 5",
        ),
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
        known_satellites=("JCSAT-1", "JCSAT-2", "SBS-6"),
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
        known_satellites=(
            "INTELSAT 601",
            "INTELSAT 602",
            "INTELSAT 603",
            "INTELSAT 604",
            "INTELSAT 605",
        ),
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
        known_satellites=(
            "OPTUS B1",
            "OPTUS B2",
            "OPTUS B3",
            "DIRECTV 1",
            "DIRECTV 2",
            "DIRECTV 3",
            "DIRECTV 1R",
            "DIRECTV 4S",
            "ASIASAT 3S",
            "ASIASAT 4",
            "PAKSAT 1",  # Palapa-C1, HGS-3, Anatolia-1
            "PALAPA C2",
            "INTELSAT 802",
            "JCSAT-3",
            "INTELSAT 26",  # JCSAT-4
            "JCSAT-1B",  # JCSAT 5
            "JCSAT-4A",
            "JCSAT-2A",  # JCSAT-8
            "ORION 3",
            "MEASAT-3",
            "GALAXY 3R",
            "GALAXY 4",
            "GALAXY 4R",
            "GALAXY 8",
            "GALAXY 10R",
            "SOLIDARIDAD 1",
            "SOLIDARIDAD 2",
            "ASTRA 1C",
            "ASTRA 1D",
            "ASTRA 1E",
            "ASTRA 1F",
            "ASTRA 1G",
            "ASTRA 1H",
            "ASTRA 2A",
            "ASTRA 2C",
            "SUPERBIRD-A2",  # Superbird-6
            "SUPERBIRD-A3",  # Superbird-3, Superbird-C
            "SUPERBIRD-B2",
            "AMSC 1",
            "MSAT M1",
            "UFO 1",
            "UFO 2",
            "UFO 3",
            "UFO 4",
            "UFO 5",
            "UFO 6",
            "UFO 7",
            "UFO 8",
            "UFO 9",
            "UFO 10",
            "UFO 11",
            "GOES 13",
            "GOES 14",
            "GOES 15",
            "TDRS 8",
            "TDRS 9",
            "TDRS 10",
            "TDRS 11",
            "TDRS 12",
            "TDRS 13",
            "OMNI-M1",  # ICO F2
            "SES-7",
            "INTELSAT 2 ",
            "INTELSAT 3R",
            "INTELSAT 4 ",
            "INTELSAT 5 ",
            "INTELSAT 6B",
            "INTELSAT 9 ",
            "HGS 1",  # AsiaSat 3 → HGS-1 → PAS-22
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
        known_satellites=(
            "GALAXY 11",
            "INTELSAT 1R",  # IS-1R, PAS-1R
            "ANIK F1",
            "ANIK F2",
            "THURAYA 1",
            "THURAYA 2",
            "THURAYA 3",
            "XM-1",
            "XM-2",
            "XM-3",
            "XM-4",
            "SPACEWAY 1",
            "SPACEWAY 2",
            "SPACEWAY 3",
            "DIRECTV 10",
            "DIRECTV 11",
            "DIRECTV 12",
            "SKYTERRA 1",
            "INTELSAT 21",
            "INTELSAT 22",  # INTELSAT 27: failed to orbit, untracked
            "INTELSAT 29E",
            "INTELSAT 33E",
            "INTELSAT 35E",
            "INMARSAT 5-F1",
            "INMARSAT 5-F2",
            "INMARSAT 5-F3",
            "INMARSAT 5-F4",
            "MORELOS 3",  # MEXSAT 2. Mexsat-1: failed to orbit
            "ABS-2A",
            "ABS-3A",
            "EUTELSAT 115 WEST B",
            "EUTELSAT 117 WEST B",
            "SES-9",
            "SES-15",
            "SES-20",
            "SES-21",
            "VIASAT-2",
            "VIASAT-3 F1",
            "VIASAT-3 F2",
            "VIASAT-3 F3",  # Not launched as of 2026-04-19
            "SILKWAVE 1",  # Not launched as of 2026-04-19
            "O3B MPOWER F1",
            "O3B MPOWER F2",
            "O3B MPOWER F3",
            "O3B MPOWER F4",
            "O3B MPOWER F5",
            "O3B MPOWER F6",
            "O3B MPOWER F7",
            "O3B MPOWER F8",
            "O3B MPOWER F9",
            "O3B MPOWER F10",
            "O3B MPOWER F11",  # Not launched as of 2026-04-19
            "O3B MPOWER F12",
            "O3B MPOWER F13",
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
        known_satellites=tuple(
            f"NAVSTAR {n}" for n in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11)
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-ii",
        wikidata_qid="Q121831554",
        manufacturer=MANUFACTURER_BY_SLUG["rockwell"],
        also_known_as=("Navstar Block II", "GPS Block 2"),
        first_launch="1989",
        known_satellites=tuple(
            f"NAVSTAR {n}" for n in (13, 14, 15, 16, 17, 18, 19, 20)
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iia",
        wikidata_qid="Q121831557",
        manufacturer=MANUFACTURER_BY_SLUG["rockwell"],
        also_known_as=("Navstar Block IIA", "GPS Block 2A"),
        first_launch="1990",
        # NAVSTAR 44 (USA-135 = IIA-19) is the last IIA, launched after the first IIR.
        known_satellites=tuple(
            f"NAVSTAR {n}"
            for n in (
                21,
                22,
                23,
                24,
                25,
                26,
                27,
                28,
                29,
                30,
                31,
                32,
                33,
                34,
                35,
                36,
                37,
                38,
                39,
                44,
            )
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iir",
        wikidata_qid="Q121831559",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=("Navstar Block IIR", "GPS Block 2R"),
        first_launch="1997",
        # NAVSTAR 43 (USA-132 = IIR-2) is the first successful IIR.
        known_satellites=tuple(
            f"NAVSTAR {n}" for n in (43, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56)
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iir-m",
        wikidata_qid="Q121831561",
        manufacturer=MANUFACTURER_BY_SLUG["lockheed-martin"],
        also_known_as=("GPS Block IIRM", "Navstar Block IIR-M", "GPS Block 2R-M"),
        first_launch="2005",
        known_satellites=tuple(
            f"NAVSTAR {n}" for n in (57, 58, 59, 60, 61, 62, 63, 64)
        ),
    ),
    SatelliteBusSpec(
        slug="gps-block-iif",
        wikidata_qid="Q5514327",
        manufacturer=MANUFACTURER_BY_SLUG["boeing"],
        also_known_as=("Navstar-2F", "GPS Block 2F", "GPS IIF"),
        first_launch="2010",
        known_satellites=tuple(
            f"NAVSTAR {n}" for n in (65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76)
        ),
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
        known_satellites=(
            "AMC-1",
            "AMC-2",
            "AMC-4",
            "AMC-6",
            "AMC-7",
            "AMC-8",
            "AMC-14",
            "AMC-15",
            "AMC-16",
            "AMC-3",  # EAGLE 1
            "NSS-11",
            "ABS-6",
            "ABS-7",
            "BSAT-3A",
            "BSAT-3B",
            "BSAT-3C",
            "AMC-10",  # GE-10
            "AMC-11",  # GE-11
            "AMC-18",  # GE-18
            "GOES 16",
            "GOES 17",
            "GOES 18",
            "GOES 19",
            "USA 207",  # Nemesis 1, PAN
            "USA 257",  # Nemesis 2, CLIO
            "TELKOM 1",
            "VINASAT-1",
            "VINASAT-2",
            "ZHONGXING-5A",
            "ECHOSTAR 3",
            "ECHOSTAR 4",
            "ECHOSTAR 7",
            "ECHOSTAR 10",
            "ECHOSTAR 12",
            "NIMIQ 1",
            "NIMIQ 2",
            "N-SAT-110",
            "SUPERBIRD 5",
            "ASTRA 1KR",
            "ASTRA 1L",
            "JCSAT-5A",
            "JCSAT-3A",  # JCSAT-11: launch failure
            "JCSAT-12",
            "JCSAT-13",
            "JCSAT-17",
            "NSS-6",
            "NSS-7",
            "ASTRA 4A",
            "GARUDA 1",
            "AEHF-1",
            "AEHF-2",
            "AEHF-3",
            "AEHF-4",
            "AEHF-5",
            "AEHF-6",
            "MUOS-1",
            "MUOS-2",
            "MUOS-3",
            "MUOS-4",
            "MUOS-5",
            "NAVSTAR 77",
            "NAVSTAR 78",
            "NAVSTAR 79",
            "NAVSTAR 80",
            "NAVSTAR 81",
            "NAVSTAR 82",
            "NAVSTAR 83",
            "NAVSTAR 84",
            "NAVSTAR 85",
            "NAVSTAR 86",  # Not launched as of 2026-04-20
            "SBIRS GEO-1",
            "SBIRS GEO-2",
            "SBIRS GEO-3",
            "SBIRS GEO-4",
            "SBIRS GEO-5",
            "SBIRS GEO-6",
            "ARABSAT-6A",
            "HELLAS-SAT 4",  # SaudiGeoSat-1/HellasSat-4
            # NG-OPIR-GEO 1-3: launch 2026-2028
            # GeoXO 1-3: launch 2030+
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
        also_known_as=("LM 700", "LM-700A", "LM-700B", "Iridium bus"),
        first_launch="1997-05-05",
        mass_kg_range=(680, 689),
        known_satellites=tuple(f"IRIDIUM {i}" for i in range(1, 99)),
        notes="Original Iridium constellation block-1 bus. 95 launched 1997-2002. "
        "Iridium-NEXT (2017+) uses Thales ELiTeBus, not LM-700. "
        "Physical engineering model on display at Smithsonian NASM.",
    ),
    SatelliteBusSpec(
        slug="elitebus1000",
        wikidata_qid="Q125698667",
        manufacturer=MANUFACTURER_BY_SLUG["thales-alenia-space"],
        first_launch="2010-10-19",
        known_satellites=tuple(
            [f"IRIDIUM {i}" for i in range(100, 182)]
            + [
                f"GLOBALSTAR M0{i}" for i in range(73, 98)
            ]  # Globalstar second generation (Q3108985)
            + [f"O3B FM{i}" for i in range(2, 21)]  # O3b (Q7072273)
            + ["O3B PFM"]
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
        known_satellites=(
            "SUPERBIRD-A",
            "SUPERBIRD-A1",
            "SUPERBIRD-B",  # lost after 1990 launch; not in current satcat
            "SUPERBIRD-B1",
            "ABS-3",  # Agila 2, renamed ABS-3
            "APSTAR-2R",
            "ASIASAT 5",
            "ASIASAT 6",
            "ASIASAT 7",
            "ASIASAT 8",
            "ASIASAT 9",
            "AZERSPACE 2",  # = Intelsat 38 (one satellite)
            "BRISAT",
            "BSAT-4A",
            "BSAT-4B",
            "BULGARIASAT-1",
            "TEMPO 1",
            "TEMPO 2",
            "DIRECTV 5",
            "DIRECTV 6",
            "DIRECTV 7S",
            "DIRECTV 8",
            "DIRECTV 9S",
            "DIRECTV 14",
            "ECHOSTAR 5",
            "ECHOSTAR 6",
            "ECHOSTAR 8",
            # EchoStar 9 = Galaxy 23 (listed)
            "ECHOSTAR 11",
            "ECHOSTAR 15",
            "ECHOSTAR 16",
            "ECHOSTAR 17",
            "ECHOSTAR 18",
            "ECHOSTAR 19",
            "ECHOSTAR 21",
            "ECHOSTAR 23",
            "ECHOSTAR 24",  # = Jupiter 3
            # Jupiter 1/2 = EchoStar 17/19 (listed); Europe*Star 1 = Intelsat 12 (listed)
            "INTELSAT 12",
            "INTELSAT 14",
            "INTELSAT 17",
            "INTELSAT 19",
            "INTELSAT 20",
            "INTELSAT 25",
            "INTELSAT 30",
            "INTELSAT 31",
            "INTELSAT 34",
            "INTELSAT 36",
            "INTELSAT 37E",
            "INTELSAT 39",
            "INTELSAT 40E",
            "INTELSAT 701",
            "INTELSAT 702",
            "INTELSAT 703",  # decayed/removed from satcat
            "INTELSAT 704",
            "INTELSAT 705",
            "INTELSAT 706",
            "INTELSAT 707",
            "INTELSAT 708",  # 1996 Long March 3B launch failure
            "INTELSAT 709",
            "INTELSAT 901",
            "INTELSAT 902",
            "INTELSAT 903",
            "INTELSAT 904",
            "INTELSAT 905",
            "INTELSAT 906",
            "INTELSAT 907",
            "GALAXY 16",
            "GALAXY 18",
            "GALAXY 19",
            "GALAXY 23",
            "GALAXY 25",
            "GALAXY 26",
            "GALAXY 27",
            "GALAXY 28",
            "GALAXY 31",
            "GALAXY 32",
            "GALAXY 35",
            "GALAXY 36",
            "GALAXY 37",
            "GOES 8",
            "GOES 9",
            "GOES 10",
            "GOES 11",
            "GOES 12",
            "THAICOM 4",  # IPSTAR-1
            "JCSAT-2B",  # = JCSAT-14 in satcat
            "JCSAT-15",
            "JCSAT-16",
            "MBSAT 1",  # MBSat; decayed, not in current satcat
            "MTSAT 1",  # 1999 H-II launch failure
            "MTSAT-1R",  # = Himawari-6
            "N-STAR A",
            "N-STAR B",
            "NIMIQ 5",
            "NIMIQ 6",
            "NSS-12",
            "SKY MUSTER 1",  # = NBN-Co 1A
            "SKY MUSTER 2",  # = NBN-Co 1B
            "OPTUS 10",
            "OPTUS C1",
            "ORION 2",
            # Telstar 5/6/7 = Galaxy 25/26/27 (listed)
            "TELSTAR 11N",
            "TELSTAR 12",
            "TELSTAR 14R",  # Telstar 14 = Estrela do Sul (listed)
            "TELSTAR 18",
            "TELSTAR 18V",
            "TELSTAR 19V",
            "ESTRELA DO SUL",  # Estrela do Sul 1; Estrela do Sul 2 = Telstar 14R (listed)
            "PAS 6",
            "INTELSAT 7",  # PAS-7
            "INTELSAT 8",  # PAS-8
            "PROTOSTAR 1",  # ProtoStar I; deorbited 2010, not in satcat
            "NUSANTARA SATU",  # PSN-6
            "QUETZSAT 1",
            # Satmex 6/8 = Eutelsat 113/117 West A (listed)
            "EUTELSAT 113 WEST A",
            "EUTELSAT 117 WEST A",
            "EUTELSAT 7C",
            "ES'HAIL 1",  # = Eutelsat 25B (one satellite)
            "EUTELSAT 65 WEST A",
            "SES-4",
            "SES-5",
            "SIRIUS-1",  # Sirius FM-1
            "SIRIUS-2",  # Sirius FM-2
            "SIRIUS-3",  # Sirius FM-3
            "FM-5",  # Sirius FM-5 (satcat OBJECT_NAME is literally "FM-5")
            "FM-6",  # Sirius FM-6
            "SXM-7",
            "SXM-8",
            "SXM-9",
            "SXM-10",
            "SPAINSAT",
            # XTAR-LANT is a hosted payload on Spainsat (listed)
            "XTAR-EUR",
            "STAR ONE C4",
            "STAR ONE D1",
            "STAR ONE D2",
            "TELKOM 4",  # = Merah Putih (bare "MERAH PUTIH" also matches Merah Putih 2, a Spacebus-4000)
            "TERRESTAR-1",
            "THOR 7",
            "VIASAT-1",
            "WILDBLUE-1",
            "XM-5",
            "AMAZONAS 3",
            "AMAZONAS 5",
            "ANIK G1",
            "ABS-2",
            "HISPASAT 30W-5",
            "HISPASAT 30W-6",
            "ICO G1",
            "PSYCHE",
        ),
        model_url="https://science.nasa.gov/3d-resources/space-systems-loral-ssl-1300/",
        model_format="glTF/OBJ",
        model_license="NASA Public Domain",
        model_slug="space-systems-loral-ssl-1300",
        notes="3-axis box + two solar wings, GEO. First Western commsat with electric propulsion "
        "(MBSat 2004). Rebranded Lanteris 1300 Oct 2025 after Intuitive Machines acquisition. "
        "Sketchfab community model: sketchfab.com/3d-models/loral-ssl-1300-satellite-b3fddca0b88346cfad87b2bb0700549f",
    ),
    # ---------- Orbital Sciences / Orbital ATK / Northrop Grumman (STAR family) ----------
    SatelliteBusSpec(
        slug="star-bus",
        wikidata_qid="Q1131474",
        manufacturer=MANUFACTURER_BY_SLUG["northrop-grumman"],
        also_known_as=("Star-1", "Star-2", "STARBus", "STAR Bus family"),
        first_launch="1997-11-12",
        known_satellites=(
            "INDOSTAR 1",
            "BSAT-2A",
            "BSAT-2B",  # launch failure (stranded by Ariane upper stage), but cataloged
            "BSAT-2C",
        ),
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
        known_satellites=(
            "USA 187",  # MiTEx-A (MiTEx-B / USA 188 was Lockheed Martin, not Orbital)
            "USA 253",  # GSSAP 1
            "USA 254",  # GSSAP 2
            "USA 270",  # GSSAP 3
            "USA 271",  # GSSAP 4
            "USA 324",  # GSSAP 5
            "USA 325",  # GSSAP 6
            "USA 582",  # GSSAP 7
            "USA 583",  # GSSAP 8
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
        known_satellites=(
            "N-STAR C",
            "GALAXY 12",
            "GALAXY 14",
            "GALAXY 15",
            "GALAXY 30",
            "TELKOM 2",
            "OPTUS D1",
            "OPTUS D2",
            "OPTUS D3",
            "INTELSAT 11",
            "INTELSAT 15",
            "INTELSAT 16",
            "INTELSAT 18",
            "INTELSAT 23",
            "HORIZONS-2",
            "THOR 5",
            "AMC-21",
            "NSS-9",
            "MEASAT-3A",
            "SES-1",
            "SES-2",
            "SES-3",
            "SES-8",
            "KOREASAT 6",
            "INTELSAT 28",  # = New Dawn
            "HYLAS 2",
            "MEXSAT 3",
            "STAR ONE C3",
            "AZERSPACE 1",  # = Africasat-1A
            "THAICOM 6",
            "THAICOM 8",
            "SKY MEXICO-1",
            "EUTELSAT 5 WEST B",
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
        known_satellites=(
            "AL YAH 3",
            "GOVSAT-1",
            "HYLAS 4",
            "MEV-1",
            "MEV-2",
            "GALAXY 33",
            "GALAXY 34",
            "SES-18",
            "SES-19",
            "ASBM-1",  # hosts Inmarsat GX 10A payload
            "ASBM-2",  # hosts Inmarsat GX 10B payload
        ),
        notes="Evolutionary growth of GEOStar-2 with larger solar arrays and hybrid propulsion option. "
        "Supports dual-launch stacking (MEV/MRV, Galaxy 33+34).",
    ),
    SatelliteBusSpec(
        slug="leostar",
        wikidata_qid=None,  # No dedicated item for the umbrella; Q133286575 covers only LEOStar-3
        manufacturer=MANUFACTURER_BY_SLUG["orbital-sciences"],
        also_known_as=("LEOStar-1", "LEOStar-2", "LEOStar-3"),
        first_launch="2003",  # OrbView-4 (2001) was the first LEOStar flight but failed to orbit
        mass_kg_range=(300, 4000),
        known_satellites=(
            "ORBVIEW 3",  # LEOStar-1
            "ORBVIEW-4",  # LEOStar-1; 2001 Taurus launch failure, never cataloged
            "GALEX",  # LEOStar-2
            "SORCE",
            "RHESSI",
            "AIM",  # LEOStar-2 (NOT rs-300)
            "FGRST (GLAST)",  # Fermi / GLAST, LEOStar-3
            "NUSTAR",
            "OCO 2",
            "LANDSAT 8",  # LEOStar-3
            "ICESAT-2",
            "NOAA 21",  # JPSS-2, LEOStar-3 (NOAA-20/JPSS-1 was Ball BCP-2000, not LEOStar)
            "TESS",  # LEOStar-2
            "ICON",  # LEOStar-2
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
        known_satellites=(
            # satcat zero-pads FM01-FM09; FM10+ unpadded
            "ORBCOMM FM01",
            "ORBCOMM FM02",
            "ORBCOMM FM03",
            "ORBCOMM FM04",
            "ORBCOMM FM05",
            "ORBCOMM FM06",
            "ORBCOMM FM07",
            "ORBCOMM FM08",
            "ORBCOMM FM09",
            "ORBCOMM FM10",
            "ORBCOMM FM11",
            "ORBCOMM FM12",
            "ORBCOMM FM13",
            "ORBCOMM FM14",
            "ORBCOMM FM15",
            "ORBCOMM FM16",
            "ORBCOMM FM17",
            "ORBCOMM FM18",
            "ORBCOMM FM19",
            "ORBCOMM FM20",
            "ORBCOMM FM21",
            "ORBCOMM FM22",
            "ORBCOMM FM23",
            "ORBCOMM FM24",
            "ORBCOMM FM25",
            "ORBCOMM FM26",
            "ORBCOMM FM27",
            "ORBCOMM FM28",
            "ORBCOMM FM29",
            "ORBCOMM FM30",
            "ORBCOMM FM31",
            "ORBCOMM FM32",
            "ORBCOMM FM33",
            "ORBCOMM FM34",
            "ORBCOMM FM35",
            "ORBCOMM FM36",
            "ORBVIEW 1",  # OrbView-1 / Microlab
            "MUBLCOM",
            "FORMOSAT-3 FM1",
            "FORMOSAT-3 FM2",
            "FORMOSAT-3 FM3",
            "FORMOSAT-3 FM4",
            "FORMOSAT-3 FM5",
            "FORMOSAT-3 FM6",
            "IBEX",
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
        known_satellites=(
            "ARABSAT-1A",
            "ARABSAT-1B",
            "INSAT-2DT",
        ),  # Arabsat-1C sold to India
        notes="Franco-German Eurosatellite consortium (Aerospatiale + MBB).",
    ),
    SatelliteBusSpec(
        slug="spacebus-300",
        wikidata_qid="Q125680104",  # Spacebus-300 (no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["aerospatiale"],
        also_known_as=("SB-300",),
        first_launch="1987-11-21",
        mass_kg_range=(2077, 2144),
        known_satellites=(
            "TDF 1",
            "TDF 2",
            "TELE-X",
            "TVSAT 1",
            "TVSAT 2",
        ),
        notes="Eurosatellite DBS bus for TV-Sat/TDF/Tele-X programs.",
    ),
    SatelliteBusSpec(
        slug="spacebus-2000",
        wikidata_qid="Q125680105",  # Spacebus-2000 (no enwiki sitelink)
        manufacturer=MANUFACTURER_BY_SLUG["aerospatiale"],
        first_launch="1990-08-30",
        mass_kg_range=(1800, 2500),
        solar_span_m=22.4,
        known_satellites=(
            "EUTELSAT 2-F1",
            "EUTELSAT 2-F2",
            "EUTELSAT 2-F3",
            "EUTELSAT 2-F4",
            "EUTELSAT-2 F5",  # lost in 1994 Ariane failure (with Turksat 1A); not in satcat
            "AMC-5",
            "HOT BIRD 1",
            "NAHUEL 1A",
            "TURKSAT 1A",  # lost in 1994 Ariane failure; not in satcat
            "TURKSAT 1B",
            "TURKSAT 1C",
        ),
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
        known_satellites=(
            "ARABSAT-2A",
            "ARABSAT-2B",
            "ZHONGXING-5B",  # Sinosat-1
            "THAICOM 3",
            "THAICOM 5",
            "EUTELSAT 12 WEST B",  # Atlantic Bird 2
            "BADR-3",  # Arabsat-3A
            "COMSATBW-1",
            "COMSATBW-2",
            "EUTELSAT 133 WEST A",  # Eurobird 1
            "EUTELSAT W2",
            "EUTELSAT 48C",  # Eutelsat W3
            "EUTELSAT 80A",  # Eutelsat W4
            "EUTELSAT 33B",  # Eutelsat W5
            "HISPASAT 1C",
            "HISPASAT 30W-4",  # Hispasat 1D
            "ASTRA 5A",  # Sirius 2
            "AMC-9",
            "TURKSAT 2A",  # Eurasiasat 1
            "GALAXY 17",
            "EUTELSAT 33D",  # Hot Bird 6
            "EUTELSAT HOTBIRD 13E",  # Hot Bird 7A
            "STAR ONE C1",
            "STAR ONE C2",
            "EUTELSAT 5 WEST A",  # Stellat 5
            "STENTOR",  # lost in 2002 Ariane 5 ECA failure; not in satcat
            "ASTRA 1K",  # reached only parking orbit (2002 Proton failure); cataloged, decayed
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
        known_satellites=(
            "ATHENA-FIDUS",
            "BANGABANDHUSAT-1",  # Bangabandhu-1
            "INMARSAT GX5",
            "KOREASAT 5",
            "KOREASAT 5A",
            "KOREASAT 6A",
            "KOREASAT 7",
            "NILESAT 201",
            "NILESAT 301",
            "SES-22",
            "SES-23",  # not in satcat (not separately cataloged / not yet launched)
            "SICRAL 2",
            "TELKOM 3S",
            "MERAH PUTIH 2",
            "THOR 6",
            "TURKSAT 3A",
            "PALAPA D",
            "RASCOM-QAF 1",
            "RASCOM-QAF 1R",
            "SYRACUSE 3A",
            "SYRACUSE 3B",
            "APSTAR-6",
            "APSTAR-7",
            "TURKMENALEM52E/MONACOSAT",  # TurkmenAlem 52E / MonacoSat
            "ZHONGXING-6B",  # ZX 6B
            "ZHONGXING-9",  # ZX 9
            "ZHONGXING-12",  # ZX 12
            "NSS-10",  # ex AMC-12 (renamed 2009)
            "EUTELSAT W3B",  # failed to orbit 2010; cataloged
            "EUTELSAT 16A",
            "EUTELSAT 8 WEST B",
            "EUTELSAT 21B",
            "YAMAL 402",
            "YAMAL 601",  # Spacebus-4000C4 (moved from ekspress)
            "CIEL-2",
            "EUTELSAT 36B",  # Eutelsat W7
            "HELLAS-SAT 3",
            "EUTELSAT 10A",  # Eutelsat W2A
        ),
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
        known_satellites=(
            "EUTELSAT KONNECT",
            "SYRACUSE 4A",
            "SES-17",
            "EUTELSAT KONNECT VHTS",
            "EUTELSAT 10B",
            "AMAZONAS NEXUS",
            "NUSANTARA TIGA (SATRIA)",
            "ASTRA 1P (SES-24)",
            # Not yet launched: Sicral 3A, Sicral 3B (~2027)
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
        known_satellites=(
            "COSMO-SKYMED 1",
            "COSMO-SKYMED 2",
            "COSMO-SKYMED 3",
            "COSMO-SKYMED 4",
            "CSG-1",
            "CSG-2",
            "CSG-3",
            "RADARSAT-2",
            "SENTINEL-1A",
            "SENTINEL-1B",
            "SENTINEL-1C",
            "SENTINEL-1D",
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
        known_satellites=(
            "JASON-1",
            "CALIPSO",
            "COROT",
            "JASON-2",
            "SMOS",
            "JASON-3",
        ),
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
        known_satellites=(
            "AFRISTAR",
            "ASIASTAR",
            "ASTRA 2B",
            "BADR-4",
            "EUROBIRD 4A",  # Eutelsat 4A / ex-Eutelsat W1 (Eurostar-2000+)
            "EUTELSAT 16B",  # = Hot Bird 4
            "HELLAS-SAT 2",
            "HOT BIRD 2",  # decayed; not in current satcat
            "HOT BIRD 3",  # decayed; not in current satcat
            "HOT BIRD 5",  # decayed; not in current satcat
            "NILESAT 102",
            "ST-1",
            "TELECOM 2A",
            "TELECOM 2C",
            "TELSTAR 11",
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
        known_satellites=(
            "ANASIS 2",  # KR military; not in satcat
            "AMAZONAS 1",
            "AMAZONAS 2",
            "ASTRA 1M",
            "ASTRA 1N",
            "ASTRA 2E",
            "ASTRA 2F",
            "ASTRA 2G",
            "ASTRA 3B",
            "ASTRA 5B",
            # Atlantic Bird 7 = Eutelsat 7 West A
            "EUTELSAT 70B",  # Atlantic Bird 70B
            "ANIK F1R",
            "ANIK F3",
            "ARABSAT-5C",
            "ARABSAT-6B",
            "BADR-5",  # Arabsat-5B
            "DIRECTV 15",
            "EXPRESS-AM4",  # Ekspress-AM4
            "EKSPRESS-AM4R",  # 2014 Proton launch failure; not in satcat
            "EXPRESS-AM7",  # Ekspress-AM7
            "EXPRESS-AMU1",  # Ekspress-AMU1
            "EUTELSAT 7 WEST A",
            "EUTELSAT 9B",
            "EUTELSAT 36 WEST A",  # Eutelsat W3A
            "EUTELSAT 139 WEST A",
            "EUTELSAT 172B",
            "EUTELSAT 33F",  # Hot Bird 8 / Hot Bird 13B
            "EUTELSAT HOTBIRD 13C",  # Hot Bird 9 / Hot Bird 13C
            "EUTELSAT 33E",  # Hot Bird 10 / Hot Bird 13D
            "INTELSAT 10-02",
            "KA-SAT",
            "MEASAT-3B",
            "NIMIQ 4",
            "INMARSAT 4-F1",
            "INMARSAT 4-F2",
            "INMARSAT 4-F3",
            "INMARSAT 6-F1",
            "INMARSAT 6-F2",
            "SES-6",
            "SES-10",
            "SES-11",
            "SES-14",
            "SKYNET 5A",
            "SKYNET 5B",
            "SKYNET 5C",
            "SKYNET 5D",
            "SYRACUSE 4B",  # Eurostar-3000EOR
            "TELSTAR 12V",
            "TURKSAT 5A",
            "TURKSAT 5B",
            "YAHSAT 1A",
            "YAHSAT 1B",
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
        known_satellites=("PLEIADES 1A", "PLEIADES 1B"),
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
        known_satellites=("ALPHASAT",),  # sole Alphabus flight unit (= Inmarsat-4A F4)
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
        known_satellites=(
            "DEMETER",
            "PARASOL",
            "ESSAIM-1",
            "ESSAIM-2",
            "ESSAIM-3",
            "ESSAIM-4",
            "PICARD",
            "ELISA W11",  # Elisa 1
            "ELISA E12",  # Elisa 2
            "ELISA W23",  # Elisa 3
            "ELISA E24",  # Elisa 4
            "SPIRALE A",
            "SPIRALE B",
            "MICROSCOPE",
            "ALSAT-2A",
            "ALSAT-2B",
            "VNREDSAT 1",
            "TARANIS",  # lost in 2020 Vega VV17 launch failure; not in satcat
            "ANGELS",
        ),
        notes="French ~125 kg microsat platform (CNES + Airbus). Myriade-Evolutions is 350-400 kg.",
    ),
    SatelliteBusSpec(
        slug="small-geo",
        wikidata_qid="Q48755064",
        manufacturer=MANUFACTURER_BY_SLUG["ohb"],
        also_known_as=("SGEO", "Luxor"),
        first_launch="2017-01-28",
        mass_kg_range=(1600, 3200),
        known_satellites=(
            "HISPASAT 36W-1",
            "EDRS-C",
            "HEINRICH HERTZ",
            "ELECTRA",  # not launched as of 2026; not in satcat
        ),
        notes="German/ESA ARTES-11 3-ton GEO platform; classic, hybrid, or all-electric propulsion.",
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
        known_satellites=(
            "DFH 3-2",  # ChinaSat 6 / ZX 6 (1997, first successful DFH-3)
            "ZHONGXING-22",  # ChinaSat 22 / Fenghuo-1
            "ZHONGXING-22A",
            "BEIDOU-2 G1",
            "BEIDOU-2 G2",
            "BEIDOU-2 M1",
            "BEIDOU-2 IGSO-1",
            "TIANLIAN 1-01",
            "TIANLIAN 1-02",
            "TIANLIAN 1-03",
            "CHANG'E-1",
            "CHANG'E-2",
            "CHANG'E-5 T1",
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
        known_satellites=(
            "SINOSAT 2",  # failed to deploy arrays (2006); cataloged
            "NIGCOMSAT 1",
            "NIGCOMSAT 1R",
            "ZHONGXING-9A",  # ChinaSat 9A (ChinaSat 9 = Thales Spacebus-4000 = Zhongxing-9)
            "CHINASAT 9B",
            "CHINASAT 9C",
            "ZHONGXING-10",
            "ZHONGXING-10R",
            "ZHONGXING-11",
            "CHINASAT 16",  # matches CHINASAT 16 (SJ-13)
            "ZHONGXING-18",  # solar-array anomaly; cataloged
            "ZHONGXING-19",  # ChinaSat 19 (DFH-4E; moved from dfh-5)
            "ZHONGXING-26",  # ChinaSat 26 (DFH-4E; moved from dfh-5)
            "ZHONGXING-1A",
            "ZHONGXING-1C",
            "ZHONGXING-1D",
            "ZHONGXING-1E",
            "ZHONGXING-2A",
            "ZHONGXING-2D",
            "ZHONGXING-2E",
            "ZHONGXING-6A",
            "VENESAT-1",
            "PAKSAT-1R",
            "TKSAT-1",
            "APSTAR-9",
            "APSTAR-6C",
            "APSTAR-6E",
            "APSTAR-6D",  # DFH-4E (moved from dfh-5)
            "LAOSAT 1",  # DFH-4S (moved from dfh-3)
            "BELINTERSAT-1",
            "ALCOMSAT 1",
            "TIANLIAN 2-01",
            "TIANLIAN 2-02",
            "TIANLIAN 2-03",
            "TJS-1",
            "TJS-2",
            # Pruned (Thales Spacebus-4000C2): ChinaSat 9 (= Zhongxing-9), Apstar 7
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
        known_satellites=("SHIJIAN-20",),  # sole operational DFH-5 to date
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
        known_satellites=(
            "SJ-5",  # Shijian-5
            "HAIYANG-1A",
            "HAIYANG-1B",
            "HAIYANG-1C",
            "HAIYANG-2A",
            "DOUBLESTAR TC-1",  # Tan Ce 1
            "DOUBLESTAR TC-2",  # Tan Ce 2
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
        known_satellites=(
            "HJ-1A",
            "HJ-1B",
            "VRSS-1",
            "VRSS-2",
            "GAOFEN-1",
            "GAOFEN-6",
            "ZHANGHENG 1-01",  # Zhangheng-1 / CSES-1
            "HAIYANG-1D",
            "QUEQIAO-2",
            # Tan Ce 1/2 moved to cast968 (Double Star); SJ-6B/6D removed (no such designation)
        ),
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
        known_satellites=(
            "DRTS",
            "ETS-VIII",
            "MTSAT-2",
            "SUPERBIRD-B3",
            "SUPERBIRD-C2",
            "ST-2",
            "QZS-1",
            "QZS-1R",
            "QZS-2",
            "QZS-3",
            "QZS-4",
            "QZS-5",  # 2025 H3 stage-2 failure; not in satcat
            "QZS-6",
            "QZS-7",  # not yet launched; not in satcat
            "TURKSAT 4A",
            "TURKSAT 4B",
            "DSN-2",  # DSN-1 = Superbird-B3 (listed)
            "DSN-3",
            "ES'HAIL 2",
            "HIMAWARI-8",
            "HIMAWARI-9",
        ),
        notes="Carbon-fiber central cylinder, cuboid body, derived from DRTS/ETS-VIII.",
    ),
    SatelliteBusSpec(
        slug="nextar",
        wikidata_qid="Q11234905",
        manufacturer=MANUFACTURER_BY_SLUG["nec"],
        also_known_as=("NX-100L", "NX-300L", "NX-500L", "NX-1500L"),
        first_launch="2014-11-06",
        mass_kg_range=(250, 500),
        known_satellites=(
            "ASNARO",
            "ASNARO-2",
            "LOTUSAT-1",
        ),  # ASNARO = ASNARO-1; LOTUSat-1 not yet launched
        notes="Modular small-sat bus (JAXA/USEF collaboration); SpaceWire + SpaceCube-2 computer.",
    ),
    SatelliteBusSpec(
        slug="i-1k",
        wikidata_qid="Q17028555",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-1000", "I-1000"),
        first_launch="2002-09-12",
        mass_kg_range=(500, 1100),
        known_satellites=(
            "KALPANA-1",
            "GSAT-12",
            "CMS-01",
            "IRNSS-1A",
            "IRNSS-1B",
            "IRNSS-1C",
            "IRNSS-1D",
            "IRNSS-1E",
            "IRNSS-1F",
            "IRNSS-1G",
            "IRNSS-1I",
            "MARS ORBITER MISSION",
            "CHANDRAYAAN-1",
            "ADITYA-L1",
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
        known_satellites=(
            "INSAT-3A",
            "INSAT-3B",
            "INSAT-3C",
            "INSAT-3D",
            "INSAT-3DR",
            "INSAT-3DS",
            "INSAT-3E",
            "GSAT-1",
            "GSAT-2",
            "GSAT-3",
            "GSAT-4",  # GSLV-D3 launch failure 2010; not in satcat
            "GSAT-5P",  # GSLV-F06 launch failure 2010; not in satcat (GSAT-5 phantom removed)
            "GSAT-6",
            "GSAT-6A",
            "GSAT-7",
            "GSAT-7A",
            "GSAT-9",
            "GSAT-14",
            "GSAT-31",
            "HYLAS 1",
        ),
    ),
    SatelliteBusSpec(
        slug="i-3k",
        wikidata_qid="Q17028575",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-3000", "I-3000"),
        first_launch="2005-12-21",
        mass_kg_range=(3000, 3400),
        known_satellites=(
            "INSAT-4A",
            "INSAT-4B",
            "INSAT-4CR",
            "EUTELSAT W2M",  # in-orbit power failure post-launch; not in current satcat
            "GSAT-8",
            "GSAT-10",
            "GSAT-15",
            "GSAT-16",
            "GSAT-17",
            "GSAT-18",
            "GSAT-19",
            "GSAT-29",
            "GSAT-30",
            "GSAT-22",  # not yet launched; not in satcat
            "GSAT-23",  # not yet launched; not in satcat
            "GSAT-24",
        ),
    ),
    SatelliteBusSpec(
        slug="i-4k",
        wikidata_qid="Q16991488",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-4000", "I-4000"),
        first_launch=None,
        known_satellites=("GSAT-20", "GSAT-7R"),
        notes="In development. 4000-6500 kg class, 10-15 kW. Bus assignment varies; check NSIL.",
    ),
    SatelliteBusSpec(
        slug="i-6k",
        wikidata_qid="Q60760760",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("INSAT-6000", "I-6000"),
        first_launch="2018-12-04",
        mass_kg_range=(4000, 6500),
        known_satellites=("GSAT-11",),
        notes="India's heaviest commsat bus, 15 kW DC.",
    ),
    SatelliteBusSpec(
        slug="ims",
        wikidata_qid="Q17056247",
        manufacturer=MANUFACTURER_BY_SLUG["isro"],
        also_known_as=("IMS", "IMS-1", "IMS-2"),
        first_launch="2008-04-28",
        mass_kg_range=(80, 450),
        known_satellites=(
            "IMS-1",
            "MICROSAT-TD",  # IMS-1 demonstrator
            "YOUTHSAT",
            "SARAL",
            "SCATSAT 1",
            "EMISAT",
            "HYSIS",  # IMS-2
            "XPOSAT",  # IMS-2
            "EOS-02",  # SSLV-D1 launch failure 2022; not in satcat
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
        known_satellites=(
            "POEM",  # POEM-1 (cataloged bare as "POEM")
            "POEM-2",
            "POEM-3",
            "POEM-4",
        ),
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
        known_satellites=("RAZAKSAT", "DUBAISAT-1", "DUBAISAT-2", "DEIMOS-2"),
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
        ),
        first_launch="1965",
        mass_kg_range=(800, 2000),
        known_satellites=(
            "MOLNIYA 1",  # whole series (KAUR-1)
            "MOLNIYA 2",
            "MOLNIYA 3",
            "EKRAN 1",
            "EKRAN 2",
            "EKRAN-M",  # decayed; not in current satcat
            "GORIZONT 1",
            "GORIZONT 2",
            "GORIZONT 3",
            "RADUGA 1",
            "RADUGA 2",
            "RADUGA-1",  # distinct Globus/Raduga-1 series (not a dup of Raduga 1)
            "LUCH",
            "POTOK",  # decayed; not in current satcat
        ),
        notes="Soviet 'Universal Spacecraft Series' - 4 generations spanning 1965-2009, 400+ built.",
    ),
    SatelliteBusSpec(
        slug="usp",
        wikidata_qid="Q22084823",
        manufacturer=MANUFACTURER_BY_SLUG["energia"],
        also_known_as=("Universal Space Platform", "\u0423\u041a\u041f", "Viktoria"),
        first_launch="1999-09-06",
        known_satellites=(
            "YAMAL 101",
            "YAMAL 102",
            "YAMAL 201",
            "YAMAL 202",
            "COSMOS 2510",  # EKS-1
            "COSMOS 2518",  # EKS-2
            "COSMOS 2541",  # EKS-3
            "COSMOS 2546",  # EKS-4
            "COSMOS 2552",  # EKS-5
            "COSMOS 2563",  # EKS-6
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
        known_satellites=(
            "MONITOR-E",
            "KAZSAT-1",
            "KAZSAT-2",
            "EXPRESS-MD1",
            "EXPRESS-MD2",
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
        known_satellites=(
            "EXPRESS-AT1",
            "EXPRESS-AT2",
            "EXPRESS-AM5",
            "EUTELSAT 53A",  # Ekspress-AM6 (only cataloged under Eutelsat name)
            "EXPRESS-AM8",
            "EXPRESS 80",
            "EXPRESS 103",
            "GLONASS-K",
            "GLONASS-K2",
            "KAZSAT-3",
            "LUCH-5A",
            "LUCH-5B",
            "LUCH-5V",
            "OLYMP-K",
            "TELKOM 3",
            "YAMAL 300K",
            "YAMAL 401",
            "AMOS-5",
            "COSMOS 2520",
            "COSMOS 2526",
            "COSMOS 2533",
            "COSMOS 2539",
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
        known_satellites=(
            "ELEKTRO-L 1",
            "ELEKTRO-L 2",
            "ELEKTRO-L 3",
            "ELEKTRO-L 4",
            "ELEKTRO-L 5",
            "SPEKTR-R",
            "SPEKTR-RG",
        ),
        notes="Lavochkin modular service module for meteorology and deep space (RadioAstron, Spektr-RG).",
    ),
    SatelliteBusSpec(
        slug="yamal",
        wikidata_qid="Q3656794",
        manufacturer=MANUFACTURER_BY_SLUG["energia"],
        also_known_as=("\u042f\u043c\u0430\u043b",),
        first_launch="1999-09-06",
        known_satellites=(),  # series, not a bus: members live on usp / ekspress / spacebus-4000
        notes="Yamal name refers to the satellite series (Gazprom Space Systems); hardware built "
        "on USP (Energia), Ekspress-2000 (Reshetnev), and Spacebus-4000 (Thales) platforms. "
        "Wikipedia article is about the series, not a distinct bus. "
        "Yamal 101/102/201/202 -> usp; 300K/401 -> ekspress; 402/601 -> spacebus-4000.",
    ),
    # ---------- Other / misc ----------
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
        known_satellites=(
            "INTELSAT 24",  # AMOS-1 (transferred to Intelsat)
            "AMOS-2",
            "AMOS-3",
            "AMOS-4",
            "AMOS 6",  # lost in 2016 Falcon 9 pad explosion; never reached orbit
            "DROR 1",
        ),
        notes="IAI GEO commsat family derived from Ofeq. AMOS-5 is ISS Reshetnev; AMOS-17 is "
        "reportedly Boeing 702MP per Wikipedia (sources conflict); AMOS-6 lost pre-launch 2016.",
    ),
    SatelliteBusSpec(
        slug="arsat-3k",
        wikidata_qid="Q22084804",
        manufacturer=MANUFACTURER_BY_SLUG["invap"],
        first_launch="2014-10-16",
        mass_kg_range=(2900, 3000),
        known_satellites=(
            "ARSAT 1",
            "ARSAT 2",
            "ARSAT-SG1",
        ),  # ARSAT-SG1 not yet in satcat
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
        known_satellites=(
            "LATINSAT A",
            "LATINSAT B",
            # LatinSat C/D = AprizeSat 1/2; exactView 3/4/5/5R/6/11/12/13 = AprizeSat 3/4/5/7/6/9/8/10
            "APRIZESAT 1",
            "APRIZESAT 2",
            "APRIZESAT 3",
            "APRIZESAT 4",
            "APRIZESAT 5",
            "APRIZESAT 6",
            "APRIZESAT 7",
            "APRIZESAT 8",
            "APRIZESAT 9",
            "APRIZESAT 10",
        ),
        notes="US microsat bus (~12-14 kg) for AIS/M2M. Now AAC SpaceQuest (since 2020).",
    ),
    SatelliteBusSpec(
        slug="arkyd-3",
        wikidata_qid="Q18520405",
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Arkyd 3", "Arkyd-3R"),
        first_launch="2015-04-14",
        mass_kg_range=(4, 5),
        known_satellites=(
            "ARKYD 3",
            "ARKYD-3R",
        ),  # Arkyd 3 lost in 2014 Antares failure; not in satcat
        notes="3U CubeSat testbed for larger Arkyd-100. Arkyd 3 lost in Antares Orb-3 failure (2014); "
        "Arkyd 3R deployed from ISS 2015.",
    ),
    SatelliteBusSpec(
        slug="arkyd-100",
        wikidata_qid="Q25449222",
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Leo Space Telescope", "Ceres"),
        first_launch=None,
        mass_kg_range=(11, 15),
        notes="Planned LEO space telescope; only ground-test prototypes; cancelled after 2018 ConsenSys acquisition.",
    ),
    SatelliteBusSpec(
        slug="arkyd-200",
        wikidata_qid=None,  # Q17620827 is the generic "Arkyd" series item, not the 200; no dedicated item
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Interceptor",),
        first_launch=None,
        notes="Planned asteroid interceptor; full-size prototype built 2016; never launched.",
    ),
    SatelliteBusSpec(
        slug="arkyd-300",
        wikidata_qid=None,  # Q17620827 is the generic "Arkyd" series item, not the 300; no dedicated item
        manufacturer=MANUFACTURER_BY_SLUG["planetary-resources"],
        also_known_as=("Rendezvous Prospector", "Arkyd-301"),
        first_launch=None,
        notes="Concept only; cancelled 2018.",
    ),
    SatelliteBusSpec(
        slug="mcsb",
        wikidata_qid="Q6889690",
        manufacturer=MANUFACTURER_BY_SLUG["nasa-ames"],
        also_known_as=("MCSB",),
        first_launch="2013-09-06",
        known_satellites=("LADEE",),
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
        known_satellites=(
            "RLFL14",  # First Light / Photon 01
            "CAPSTONE",
            "PHOTON-02",  # Pathstone
            "ESCAPADE BLUE",
            "ESCAPADE GOLD",
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
        known_satellites=("OE (NEXTSAT)", "NEOWISE", "SPHEREX (MIDEX 9)"),
        notes="Small low-cost LEO bus; ASPEN avionics from Deep Impact heritage. "
        "Succeeded/renamed to BCP-300. Now BAE Systems Space & Mission Systems (2024).",
    ),
)


BUS_BY_SLUG: dict[str, SatelliteBusSpec] = {b.slug: b for b in SATELLITE_BUSES}
assert len(BUS_BY_SLUG) == len(SATELLITE_BUSES), "Duplicate bus slug"


# Precompiled word-boundary patterns for each known_satellites entry, sorted by
# descending match length (ties broken by declaration order) so the first hit
# during lookup is the longest — and therefore most specific — match.
_ENTRY_PATTERNS: tuple[tuple[re.Pattern[str], SatelliteBusSpec], ...] = tuple(
    (pat, bus)
    for pat, _, _, bus in sorted(
        (
            (
                re.compile(r"(?<![0-9A-Z])" + re.escape(sat.upper()) + r"(?![0-9A-Z])"),
                len(sat),
                bus_idx,
                bus,
            )
            for bus_idx, bus in enumerate(SATELLITE_BUSES)
            for sat in bus.known_satellites
        ),
        key=lambda e: (-e[1], e[2]),
    )
)


def bus_for_satellite(object_name: str) -> SatelliteBusSpec | None:
    """Look up the bus for a SATCAT/TLE OBJECT_NAME.

    Matches known_satellites entries as word-boundary substrings of OBJECT_NAME,
    preferring the longest match (ties broken by declaration order).
    """
    normalized = object_name.strip().upper()
    for pat, bus in _ENTRY_PATTERNS:
        if pat.search(normalized):
            return bus
    return None


def buses_by_manufacturer(manufacturer_qid: str) -> tuple[SatelliteBusSpec, ...]:
    return tuple(
        b for b in SATELLITE_BUSES if b.manufacturer.wikidata_qid == manufacturer_qid
    )
