"""Curated promoted-body IDs.

A "promoted" body shows up labeled on the map before the user interacts —
rendered as an individual mesh rather than a point in a cloud. Two sources
combine into the runtime promoted set:

* All planets, dwarf planets, moons, stars, barycenters, and Lagrange points,
  picked up automatically by object type.
* The hand-picked spacecraft / satellites / asteroids / comets below — bodies
  that aren't in any of those categories but are interesting enough to surface
  on first paint (visited targets, hazardous NEOs, famous comets, flagship
  probes).

The frontend used to own this list; it now reads it from the
``/v1/labels/{lang}.gz`` files (whose keys are exactly the promoted set).
"""

from space_map_data.models.object import ObjectType

PROMOTED_TYPES: frozenset[ObjectType] = frozenset(
    {
        ObjectType.planet,
        ObjectType.dwarf_planet,
        ObjectType.moon,
        ObjectType.star,
        ObjectType.barycenter,
        ObjectType.lagrange_point,
    }
)


PROMOTED_EXTRA_IDS: frozenset[str] = frozenset(
    {
        # Spacecraft: deep space
        "probe-49065984",  # Voyager 1   (mission VOYAGER, naif -31)
        "probe-49000448",  # Voyager 2   (mission VOYAGER, naif -32)
        "probe-40910848",  # Pioneer 10  (mission PIONEER10, naif -23)
        "probe-42479616",  # Pioneer 11  (mission PIONEER11, naif -24)
        "probe-104804352",  # New Horizons (mission NEWHORIZONS, naif -98)
        "probe-115347456",  # JWST        (mission JWST, naif -170)
        "probe-120614912",  # Lucy        (mission LUCY, naif -49)
        "probe-118050816",  # Psyche      (mission PSYCHE, naif -255)
        "probe-110526464",  # BepiColombo (mission BEPICOLOMBO, naif -121)
        "probe-112545792",  # Solar Orbiter (mission SOLAR-ORBITER, naif -144)
        "probe-117293056",  # JUICE       (mission JUICE, naif -28)
        "probe-92659712",  # STEREO-A    (mission STEREO, naif -234)
        "probe-68640768",  # Ulysses     (mission ULYSSES, naif -55)
        "probe-119513088",  # Hera        (mission HERA, naif -91)
        "probe-107159552",  # Juno        (mission JUNO, naif -61)
        "probe-89325568",  # MESSENGER   (mission MESSENGER, naif -236)
        "probe-103354368",  # Gaia        (mission GAIA, naif -123)
        "probe-119541760",  # Europa Clipper (mission EUROPACLIPPER, naif -159)
        "probe-110309376",  # Parker Solar Probe (mission HORIZONS-SYNTH, naif -96)
        "probe-107429888",  # OSIRIS-REx  (mission ORX, naif -64)
        "probe-112156672",  # Hayabusa 2  (mission HYB2, naif -37)
        "probe-96198656",  # Kepler      (mission HORIZONS-SYNTH, naif -227)
        "probe-76357632",  # SOHO        (mission HORIZONS-SYNTH, naif -21)
        "probe-105070592",  # DSCOVR      (mission EVENTS-DB, naif -90000220)
        "probe-117612544",  # Euclid      (mission EUCLID, naif -680)
        # Small-body visitors (sample-return / impactor)
        "probe-90976256",  # Hayabusa 1  (mission HAYABUSA, naif -130; visited Itokawa)
        "probe-89989120",  # Deep Impact (mission DEEPIMPACT, naif -140; visited Tempel 1)
        "probe-115220480",  # DART        (mission DART, naif -135; impacted Didymos)
        # Venus orbiters
        "probe-80683008",  # Magellan    (mission EVENTS-DB, naif -90000036)
        "probe-111718401",  # Akatsuki    (mission HORIZONS-SYNTH, naif -152)
        # Mars / planetary orbiters & landers
        "probe-93536256",  # Mars Express (mission MEX, naif -41)
        "probe-84353024",  # Mars Odyssey (mission M01, naif -53)
        "probe-90857472",  # MRO         (mission MRO, naif -74)
        "probe-100265984",  # MSL Curiosity (mission MSL, naif -76)
        "probe-109281280",  # ExoMars 2016 TGO (mission EXOMARS2016, naif -143)
        "probe-109899776",  # InSight     (mission INSIGHT, naif -189)
        "probe-107151360",  # Tianwen-1   (mission HORIZONS-SYNTH, naif -86)
        "probe-96616448",  # LRO         (mission LRO, naif -85)
        "probe-88592384",  # Cassini     (mission CASSINI, naif -82)
        "probe-76308480",  # Galileo     (mission GLL, naif -77)
        "probe-89915392",  # Huygens     (mission HUYGENS, naif -150)
        "probe-88698880",  # Rosetta     (mission HORIZONS-SYNTH, naif -226)
        # Apollo program — trajectories (APOLLO mission) + EVENTS-DB markers.
        # EVENTS-DB IDs identified by inception_mjd → launch date.
        "probe-39936000",  # Apollo 15 traj (mission APOLLO, naif -915)
        "probe-41050112",  # Apollo 16 PFS-1 subsatellite (mission APOLLO, naif -916300)
        "probe-36040704",  # Apollo 8
        "probe-36040705",  # Apollo 8
        "probe-36646912",  # Apollo 10
        "probe-36646913",  # Apollo 10
        "probe-36663296",  # Apollo 10
        "probe-36663297",  # Apollo 10
        "probe-36888576",  # Apollo 11
        "probe-36888577",  # Apollo 11
        "probe-36904960",  # Apollo 11
        "probe-36909056",  # Apollo 11
        "probe-37384192",  # Apollo 12
        "probe-37384193",  # Apollo 12
        "probe-37404672",  # Apollo 12
        "probe-37408768",  # Apollo 12
        "probe-37990400",  # Apollo 13
        "probe-37990401",  # Apollo 13
        "probe-37990402",  # Apollo 13
        "probe-39198720",  # Apollo 14
        "probe-39202816",  # Apollo 14
        "probe-39219200",  # Apollo 14
        "probe-39223296",  # Apollo 14
        "probe-39919616",  # Apollo 15
        "probe-39919617",  # Apollo 15
        "probe-39936001",  # Apollo 15
        "probe-39948288",  # Apollo 15
        "probe-41005056",  # Apollo 16
        "probe-41005057",  # Apollo 16
        "probe-41021440",  # Apollo 16
        "probe-41037824",  # Apollo 16
        "probe-41967616",  # Apollo 17
        "probe-41967617",  # Apollo 17
        "probe-41984000",  # Apollo 17
        "probe-41996288",  # Apollo 17
        # Retired
        "probe-112132096",  # Spitzer Space Telescope (mission SIRTF, naif -79)
        "probe-101912576",  # Dawn (mission DAWN, naif -203)
        # Earth-orbiting (NORAD/CelesTrak TLEs). Daily SGP4 elements cover
        # the expected lifespan — these are sats, never probes.
        "norad_satcat-20580",  # HST (Hubble)
        "norad_satcat-25544",  # ISS (Zarya)
        "norad_satcat-48274",  # CSS Tianhe (Tiangong)
        # TESS and CXO have SPICE kernels and land in the probe namespace.
        "probe-109834240",  # TESS (mission HORIZONS-SYNTH, naif -95)
        "probe-81858560",  # Chandra X-ray Observatory (mission CHANDRA, naif -151)
        # Asteroids (visited, hazardous, or otherwise famous)
        "spkid-20000002",  # 2 Pallas
        "spkid-20000003",  # 3 Juno
        "spkid-20000004",  # 4 Vesta
        "spkid-20000010",  # 10 Hygiea
        "spkid-20000016",  # 16 Psyche
        "spkid-20000130",  # 130 Elektra - 3 moons
        "spkid-20000243",  # 243 Ida
        "spkid-20000253",  # 253 Mathilde
        "spkid-20000433",  # 433 Eros
        "spkid-20000511",  # 511 Davida
        "spkid-20000588",  # 588 Achilles
        "spkid-20000624",  # 624 Hektor
        "spkid-20000704",  # 704 Interamnia
        "spkid-20000951",  # 951 Gaspra
        "spkid-20001862",  # 1862 Apollo
        "spkid-20002060",  # 2060 Chiron
        "spkid-20004179",  # 4179 Toutatis
        "spkid-20010199",  # 10199 Chariklo
        "spkid-20025143",  # 25143 Itokawa
        "spkid-20047171",  # 47171 Lempo
        "spkid-20065803",  # 65803 Didymos
        "spkid-20099942",  # 99942 Apophis
        "spkid-20101955",  # 101955 Bennu
        "spkid-20162173",  # 162173 Ryugu
        "spkid-20486958",  # 486958 Arrokoth
        # Interstellar objects
        "spkid-3788040",  # 1I/ʻOumuamua
        "spkid-1003639",  # C/2019 Q4 (Borisov)
        "spkid-1004083",  # C/2025 N1 (ATLAS)
        # Comets
        "spkid-1000036",  # 1P/Halley
        "spkid-1000025",  # 2P/Encke
        "spkid-1000093",  # 9P/Tempel 1
        "spkid-1000109",  # 46P/Wirtanen
        "spkid-1000012",  # 67P/Churyumov-Gerasimenko
        "spkid-1000107",  # 81P/Wild 2
        "spkid-1000041",  # 103P/Hartley 2
        "spkid-1000132",  # C/1995 O1 (Hale-Bopp)
        # Great comets (non-periodic)
        "spkid-1000738",  # Great Comet of 1807
        "spkid-1000742",  # Great Comet of 1811
        "spkid-1000749",  # Great Comet of 1819
        "spkid-1000755",  # Great Comet of 1823  # TODO check defunct
        "spkid-1000778",  # Great Comet of 1843
        "spkid-1000845",  # Great Southern Comet of 1865
        "spkid-1000872",  # Great Southern Comet of 1880
        "spkid-1000882",  # Great Comet of 1882
        "spkid-1000899",  # Great Southern Comet of 1887
        "spkid-1000945",  # Great Comet of 1901
        "spkid-1000967",  # Great January Comet of 1910
        "spkid-1001121",  # Comet Ikeya–Seki
        "spkid-1003162",  # C/2011 W3 (Lovejoy)
        "spkid-1003667",  # C/2020 F3 (NEOWISE)
        "spkid-1003913",  # C/2023 A3 (Tsuchinshan-ATLAS)
        # no wikidata match
        "spkid-1000592",  # C/390 Q1
        "spkid-1000616",  # Great Comet of 1264
        "spkid-1000630",  # Great Comet of 1402
        "spkid-1000639",  # Great Comet of 1472
        "spkid-1000648",  # Great Comet of 1556
        "spkid-1000651",  # Great Comet of 1577
        "spkid-1000669",  # Great Comet of 1680
        "spkid-1000690",  # Great Comet of 1744
    }
)
