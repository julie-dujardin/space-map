"""Per-body atmosphere reference conditions + render tuning.

The reference level is what the rendered sphere shows, not necessarily the
surface: terrestrial bodies use the surface, Venus the cloud-top/tropopause
region its texture depicts, and the giants the ~0.3 bar visible deck (their
1-bar derivation would white-wash the banding the shell sits above — the
previous hand-tuned table encoded this as an undocumented ÷3-4 on the 1-bar
coefficients). Rayleigh coefficients and scale heights are derived from these
conditions by export/atmospheres/; nothing here is a scattering coefficient.

NSSDCA fact-sheet values were read from Internet Archive snapshots of the
2024-2025 sheets (nssdc.gsfc.nasa.gov was offline 2026-07); mission values
from the cited primary papers.
"""

from typing import NamedTuple


# Bruneton-convention RGB render wavelengths, metres.
RENDER_WAVELENGTHS_M = {"r": 680e-9, "g": 550e-9, "b": 440e-9}

# 1 Dobson unit of ozone column, molecules/m².
_DOBSON_M2 = 2.687e20


class AbsorberBand(NamedTuple):
    """A pure-absorption band (ozone), as column density + cross sections; the
    export turns it into peak per-km coefficients for the shader's linear
    density tent."""

    cross_section_m2: tuple[float, float, float]
    column_m2: float
    center_km: float
    width_km: float


class RenderTuning(NamedTuple):
    """Artistic knobs — not physical, carried over from the previously shipped
    hand-tuned look; documented per body where non-obvious."""

    baked_compensation: float
    multi_scatter_gain: float
    sun_intensity: float
    realistic_sun_always: bool = False


class BodyAtmosphere(NamedTuple):
    # Gas name -> volume (number) fraction at the reference level. Truncated
    # tails are renormalised by the derivation, so fractions need not sum to 1.
    composition: dict[str, float]
    pressure_pa: float
    temperature_k: float
    # Effective (rotation-included) gravity at the reference level — the
    # NSSDCA "acceleration" rows for the fast-spinning giants.
    gravity_m_s2: float
    aerosol: str
    tuning: RenderTuning
    absorber: AbsorberBand | None = None


