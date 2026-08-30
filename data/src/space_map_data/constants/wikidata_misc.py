"""Wikidata topic pages that belong to no single constants package.

Geology, exploration, magnetic fields and the physical quantities the stat
cards name. Grouped by the panel they read against, not by subject.

Values are tuples because a topic occasionally splits across two Wikidata
items with disjoint sitelinks. No locale falls back to English — a reader
gets the article in their language or no link, so the coverage comment on
each row is the whole story.

Locale codes follow ``constants.providers.LANGUAGES``; "all 12" means all of
them. Coverage drifts as Wikidata articles are written or merged — comments
are as of 2026-07-31.
"""

MISC_PAGES: dict[str, tuple[str, ...]] = {
    # Geology, for the surface panel.
    "geology_moon": ("Q1648514",),  # geology of the Moon — all 12
    "geology_mercury": ("Q1207482",),  # geology of Mercury — en fr ja zh ar pt it es
    "geology_venus": ("Q2089244",),  # geology of Venus — en fr zh ar ru pt it es
    "geology_mars": ("Q2466",),  # geology of Mars — en fr zh ar ru pt it es pl
    "geology_titan": ("Q128693316",),  # geology of Titan — en
    "geology_pluto": ("Q20678700",),  # geology of Pluto — en fr zh ar es
    "geology_ceres": ("Q25338527",),  # geology of Ceres — en zh ar pt
    # planetary geology — en fr ja zh ar ru pt de it es pl
    "planetary_geology": ("Q751439",),
    "selenography": ("Q1409625",),  # selenography — en fr ja zh ar ru pt de it es pl
    "areography": ("Q128621",),  # areography — en fr zh ar ru pt de it es
    "lunar_mare": ("Q180874",),  # lunar mare — all 12
    "regolith": ("Q106551",),  # regolith — all 12
    # space weathering — en fr zh ar ru pt de it es
    "space_weathering": ("Q1570174",),
    # Impact crater (Q55818) and planetary nomenclature (Q1463003) belong here
    # by subject but are already declared as group QIDs — FEATURE_TYPES["AA"]
    # (ft-crater) and CATEGORIES (cat-surface-features) — so they resolve
    # through their own pages instead.
    # Volcanism and seismology.
    "volcanism_io": ("Q3096",),  # volcanology of Io — en fr ja zh ar ru pt de it es
    "volcanism_mars": ("Q2293383",),  # volcanology of Mars — en fr zh ar ru pt es
    "volcanism_venus": ("Q2787452",),  # volcanology of Venus — en fr zh ar ru es
    "volcanism_moon": ("Q104903321",),  # volcanism on the Moon — en es
    "cryovolcano": ("Q478788",),  # cryovolcano — en fr ja zh ar ru pt de it es pl
    "marsquake": ("Q59310748",),  # marsquake — en fr zh ru pt de es
    "lunar_seismology": ("Q6703832",),  # lunar seismology — en zh
    "tiger_stripes": ("Q1048973",),  # Tiger Stripes — en fr zh pt it
    # Magnetic fields — the one panel-adjacent topic with no data of ours.
    "magnetosphere": ("Q6915",),  # magnetosphere — all 12
    "magnetic_field_earth": ("Q6500960",),  # Earth's magnetic field — all 12
    # Mercury's magnetic field — en fr zh ar it
    "magnetic_field_mercury": ("Q1752971",),
    # magnetic field of the Moon — en ja ru pt de es
    "magnetic_field_moon": ("Q1037706",),
    "magnetic_field_mars": ("Q109018131",),  # Martian magnetic field — en fr
    # magnetosphere of Jupiter — en fr zh ar ru pt it es
    "magnetosphere_jupiter": ("Q3041",),
    "magnetosphere_saturn": ("Q2334004",),  # magnetosphere of Saturn — en fr zh ar it
    # Water, ice and habitability.
    "water_mars": ("Q1985733",),  # water on Mars — en fr zh ar ru pt es
    "water_venus": ("Q126008757",),  # water on Venus — en
    "lunar_water": ("Q1037506",),  # lunar water — en fr ja ar ru pt it es
    "titan_lakes": ("Q1925406",),  # lakes of Titan — en fr zh ar ru pt de it es pl
    "life_mars": ("Q601319",),  # life on Mars — en fr ja zh ar ru pt de it es he
    "life_venus": ("Q2582723",),  # life on Venus — en fr zh ar ru pt de it es pl
    "life_titan": ("Q2591050",),  # life on Titan — en fr ja zh ar ru pt de it
    "habitable_zone": ("Q215913",),  # circumstellar habitable zone — all 12
    "frost_line": ("Q590180",),  # frost line — en fr ja zh ru pt de it es he pl
    "sublimation": ("Q131800",),  # sublimation — all 12
    # Exploration, for the mission panel.
    # "Exploration of X" moved to constants.spacecraft.wikidata, keyed by body.
    # Discovery panel.
    # discovery of Neptune — en fr ja zh ar ru it es he
    "discovery_neptune": ("Q1356165",),
    # timeline of Solar System discovery — en fr ja zh ar ru pt de it es pl
    "discovery_timeline": ("Q37642",),
    "naming_of_moons": ("Q835598",),  # naming of moons — en ja zh ar es
    # Orbital panel.
    # orbit of the Moon — en fr ja zh ar ru pt de it es pl
    "orbit_moon": ("Q210539",),
    "orbit_mars": ("Q3895208",),  # orbit of Mars — en zh ar de it
    "orbit_venus": ("Q3895220",),  # orbit of Venus — en it es
    "orbit_earth": ("Q1348808",),  # orbit of Earth — en fr zh ar ru pt de it es pl
    # Earth's rotation — en fr ja zh ar ru pt de es he pl
    "earth_rotation": ("Q244743",),
    "solar_rotation": ("Q1724743",),  # solar rotation — en fr zh ar ru pt de it es
    # escape velocity — en fr ja zh ar ru pt it es he pl
    "escape_velocity": ("Q166530",),
    "hill_sphere": ("Q498792",),  # Hill sphere — all 12
    "tidal_locking": ("Q109144",),  # tidal locking — all 12
    "tidal_force": ("Q223325",),  # tidal force — all 12
    "axial_tilt": ("Q179745",),  # axial tilt — en fr ja zh ar ru pt de it es he
    "kirkwood_gap": ("Q318541",),  # Kirkwood gap — en fr ja zh ar ru pt de it es pl
    "asteroid_family": ("Q249083",),  # asteroid family — all 12
    # Bulk panel.
    "density": ("Q29539",),  # mass density — all 12
    "planetary_mass": ("Q12989628",),  # planetary mass — en ar es
    "surface_gravity": ("Q1758384",),  # surface gravity — en fr ja zh ar ru it
    # standard gravitational parameter — en fr ja zh ar ru pt de it es pl
    "standard_gravitational_parameter": ("Q579338",),
    "flattening": ("Q212750",),  # flatness — en fr ja zh ar ru pt it es he pl
    "equatorial_bulge": ("Q1440352",),  # equatorial bulge — en zh ar ru de it es
    # standard asteroid characteristics — en zh ar ru pt
    "asteroid_physical_characteristics": ("Q1090860",),
    # Temperature panel.
    # planetary equilibrium temperature — en fr zh ar ru pt de it es
    "equilibrium_temperature": ("Q1530267",),
    # effective temperature — en fr ja zh ar ru pt de it es pl
    "effective_temperature": ("Q854050",),
    "surface_temperature": ("Q50767635",),  # surface temperature — en
    "black_body": ("Q161424",),  # black body — all 12
    "thermal_inertia": ("Q131938963",),  # thermal inertia — en zh
    "tidal_heating": ("Q7800788",),  # tidal heating — en fr zh ar ru pt de es
    "solar_irradiance": ("Q1531731",),  # solar irradiance — en fr zh ar pt de es
    "climate_mars": ("Q2587227",),  # climate of Mars — en fr zh ar ru pt it es
    "aurora_mars": ("Q111915834",),  # aurora on Mars — en
    # Brightness panel.
    "albedo": ("Q101038",),  # albedo — all 12
    "geometric_albedo": ("Q2832068",),  # geometric albedo — en fr ja zh ar pt it es
    "bond_albedo": ("Q2731139",),  # Bond albedo — en fr ja zh ar pt it es
    "absolute_magnitude": ("Q159653",),  # absolute magnitude — all 12
    "apparent_magnitude": ("Q124313",),  # apparent magnitude — all 12
    "phase_curve": ("Q7180945",),  # phase curve — en pt
    "phase_angle": ("Q2059855",),  # phase angle — en fr ja zh ar ru pt es
    # opposition surge — en fr ja zh ru pt de es pl
    "opposition_surge": ("Q2027206",),
}
