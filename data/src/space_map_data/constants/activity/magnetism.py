"""Per-body magnetic fields — what generates one, and how big it is.

Fields are in tesla, moments in A m². Papers publish a *surface* field scaled
to the body's own radius, so each dipole moment here is arithmetic on that
field and radius:

    M = (4π/μ₀) · R³ · B_eq

marked `modelled=False` since it's a unit change, not an added assumption.
`surface_field_t` is the equatorial field of the equivalent centred dipole
unless a comment says otherwise; ice giants and Jupiter carry a `range`
because their real surface field departs from a pure dipole by an order of
magnitude. Radii are the IAU mean/equatorial radii each source scales to,
given per comment.
"""

from space_map_data.constants.activity.schema import (
    DYNAMO,
    INDUCED,
    NO_FIELD,
    REMANENT,
    MagneticField,
    Measurement,
)

MAGNETIC_FIELDS: dict[str, MagneticField] = {
    # Sun. `surface_field_t` is polar, not equatorial — no steady dipole to
    # take an equator from. WSO's polemost aperture (55° to pole) swings
    # through zero and reverses sign near every sunspot maximum; the range is
    # the 1976-2026 record span, the value a typical minimum.
    "naif-10": MagneticField(
        kind=DYNAMO,
        kind_sources=("wso_polar",),
        surface_field_t=Measurement(1.0e-4, "wso_polar", range=(0.0, 1.6e-4)),
        note="cyclic_reversal",
    ),
    # Mercury. Nearly axisymmetric, so tilt is only ever a bound. The
    # 479 km northward offset triples the southern surface field over the
    # northern and lets solar wind reach the south pole.
    # M = (4π/μ₀)(2439.7 km)³(190 nT).
    "naif-199": MagneticField(
        kind=DYNAMO,
        kind_sources=("anderson_2012",),
        dipole_moment_a_m2=Measurement(2.76e19, "anderson_2012"),
        surface_field_t=Measurement(1.90e-7, "anderson_2012"),
        dipole_tilt_deg=Measurement(0.8, "anderson_2012", upper_limit=True),
        dipole_offset_radii=Measurement(0.19, "anderson_2012"),
        note="offset_dipole",
    ),
    # Venus. Pioneer Venus nightside data bound the moment at a ten-thousandth
    # of Earth's, with no crustal remanence either; what Venus has instead is
    # an induced magnetosphere from the draping interplanetary field.
    # Phillips & Russell's 8.4×10¹⁰ T m³ is 8.4×10¹⁷ A m² in SI.
    "naif-299": MagneticField(
        kind=NO_FIELD,
        kind_sources=("phillips_1987",),
        dipole_moment_a_m2=Measurement(8.4e17, "phillips_1987", upper_limit=True),
        note="induced_magnetosphere",
    ),
    # Earth. IGRF-14 epoch 2025.0: dipole term is the root-sum-square of the
    # degree-1 coefficients (29733 nT), tilt is arccos(|g₁⁰|/29733). The
    # surface-field range (22,071-70,000 nT) is the model's real spread, not
    # the dipole's — non-dipole field carries 8% of the power.
    "naif-399": MagneticField(
        kind=DYNAMO,
        kind_sources=("igrf_14",),
        dipole_moment_a_m2=Measurement(7.69e22, "igrf_14"),
        surface_field_t=Measurement(2.9733e-5, "igrf_14", range=(2.2071e-5, 7.0e-5)),
        dipole_tilt_deg=Measurement(9.21, "igrf_14"),
        note="polarity_reversals",
    ),
    # Moon. No dynamo now, only magnetised crust. The 718 nT peak sits at the
    # Crisium antipode, tying strong anomalies to basin-forming impacts rather
    # than a global field. Breccias cooled in a near-zero field bracket the
    # dynamo's end between 1.92 and 0.80 Ga.
    "naif-301": MagneticField(
        kind=REMANENT,
        kind_sources=("tsunakawa_2015",),
        surface_field_t=Measurement(7.18e-7, "tsunakawa_2015"),
        dynamo_ended_years=Measurement(1.36e9, "mighani_2020", range=(0.80e9, 1.92e9)),
        note="crustal_anomalies",
    ),
    # Mars. Remanence only, an order of magnitude stronger than the Moon's and
    # concentrated in the southern highlands, whose crust predates the basins
    # that would have demagnetised it. The 2000 nT is InSight's static-field
    # measurement at its Elysium landing site, itself an order of magnitude
    # above what orbital models predicted there.
    "naif-499": MagneticField(
        kind=REMANENT,
        kind_sources=("mittelholz_2022",),
        surface_field_t=Measurement(2.0e-6, "mittelholz_2022"),
        dynamo_ended_years=Measurement(4.05e9, "mittelholz_2022", range=(4.0e9, 4.1e9)),
        note="crustal_anomalies",
    ),
    # Jupiter. JRM33 dipole: 4.177 G tilted 10.25° at System III longitude
    # 196.38°; offset is Connerney's eccentric-dipole fit. Surface range is
    # what Juno actually flew through, 3.20-14.31 G at the equator, ~20 G near
    # the Great Blue Spot where the field reverses sign.
    # M = (4π/μ₀)(71492 km)³(4.177 G).
    "naif-599": MagneticField(
        kind=DYNAMO,
        kind_sources=("connerney_2022",),
        dipole_moment_a_m2=Measurement(1.53e27, "connerney_2022"),
        surface_field_t=Measurement(
            4.177e-4, "connerney_2022", range=(3.20e-4, 2.0e-3)
        ),
        dipole_tilt_deg=Measurement(10.25, "connerney_2022"),
        dipole_offset_radii=Measurement(0.101, "garrett_2017"),
        note="great_blue_spot",
    ),
    # Io. Contested: Khurana read Galileo's magnetometer signature as induction
    # in a global magma ocean, but Juno's tidal Love number, measured
    # twenty-four years later, rules out the shallow ocean that reading needs.
    # Recorded as induced and disputed, not as evidence of an ocean.
    "naif-501": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_2011", "park_2025"),
        note="induction_disputed",
    ),
    # Europa. Clean case: the induced field flips with Jupiter's as Europa
    # crosses the tilted magnetic equator, requiring a conductive shell within
    # tens of km of the surface — salty water is the only candidate. No
    # intrinsic moment; the measurement is about the ocean, not a core.
    "naif-502": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_1998",),
        note="ocean_induction",
    ),
    # Ganymede. The only moon with a dynamo: Galileo's five passes give a
    # 719 nT dipole tilted 176° (nearly anti-aligned) with a magnetosphere
    # inside Jupiter's. An induced component riding on top is how the ocean
    # was found. M = (4π/μ₀)(2631.2 km)³(719 nT).
    "naif-503": MagneticField(
        kind=DYNAMO,
        kind_sources=("kivelson_2002",),
        dipole_moment_a_m2=Measurement(1.31e20, "kivelson_2002"),
        surface_field_t=Measurement(7.19e-7, "kivelson_2002"),
        dipole_tilt_deg=Measurement(4.0, "kivelson_2002"),
        note="magnetosphere_within_magnetosphere",
    ),
    # Callisto. Same induction signature as Europa's, from the same Galileo
    # passes — the only reason it's counted an ocean world; nothing on its
    # cratered surface says so.
    "naif-504": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_1998",),
        note="ocean_induction",
    ),
    # Saturn. Anomalous: 22 Grand Finale orbits bound the tilt at 25
    # arcseconds, which no dynamo model reproduces without a stably stratified
    # layer filtering out the non-axisymmetric field. Asymmetry shows up
    # instead in the 2820 km northward offset.
    # M = (4π/μ₀)(60268 km)³(21141 nT).
    "naif-699": MagneticField(
        kind=DYNAMO,
        kind_sources=("cao_2020",),
        dipole_moment_a_m2=Measurement(4.63e25, "cao_2020"),
        surface_field_t=Measurement(2.1141e-5, "cao_2020"),
        dipole_tilt_deg=Measurement(0.007, "cao_2020", upper_limit=True),
        dipole_offset_radii=Measurement(0.0468, "cao_2020"),
        note="axisymmetric",
    ),
    # Titan. 25 Cassini flybys bound the moment below 0.78 nT R_Ti³, five
    # times tighter than Voyager and consistent with zero — no dynamo, which
    # agrees with the moon's low degree of differentiation.
    # M = (4π/μ₀)(2574.7 km)³(0.78 nT).
    "naif-606": MagneticField(
        kind=NO_FIELD,
        kind_sources=("wei_2010",),
        dipole_moment_a_m2=Measurement(1.33e17, "wei_2010", upper_limit=True),
        surface_field_t=Measurement(7.8e-10, "wei_2010", upper_limit=True),
    ),
    # Uranus. Oblique rotator: dipole 59° off-axis, a third of a radius off
    # centre — surface field runs 0.1-1.1 G, magnetosphere flips inside out
    # each rotation. Quadrupole rivals the dipole, so range matters more than
    # value. Offset is JPL's number from Connerney's model, untabulated there.
    # M = (4π/μ₀)(25559 km)³(0.228 G).
    "naif-799": MagneticField(
        kind=DYNAMO,
        kind_sources=("connerney_1987",),
        dipole_moment_a_m2=Measurement(3.81e24, "connerney_1987"),
        surface_field_t=Measurement(2.28e-5, "connerney_1987", range=(1.0e-5, 1.1e-4)),
        dipole_tilt_deg=Measurement(58.6, "connerney_1987"),
        dipole_offset_radii=Measurement(0.31, "garrett_2015"),
        note="oblique_rotator",
    ),
    # Neptune. Uranus's twin: 47° tilt, offset about half a radius, from a
    # dynamo in a thin conducting ice shell rather than a core. Offset is the
    # ED2/OTD(O8) row of Connerney's Table 8 (0.05, 0.48, 0.00), not the 0.55
    # R_N of the earlier fit to the same encounter.
    # M = (4π/μ₀)(24764 km)³(0.142 G).
    "naif-899": MagneticField(
        kind=DYNAMO,
        kind_sources=("connerney_1991",),
        dipole_moment_a_m2=Measurement(2.16e24, "connerney_1991"),
        surface_field_t=Measurement(1.42e-5, "connerney_1991"),
        dipole_tilt_deg=Measurement(46.9, "connerney_1991"),
        dipole_offset_radii=Measurement(0.48, "connerney_1991"),
        note="oblique_rotator",
    ),
}