ATMOSPHERE_BODIES: dict[str, BodyAtmosphere] = {
    # Venus, referenced to the ~60-65 km cloud-top/tropopause region the
    # texture shows: ~0.1 bar, 245 K (Gillmann et al. 2024 review of VIRA:
    # tropopause 245 K near 60 km; Seiff et al. 1985). Composition: 96.5%
    # CO₂ / 3.5% N₂ (VIRA via Limaye et al. 2017). g ≈ 8.7 at 65 km
    # (8.87 surface, NSSDCA). Surface conditions (92 bar, 735 K) are NOT
    # rendered — the deck is opaque.
    "naif-299": BodyAtmosphere(
        composition={"CO2": 0.965, "N2": 0.035},
        pressure_pa=1.0e4,
        temperature_k=245.0,
        gravity_m_s2=8.7,
        aerosol="h2so4_cloud",
        tuning=RenderTuning(
            # The shell IS the visible cloud deck's overburden — keep it
            # opaque over the disc; thick atmosphere wants MS ≥ 1; sun kept
            # under the rolloff shoulder so the H₂SO₄ cream tint survives.
            baked_compensation=0.0,
            multi_scatter_gain=1.5,
            sun_intensity=12.0,
        ),
    ),
    # Earth at US Standard Atmosphere 1976 sea level: 101325 Pa (exact),
    # 288.15 K, g₀ = 9.80665 (exact). Composition: NSSDCA 2024 dry air.
    # Ozone: 300 DU column in Bruneton's 10-25-40 km tent convention;
    # Chappuis cross sections at 680/550/440 nm reduced from the
    # Serdyuchenko/Gorshelev dataset (Gorshelev et al. 2014, AMT 7, 609;
    # doi:10.5281/zenodo.5793206).
    "naif-399": BodyAtmosphere(
        composition={"N2": 0.7808, "O2": 0.2095, "Ar": 0.00934, "CO2": 0.00042},
        pressure_pa=101325.0,
        temperature_k=288.15,
        gravity_m_s2=9.80665,
        aerosol="continental",
        tuning=RenderTuning(
            # sunIntensity well below physical ~22: the satellite mosaic
            # already bakes in the atmosphere seen from above.
            baked_compensation=1.0,
            multi_scatter_gain=0.3,
            sun_intensity=5.0,
        ),
        absorber=AbsorberBand(
            cross_section_m2=(1.36e-25, 3.29e-25, 1.35e-26),
            column_m2=300.0 * _DOBSON_M2,
            center_km=25.0,
            width_km=15.0,
        ),
    ),
    # Mars at the mean-radius datum: 636 Pa, 214 K average, g = 3.73
    # (NSSDCA 2025 sheet; pressure is seasonal ±25%, 4.0-8.7 mbar).
    # Composition: NSSDCA (Curiosity/SAM-era rows).
    "naif-499": BodyAtmosphere(
        composition={"CO2": 0.951, "N2": 0.0259, "Ar": 0.0194, "O2": 0.0016},
        pressure_pa=636.0,
        temperature_k=214.0,
        gravity_m_s2=3.73,
        aerosol="mars_dust",
        tuning=RenderTuning(
            # Below physical like Earth: the mosaic bakes in the dust haze.
            baked_compensation=1.0,
            multi_scatter_gain=0.4,
            sun_intensity=7.0,
        ),
    ),
    # Jupiter above the 1-bar cloud texture, referenced to the ~0.3 bar
    # visible deck; T ≈ 125 K interpolated on the Voyager occultation
    # profile between the 110 K / 0.14 bar tropopause and 165±5 K / 1 bar
    # (Lindal et al. 1981). He = 0.1359±0.0027 from the Galileo probe
    # (von Zahn et al. 1998) — the NSSDCA row still carries the Voyager-era
    # 10.2%. g: NSSDCA equatorial acceleration (rotation included).
    "naif-599": BodyAtmosphere(
        composition={"H2": 0.861, "He": 0.136, "CH4": 0.003},
        pressure_pa=3.0e4,
        temperature_k=125.0,
        gravity_m_s2=23.12,
        aerosol="nh3_haze",
        tuning=RenderTuning(
            baked_compensation=1.0,
            multi_scatter_gain=0.3,
            sun_intensity=6.0,
        ),
    ),
    # Titan at the Huygens landing site: 146700±100 Pa, 93.65±0.25 K
    # (HASI, Fulchignoni et al. 2005). Composition: GCMS near-surface
    # CH₄ = 5.65±0.18%, H₂ = 0.101% (Niemann et al. 2010), N₂ balance.
    # g = 1.35 (GM/r² from NSSDCA mass + 2575 km radius).
    "naif-606": BodyAtmosphere(
        composition={"N2": 0.942, "CH4": 0.0565, "H2": 0.00101},
        pressure_pa=1.467e5,
        temperature_k=93.65,
        gravity_m_s2=1.35,
        aerosol="titan_tholin",
        tuning=RenderTuning(
            # Texture is the haze-hidden surface map, not Titan's
            # photographed look — the orange shell must stay opaque over it.
            # High sun saturates the 1-exp rolloff and bleaches the orange.
            baked_compensation=0.0,
            multi_scatter_gain=0.5,
            sun_intensity=9.0,
        ),
    ),
    # Saturn, ~0.3 bar deck; T ≈ 110 K interpolated between the 82 K /
    # 70 mbar tropopause and 134 K / 1 bar (Voyager: Tyler et al. 1982,
    # Lindal et al. 1985). He is genuinely unsettled — Voyager IRIS 3.25%,
    # Conrath & Gautier 2000 He/H₂ = 0.11-0.16, Cassini CIRS 2020 ~0.052;
    # mid Conrath & Gautier (He/H₂ = 0.135) adopted here.
    "naif-699": BodyAtmosphere(
        composition={"H2": 0.877, "He": 0.118, "CH4": 0.0045},
        pressure_pa=3.0e4,
        temperature_k=110.0,
        gravity_m_s2=8.96,
        aerosol="nh3_haze_saturn",
        tuning=RenderTuning(
            baked_compensation=1.0,
            multi_scatter_gain=0.3,
            sun_intensity=6.0,
        ),
    ),
    # Uranus, ~0.3 bar; T ≈ 58 K between the 53±1 K / 0.1 bar tropopause
    # and 76 K / 1 bar (Voyager: Lindal et al. 1987). He = 0.152±0.033
    # (Conrath et al. 1987); CH₄ 2.3% (occultation nominal; drops above the
    # 1.2 bar CH₄ cloud, and the modern deep value is latitude-dependent
    # 1.4-4%, Karkoschka & Tomasko 2009). g: equatorial acceleration.
    "naif-799": BodyAtmosphere(
        composition={"H2": 0.825, "He": 0.152, "CH4": 0.023},
        pressure_pa=3.0e4,
        temperature_k=58.0,
        gravity_m_s2=8.69,
        aerosol="ice_giant_haze",
        tuning=RenderTuning(
            baked_compensation=1.0,
            multi_scatter_gain=0.4,
            sun_intensity=6.0,
        ),
    ),
    # Triton, Voyager 2 epoch (1989-08-25): surface 1.5 Pa (radio 1.6±0.3,
    # UVS ~1.4 — Tyler et al. 1989, Broadfoot et al. 1989), 38 K surface
    # in N₂-ice vapor equilibrium (Conrath et al. 1989). CH₄ ~1e-4.
    # g = 0.78 (GM/r²). A 2017 occultation found the pressure still
    # consistent with 1989 (Marques Oliveira et al. 2022).
    "naif-801": BodyAtmosphere(
        composition={"N2": 0.9999, "CH4": 0.0001},
        pressure_pa=1.5,
        temperature_k=38.0,
        gravity_m_s2=0.78,
        aerosol="triton_haze",
        tuning=RenderTuning(
            # There is no good flat-sun exposure for the far wisps: 1-AU
            # sunlight on the measured haze gives an Earth-sky-class glowing
            # rim (limb τ_sca(blue) ≈ 0.3 × sunIntensity 22), while true
            # inverse-square at 30 AU puts it ~3 orders below visibility.
            # The exemption IS the exposure choice: physical sun, faint wisp.
            baked_compensation=1.0,
            multi_scatter_gain=0.4,
            sun_intensity=22.0,
            realistic_sun_always=True,
        ),
    ),
    # Neptune, ~0.3 bar; T ≈ 55 K between the 52±2 K / 0.1 bar tropopause
    # and 72±2 K / 1 bar (Voyager: Lindal 1992, Tyler et al. 1989).
    # He = 0.190±0.032 (Conrath et al. 1991); CH₄ 1.5% above the cloud
    # (NSSDCA; deep value 4±1%, Karkoschka & Tomasko 2011).
    "naif-899": BodyAtmosphere(
        composition={"H2": 0.80, "He": 0.19, "CH4": 0.015},
        pressure_pa=3.0e4,
        temperature_k=55.0,
        gravity_m_s2=11.00,
        aerosol="ice_giant_haze_neptune",
        tuning=RenderTuning(
            baked_compensation=1.0,
            multi_scatter_gain=0.4,
            sun_intensity=6.0,
        ),
    ),
    # Pluto, New Horizons epoch (2015-07-14): surface 1.15±0.07 Pa (REX
    # radio occultation, Hinson et al. 2017); T = 50 K representative of
    # the REX near-surface range (38.9 K ingress boundary layer to 57 K
    # egress; strong inversion above). Composition: N₂ + 0.5% CH₄
    # (NSSDCA). g = 0.62. The pressure has been rising for decades (Meza
    # et al. 2019) — this is the flyby snapshot.
    "naif-999": BodyAtmosphere(
        composition={"N2": 0.995, "CH4": 0.005},
        pressure_pa=1.15,
        temperature_k=50.0,
        gravity_m_s2=0.62,
        aerosol="pluto_tholin",
        tuning=RenderTuning(
            # Same exposure choice as Triton (limb τ_sca(blue) ≈ 0.4 —
            # flat sun renders a full New-Horizons-style blue halo, nice but
            # ahistoric for a map default; inverse-square at 39.5 AU keeps
            # the wisp).
            baked_compensation=1.0,
            multi_scatter_gain=0.4,
            sun_intensity=22.0,
            realistic_sun_always=True,
        ),
    ),
}
