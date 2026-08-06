"""Per-body magnetic fields — what generates one, and how big it is.

Fields are in tesla and moments in A m², which is not how any of these papers
publish them: planetary magnetism quotes a *surface* field in gauss or nT
scaled to the body's own radius, because that is what the spacecraft measured.
Every dipole moment below is therefore arithmetic on the published surface
field and the body's radius,

    M = (4π/μ₀) · R³ · B_eq ,

marked `modelled=False` because the conversion adds no assumption — it is the
same number in units that let Mercury and Jupiter sit in one column. The
surface field alongside it is the source's own.

`surface_field_t` is the equatorial field of the equivalent centred dipole
unless a body's comment says otherwise. On the ice giants and Jupiter the real
surface field departs from that by an order of magnitude, which is why those
entries carry a `range`: a dipole is a poor description of a field whose
quadrupole is the same size.

Radii used for the conversions are the IAU mean or equatorial radii the source
itself scales to, written into each comment.
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
    # Sun. The one entry where `surface_field_t` is a *polar* field and not an
    # equatorial one: the Sun has no steady dipole to take an equator from. The
    # WSO record's polemost aperture averages the line-of-sight field between
    # 55° and the pole, and it swings through zero and reverses sign near every
    # sunspot maximum — 1 G at minimum, nothing at maximum, opposite polarity
    # eleven years later. The range is the span of the 1976-2026 record; the
    # value is a typical minimum.
    "naif-10": MagneticField(
        kind=DYNAMO,
        kind_sources=("wso_polar",),
        surface_field_t=Measurement(1.0e-4, "wso_polar", range=(0.0, 1.6e-4)),
        note="cyclic_reversal",
    ),
    # Mercury. 190 nT R_M³ is the axial dipole; the field is so nearly
    # axisymmetric that the tilt is only ever quoted as a bound. What makes it
    # strange is not the weakness but the offset: the magnetic equator sits
    # 479 km north of the planet's, so the southern surface field is about
    # three times the northern one, and the solar wind reaches the south pole.
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
    # Venus. Eighteen thousand low-altitude nightside vectors from Pioneer
    # Venus, and nothing: the bound is a ten-thousandth of Earth's moment, and
    # the same analysis found no crustal remanence either. What Venus has
    # instead is an induced magnetosphere, the interplanetary field draping
    # over the ionosphere. Phillips & Russell quote 8.4×10¹⁰ T m³, which is
    # 8.4×10¹⁷ A m² in SI.
    "naif-299": MagneticField(
        kind=NO_FIELD,
        kind_sources=("phillips_1987",),
        dipole_moment_a_m2=Measurement(8.4e17, "phillips_1987", upper_limit=True),
        note="induced_magnetosphere",
    ),
    # Earth. Both numbers are arithmetic on IGRF-14 at epoch 2025.0, whose
    # degree-1 coefficients are g₁⁰ = -29350.0, g₁¹ = -1410.3, h₁¹ = 4545.5 nT:
    # the dipole term is their root-sum-square, 29733 nT, and the tilt is
    # arccos(|g₁⁰|/29733). The range on the surface field is not the dipole's
    # spread but the model's real one — 22,071 nT at the South Atlantic Anomaly
    # to about 70,000 nT — because the non-dipole field is 8% of the power.
    "naif-399": MagneticField(
        kind=DYNAMO,
        kind_sources=("igrf_14",),
        dipole_moment_a_m2=Measurement(7.69e22, "igrf_14"),
        surface_field_t=Measurement(2.9733e-5, "igrf_14", range=(2.2071e-5, 7.0e-5)),
        dipole_tilt_deg=Measurement(9.21, "igrf_14"),
        note="polarity_reversals",
    ),
    # Moon. No dynamo now; what is left is magnetised crust, mapped from orbit
    # and continued down to the surface. The 718 nT peak is at the antipode of
    # Crisium, which is the pattern that ties the strong anomalies to basin-
    # forming impacts rather than to a global field. Two breccias that cooled
    # in a near-zero field at 0.91 and 0.44 Ga bracket the dynamo's end
    # against older paleointensities: between 1.92 and 0.80 Ga.
    "naif-301": MagneticField(
        kind=REMANENT,
        kind_sources=("tsunakawa_2015",),
        surface_field_t=Measurement(7.18e-7, "tsunakawa_2015"),
        dynamo_ended_years=Measurement(1.36e9, "mighani_2020", range=(0.80e9, 1.92e9)),
        note="crustal_anomalies",
    ),
    # Mars. Also remanence only, but an order of magnitude stronger than the
    # Moon's and concentrated in the southern highlands, where the crust
    # predates the basins that would have demagnetised it. The 2000 nT is the
    # static field InSight measured at its own landing site in Elysium — a
    # single ground truth an order of magnitude above what orbital models
    # predicted there, which is the reason to quote it rather than a map's
    # maximum.
    "naif-499": MagneticField(
        kind=REMANENT,
        kind_sources=("mittelholz_2022",),
        surface_field_t=Measurement(2.0e-6, "mittelholz_2022"),
        dynamo_ended_years=Measurement(4.05e9, "mittelholz_2022", range=(4.0e9, 4.1e9)),
        note="crustal_anomalies",
    ),
    # Jupiter. JRM33's degree-1 terms are a dipole of 4.177 G tilted 10.25°
    # towards System III longitude 196.38°; the offset is Connerney's eccentric
    # dipole fit from the JPL model comparison. The surface range is what Juno
    # actually flew through — 3.20 G
    # at one equator crossing against 14.31 G at another — reaching about 20 G
    # at northern mid-latitudes near the Great Blue Spot, an isolated patch of
    # flux where the equatorial field reverses sign.
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
    # Io. The contested one. Galileo's magnetometer saw a signature Khurana
    # read as induction in a global magma ocean, which would make Io the only
    # body whose induced field images molten rock rather than salt water. Juno's
    # measurement of the tidal Love number twenty-four years later rules out
    # the shallow global magma ocean that reading needs, so the field is
    # recorded here as induced and disputed rather than as evidence of an ocean.
    "naif-501": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_2011", "park_2025"),
        note="induction_disputed",
    ),
    # Europa. The clean case: the induced field flips with Jupiter's field as
    # Europa moves through the tilted magnetic equator, which needs a
    # conductive shell within a few tens of km of the surface, and salty water
    # is the only candidate. No intrinsic moment. The measurement is about the
    # ocean, not about a core, which is why no moment is quoted.
    "naif-502": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_1998",),
        note="ocean_induction",
    ),
    # Ganymede. The only moon with a dynamo. Galileo's five passes give a
    # permanent dipole of 719 nT at the equator tilted 176° from the spin axis
    # — that is, very nearly anti-aligned, 4° off — and a magnetosphere inside
    # Jupiter's. An induced component rides on top of it, which is how the
    # ocean was found. M = (4π/μ₀)(2631.2 km)³(719 nT).
    "naif-503": MagneticField(
        kind=DYNAMO,
        kind_sources=("kivelson_2002",),
        dipole_moment_a_m2=Measurement(1.31e20, "kivelson_2002"),
        surface_field_t=Measurement(7.19e-7, "kivelson_2002"),
        dipole_tilt_deg=Measurement(4.0, "kivelson_2002"),
        note="magnetosphere_within_magnetosphere",
    ),
    # Callisto. The same induction signature as Europa's, from the same two
    # Galileo passes, and the reason the outermost Galilean moon is counted an
    # ocean world at all — nothing on its cratered surface says so.
    "naif-504": MagneticField(
        kind=INDUCED,
        kind_sources=("khurana_1998",),
        note="ocean_induction",
    ),
    # Saturn. The anomaly of the set: after 22 close Grand Finale orbits the
    # tilt is bounded at 25 arcseconds, which no dynamo model reproduces
    # without a stably stratified layer above the dynamo to filter the
    # non-axisymmetric field out. What asymmetry there is sits in the offset —
    # the magnetic equator is 2820 km north of the planet's.
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
    # Titan. Twenty-five Cassini flybys put the permanent moment below
    # 0.78 nT R_Ti³, five times tighter than Voyager managed and consistent
    # with zero — the interior does not run a dynamo, which agrees with what
    # the gravity says about how little the moon has differentiated.
    # M = (4π/μ₀)(2574.7 km)³(0.78 nT).
    "naif-606": MagneticField(
        kind=NO_FIELD,
        kind_sources=("wei_2010",),
        dipole_moment_a_m2=Measurement(1.33e17, "wei_2010", upper_limit=True),
        surface_field_t=Measurement(7.8e-10, "wei_2010", upper_limit=True),
    ),
    # Uranus. An oblique rotator: the dipole lies 59° from the spin axis and a
    # third of a radius off centre, so the surface field runs from 0.1 G on one
    # side to 1.1 G on the other and the magnetosphere turns itself inside out
    # once a rotation. The quadrupole is as large as the dipole, which is why
    # the range matters more than the value. The offset is the offset-tilted-
    # dipole fit, which Connerney's paper describes without tabulating; the
    # number is JPL's, from the same model.
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
    # Neptune. Uranus's twin in this one respect, which was the useful surprise
    # of Voyager 2's second encounter: a 47° tilt and an offset of about half a
    # radius, from a dynamo running in a thin conducting ice shell rather than
    # in a core. The offset is the ED2/OTD(O8) row of Connerney's own Table 8
    # — components (0.05, 0.48, 0.00) — not the 0.55 R_N of the earlier
    # offset-tilted-dipole fit to the same encounter.
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
