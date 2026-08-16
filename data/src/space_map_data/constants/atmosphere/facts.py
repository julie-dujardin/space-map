"""Per-body atmospheric facts for the object panel's stat block.

Separate from `bodies.py` on purpose: that table states each atmosphere at
the level the shell renders from (Venus's cloud top, the giants' visible
deck), while these are the numbers a reader expects — surface pressure where
there is one — each with its own citation rather than a render tuning behind
it.

Re-checked against the cited source rather than carried over from the
compiled dataset this started as; corrections are noted inline. NSSDCA fact
sheets were read from Internet Archive snapshots (offline since early 2025),
so their numbers are the 2024-2025 editions. Nothing here feeds rendering.
"""

from typing import NamedTuple


# `composition_unit` values. Thin envelopes have no mixing ratio — each species
# is its own measurement, so shares of a column or number density are as close
# to a composition as the observations get.
VOLUME_FRACTION = "volume_fraction"
MASS_FRACTION = "mass_fraction"
COLUMN_DENSITY = "column_density"
NUMBER_DENSITY = "number_density"

COMPOSITION_UNITS = frozenset(
    {VOLUME_FRACTION, MASS_FRACTION, COLUMN_DENSITY, NUMBER_DENSITY}
)

# `Pressure.level` values — what the number is quoted against. The frontend
# turns each into a row label.
PRESSURE_LEVELS = frozenset(
    {"surface", "sea_level", "areoid", "cloud_top", "one_bar", "photosphere"}
)

# `Pressure.qualifier` values — shown as a tag next to the atmosphere type.
QUALIFIERS = frozenset({"upper_limit", "approximate", "variable"})

# `BodyFacts.note` values — the reason behind the classification, where that
# is the interesting half (why Io's atmosphere snows out every eclipse, why
# Pluto's follows its orbit). Frontend turns each into a translatable sentence.
NOTES = frozenset(
    {
        "surface_bounded",
        "sputtered_ice",
        "volcanic",
        "seasonal_cap",
        "seasonal_orbit",
        "frozen_out",
        "no_detection",
        "plume",
        "transient_vapour",
        "no_surface",
        "photosphere",
    }
)

# `BodyFacts.atmosphere_type` values, roughly ordered thick to absent.
ATMOSPHERE_TYPES = frozenset(
    {
        "stellar_atmosphere",
        "gas_giant_envelope",
        "thick_atmosphere",
        "thin_atmosphere",
        "tenuous_collisional",
        "tenuous_exosphere",
        "exosphere",
        "transient_exosphere",
        "localized_plume",
        "frozen_collapsed",
        "none_detected",
    }
)


class Species(NamedTuple):
    """One gas, in its body's `composition_unit`. Values are never mixed
    between units within a body — a share is only meaningful against like."""

    formula: str
    value: float
    source: str
    # A non-detection limit, not an abundance — kept in the bar (the best
    # number there is), but the panel says so.
    upper_limit: bool = False


class Pressure(NamedTuple):
    pascals: float
    level: str
    source: str
    qualifier: str | None = None


class BodyFacts(NamedTuple):
    atmosphere_type: str
    composition_unit: str
    composition: tuple[Species, ...]
    pressure: Pressure | None = None
    # Backs the type tag where no pressure or species citation already does —
    # non-detections are a claim about the body too.
    type_source: str | None = None
    note: str | None = None


ATMOSPHERE_FACTS: dict[str, BodyFacts] = {
    # Sun. Photospheric gas pressure is NSSDCA's optical-depth-1 value (125 mb);
    # the 0.868 mb row on the same sheet is the photosphere's *top*. Abundances
    # are by mass, so the bar reads differently from every other body here —
    # by number the photosphere is ~91% H, ~9% He.
    "naif-10": BodyFacts(
        atmosphere_type="stellar_atmosphere",
        composition_unit=MASS_FRACTION,
        composition=(
            Species("H", 0.7346, "stanford_solar"),
            Species("He", 0.2485, "stanford_solar"),
            Species("O", 0.0077, "stanford_solar"),
            Species("C", 0.0029, "stanford_solar"),
            Species("Fe", 0.0016, "stanford_solar"),
            Species("Ne", 0.0012, "stanford_solar"),
            Species("N", 0.0009, "stanford_solar"),
            Species("Si", 0.0007, "stanford_solar"),
        ),
        pressure=Pressure(1.25e4, "photosphere", "nssdc_sun", "approximate"),
        note="photosphere",
    ),
    # Mercury. Everything here is a column abundance from a different campaign;
    # NSSDCA tabulates them "in 10^6 per cm2", which is where the compiled
    # source this started from lost a decade on sodium. He has no NSSDCA row at
    # all — the number is Wikipedia's non-detection limit.
    "naif-199": BodyFacts(
        atmosphere_type="exosphere",
        composition_unit=COLUMN_DENSITY,
        composition=(
            Species("He", 3.0e11, "wiki_mercury_atm", upper_limit=True),
            Species("Mg", 1.0e11, "nssdc_mercury"),
            Species("O", 4.0e10, "nssdc_mercury", upper_limit=True),
            Species("Na", 1.2e10, "nssdc_mercury"),
            # NSSDCA's "Hydrogen" row is atomic H; the H₂ column is six orders
            # away and was a species mix-up in the compiled source.
            Species("H", 5.0e9, "nssdc_mercury"),
            Species("K", 8.0e8, "nssdc_mercury"),
            Species("Ca", 1.1e8, "wiki_mercury_atm"),
        ),
        pressure=Pressure(5.0e-10, "surface", "nssdc_mercury", "upper_limit"),
        note="surface_bounded",
    ),
    # Venus at the surface — the 92 bar, 737 K floor, not the ~0.1 bar cloud
    # top the shell is rendered from.
    "naif-299": BodyFacts(
        atmosphere_type="thick_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("CO2", 0.965, "nssdc_venus"),
            Species("N2", 0.035, "nssdc_venus"),
            Species("SO2", 1.5e-4, "nssdc_venus"),
            Species("Ar", 7.0e-5, "nssdc_venus"),
            Species("H2O", 2.0e-5, "nssdc_venus"),
            Species("CO", 1.7e-5, "nssdc_venus"),
            Species("He", 1.2e-5, "nssdc_venus"),
            Species("Ne", 7.0e-6, "nssdc_venus"),
        ),
        pressure=Pressure(9.2e6, "surface", "nssdc_venus"),
    ),
    # Earth. NSSDCA's fractions are dry air; water vapour is additive and
    # swings from near zero to ~5%, so the 1% here is an average, not a slot in
    # the same accounting as the rest.
    "naif-399": BodyFacts(
        atmosphere_type="thin_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("N2", 0.7808, "nssdc_earth"),
            Species("O2", 0.2095, "nssdc_earth"),
            Species("H2O", 0.01, "nssdc_earth"),
            Species("Ar", 9.34e-3, "nssdc_earth"),
            Species("CO2", 4.2e-4, "nssdc_earth"),
            Species("Ne", 1.818e-5, "nssdc_earth"),
            Species("He", 5.24e-6, "nssdc_earth"),
            Species("CH4", 1.94e-6, "nssdc_earth"),
            Species("Kr", 1.14e-6, "nssdc_earth"),
            Species("H2", 5.5e-7, "nssdc_earth"),
        ),
        pressure=Pressure(1.014e5, "sea_level", "nssdc_earth"),
    ),
    # Mars. 636 Pa is NSSDCA's mean-radius surface value; the areoid datum is
    # defined at 610.5 Pa, and the seasonal swing is ±25% as CO₂ freezes out
    # onto the winter cap.
    "naif-499": BodyFacts(
        atmosphere_type="thin_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("CO2", 0.951, "nssdc_mars"),
            Species("N2", 0.0259, "nssdc_mars"),
            Species("Ar", 0.0194, "nssdc_mars"),
            Species("O2", 1.6e-3, "nssdc_mars"),
            Species("CO", 6.0e-4, "nssdc_mars"),
            Species("H2O", 2.1e-4, "nssdc_mars"),
            Species("NO", 1.0e-4, "nssdc_mars"),
            Species("Ne", 2.5e-6, "nssdc_mars"),
            Species("HDO", 8.5e-7, "nssdc_mars"),
            Species("Kr", 3.0e-7, "nssdc_mars"),
            Species("Xe", 8.0e-8, "nssdc_mars"),
            Species("CH4", 4.0e-10, "webster_2018"),
        ),
        pressure=Pressure(636.0, "surface", "nssdc_mars", "variable"),
        note="seasonal_cap",
    ),
    # Jupiter at the 0.1 bar deck — the level the banding people see sits at,
    # and the one the giants' "cloud tops" means. He is the Galileo probe
    # value (von Zahn et al. 1998); NSSDCA still carries the Voyager-era 10.2%.
    "naif-599": BodyFacts(
        atmosphere_type="gas_giant_envelope",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("H2", 0.861, "von_zahn_1998"),
            Species("He", 0.136, "von_zahn_1998"),
            Species("CH4", 3.0e-3, "nssdc_jupiter"),
            Species("NH3", 2.6e-4, "nssdc_jupiter"),
            Species("HD", 2.8e-5, "nssdc_jupiter"),
            Species("C2H6", 5.8e-6, "nssdc_jupiter"),
            Species("H2O", 4.0e-6, "nssdc_jupiter"),
        ),
        pressure=Pressure(1.0e4, "cloud_top", "nssdc_jupiter"),
        note="no_surface",
    ),
    # Saturn, 0.1 bar. He is genuinely unsettled — Voyager IRIS 3.25%
    # (NSSDCA's row), Conrath & Gautier 2000 He/H₂ = 0.11-0.16, Cassini CIRS
    # ~5%; the mid Conrath & Gautier value is used here and in the renderer.
    "naif-699": BodyFacts(
        atmosphere_type="gas_giant_envelope",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("H2", 0.877, "conrath_gautier_2000"),
            Species("He", 0.118, "conrath_gautier_2000"),
            Species("CH4", 4.5e-3, "nssdc_saturn"),
            Species("NH3", 1.25e-4, "nssdc_saturn"),
            Species("HD", 1.1e-4, "nssdc_saturn"),
            Species("C2H6", 7.0e-6, "nssdc_saturn"),
        ),
        pressure=Pressure(1.0e4, "cloud_top", "nssdc_saturn"),
        note="no_surface",
    ),
    # Uranus, 0.1 bar. CH₄ 2.3% is the occultation nominal above the cloud;
    # the deep value is latitude-dependent (Karkoschka & Tomasko 2009).
    "naif-799": BodyFacts(
        atmosphere_type="gas_giant_envelope",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("H2", 0.825, "nssdc_uranus"),
            Species("He", 0.152, "nssdc_uranus"),
            Species("CH4", 0.023, "nssdc_uranus"),
            Species("HD", 1.48e-4, "nssdc_uranus"),
        ),
        pressure=Pressure(1.0e4, "cloud_top", "nssdc_uranus"),
        note="no_surface",
    ),
    # Neptune, 0.1 bar.
    "naif-899": BodyFacts(
        atmosphere_type="gas_giant_envelope",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("H2", 0.80, "nssdc_neptune"),
            Species("He", 0.19, "nssdc_neptune"),
            Species("CH4", 0.015, "nssdc_neptune"),
            Species("HD", 1.92e-4, "nssdc_neptune"),
            Species("C2H6", 1.5e-6, "nssdc_neptune"),
        ),
        pressure=Pressure(1.0e4, "cloud_top", "nssdc_neptune"),
        note="no_surface",
    ),
    # The Moon. NSSDCA's nighttime densities are explicitly upper-limit
    # estimates; sodium and potassium are daytime values from a different
    # instrument, so this list is a ranking of separate measurements rather
    # than one snapshot of a mixture.
    "naif-301": BodyFacts(
        atmosphere_type="exosphere",
        composition_unit=NUMBER_DENSITY,
        composition=(
            Species("He-4", 4.0e4, "nssdc_moon", upper_limit=True),
            Species("Ne-20", 4.0e4, "nssdc_moon", upper_limit=True),
            Species("H2", 3.5e4, "nssdc_moon", upper_limit=True),
            Species("Ar-40", 3.0e4, "nssdc_moon", upper_limit=True),
            Species("Ne-22", 5.0e3, "nssdc_moon", upper_limit=True),
            Species("Ar-36", 2.0e3, "nssdc_moon", upper_limit=True),
            Species("CH4", 1.0e3, "nssdc_moon", upper_limit=True),
            Species("NH3", 1.0e3, "nssdc_moon", upper_limit=True),
            Species("CO2", 1.0e3, "nssdc_moon", upper_limit=True),
            Species("Na", 70.0, "wiki_moon_atm"),
            Species("K", 17.0, "wiki_moon_atm"),
        ),
        pressure=Pressure(3.0e-10, "surface", "nssdc_moon"),
        note="surface_bounded",
    ),
    # Ceres has no measured pressure at all — only a water-vapour production
    # rate from localized sources (Herschel), so there is nothing to compose.
    "naif-2000001": BodyFacts(
        atmosphere_type="transient_exosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(),
        type_source="kuppers_2014",
        note="transient_vapour",
    ),
    # Pluto. 1.15 Pa is the New Horizons radio occultation; the atmosphere is
    # strongly seasonal — 0.4 Pa in 1988, peaking near 1.3 Pa in 2015, back to
    # 0.97 Pa by 2019 as Pluto recedes and nitrogen freezes out.
    "naif-999": BodyFacts(
        atmosphere_type="thin_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("N2", 0.99, "nssdc_pluto"),
            Species("CH4", 0.003, "young_2018"),
            Species("CO", 5.15e-4, "wiki_pluto_atm"),
            Species("C2H2", 3.0e-6, "wiki_pluto_atm"),
            Species("C2H4", 1.0e-6, "wiki_pluto_atm"),
        ),
        pressure=Pressure(1.15, "surface", "hinson_2017", "variable"),
        note="seasonal_orbit",
    ),
    # Triton, likewise seasonal: 1.4 Pa at the Voyager 2 flyby, roughly double
    # that around 2009, and back to 1.45 Pa by 2022.
    "naif-801": BodyFacts(
        atmosphere_type="thin_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("N2", 0.99, "wiki_triton_atm"),
            Species("CO", 6.0e-4, "lellouch_2010"),
            Species("CH4", 2.4e-4, "lellouch_2010"),
        ),
        pressure=Pressure(1.454, "surface", "sicardy_2024", "variable"),
        note="seasonal_orbit",
    ),
    # Eris: nitrogen and methane ices on the surface, but the 2010 occultation
    # saw no atmosphere above ~1 nbar. Any envelope has frozen out at 96 AU.
    "spkid-20136199": BodyFacts(
        atmosphere_type="frozen_collapsed",
        composition_unit=VOLUME_FRACTION,
        composition=(),
        pressure=Pressure(1.0e-4, "surface", "sicardy_2011", "upper_limit"),
        note="frozen_out",
    ),
    # Makemake: the 2011 occultation ruled out a global atmosphere. JWST has
    # since seen gaseous methane, but localized rather than global.
    "spkid-20136472": BodyFacts(
        atmosphere_type="none_detected",
        composition_unit=VOLUME_FRACTION,
        composition=(),
        pressure=Pressure(1.2e-3, "surface", "ortiz_2012", "upper_limit"),
        note="no_detection",
    ),
    # Haumea: the 2017 occultation limits are 15 nbar for N₂, 50 nbar for CH₄
    # (3σ); the tighter one is quoted.
    "spkid-20136108": BodyFacts(
        atmosphere_type="none_detected",
        composition_unit=VOLUME_FRACTION,
        composition=(),
        pressure=Pressure(1.5e-3, "surface", "ortiz_2017", "upper_limit"),
        note="no_detection",
    ),
    # Dione: Cassini INMS/CAPS see molecular oxygen and carbon dioxide, but
    # only O₂ has a published neutral density — one species is a fact, not a
    # composition.
    "naif-604": BodyFacts(
        atmosphere_type="exosphere",
        composition_unit=NUMBER_DENSITY,
        composition=(Species("O2", 2.0e4, "teolis_waite_2016"),),
        type_source="tokar_2012",
        note="sputtered_ice",
    ),
    # Rhea's oxygen-carbon dioxide exosphere, as the ratio of the two peak
    # densities Cassini measured (5·10⁴ and 2·10⁴ cm⁻³).
    "naif-605": BodyFacts(
        atmosphere_type="exosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("O2", 0.71, "teolis_2010"),
            Species("CO2", 0.29, "teolis_2010"),
        ),
        type_source="teolis_2010",
        note="sputtered_ice",
    ),
    # Enceladus is a south-polar plume, not an envelope: no global pressure
    # exists, and these are the vapour fractions Cassini's mass spectrometer
    # flew through.
    "naif-602": BodyFacts(
        atmosphere_type="localized_plume",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("H2O", 0.96, "waite_2017"),
            Species("H2", 0.014, "waite_2017"),
            Species("CO2", 0.0055, "waite_2017"),
            Species("NH3", 0.005, "waite_2017"),
            Species("CH4", 0.0017, "waite_2017"),
        ),
        type_source="hansen_2020",
        note="plume",
    ),
    # Titan near the surface — Huygens' own descent measurements. Methane
    # varies strongly with altitude (5.65% at the surface, 1.48% in the
    # stratosphere); the surface value goes with the surface pressure.
    "naif-606": BodyFacts(
        atmosphere_type="thick_atmosphere",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("N2", 0.9425, "niemann_2010"),
            Species("CH4", 0.0565, "niemann_2010"),
            Species("H2", 1.01e-3, "niemann_2010"),
            Species("CO", 4.7e-5, "dekok_2007"),
            Species("Ar-40", 3.39e-5, "niemann_2010"),
        ),
        pressure=Pressure(1.467e5, "surface", "huygens_hasi"),
    ),
    # Io: a collisional SO₂ atmosphere in genuine mixing ratios, unlike the
    # sputtered exospheres of the icy moons. Pressure is the dayside value —
    # it collapses by orders of magnitude in eclipse as the SO₂ freezes out.
    "naif-501": BodyFacts(
        atmosphere_type="tenuous_collisional",
        composition_unit=VOLUME_FRACTION,
        composition=(
            Species("SO2", 0.9, "wiki_io_atm"),
            Species("SO", 0.05, "wiki_io_atm"),
        ),
        pressure=Pressure(3.3e-5, "surface", "wiki_io", "variable"),
        note="volcanic",
    ),
    # Europa. Columns are sunlit-hemisphere constraints — the water is
    # sublimated where the Sun is up, so the leading hemisphere is nearly pure
    # O₂ and these shares describe the dayside, not the globe.
    "naif-502": BodyFacts(
        atmosphere_type="tenuous_exosphere",
        composition_unit=COLUMN_DENSITY,
        composition=(
            Species("H2O", 1.5e15, "cervantes_2022"),
            Species("O2", 1.2e14, "cervantes_2022"),
            Species("O", 6.0e12, "roth_2021_europa"),
        ),
        pressure=Pressure(1.0e-7, "surface", "mcgrath_2009", "approximate"),
        note="sputtered_ice",
    ),
    # Ganymede, same caveat: the water column drops ~300× in eclipse while the
    # sputtered O₂ stays put.
    "naif-503": BodyFacts(
        atmosphere_type="tenuous_exosphere",
        composition_unit=COLUMN_DENSITY,
        composition=(
            Species("H2O", 1.0e15, "roth_2021_ganymede"),
            Species("O2", 5.0e14, "hall_1998"),
            Species("O", 3.0e12, "dekleer_2023", upper_limit=True),
        ),
        pressure=Pressure(7.0e-7, "surface", "hall_1998", "approximate"),
        note="sputtered_ice",
    ),
    # Callisto. The quoted pressure is the CO₂ component Galileo measured;
    # oxygen is the larger column but was inferred from aurora, not sounded.
    # A non-detection bound on H₂O (Carberry Mogan et al. 2022) is left out —
    # it is a limit on a reservoir, not a claim about one.
    "naif-504": BodyFacts(
        atmosphere_type="tenuous_exosphere",
        composition_unit=COLUMN_DENSITY,
        composition=(
            Species("O2", 4.0e15, "dekleer_2023"),
            Species("CO2", 7.0e14, "cartwright_2024"),
        ),
        pressure=Pressure(7.5e-7, "surface", "carlson_1999"),
        note="sputtered_ice",
    ),
}
