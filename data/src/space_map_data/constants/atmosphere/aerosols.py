"""Aerosol microphysics + column optics per body.

Two phase-function families:

- `LogNormalMie` — spherical droplets/particles; the export runs Mie theory
  over a log-normal size distribution (effective radius + variance).
- `DoubleHenyeyGreenstein` — per-channel empirical fits for irregular
  particles (Mars dust, Titan fractal aggregates) that sphere-based Mie
  theory cannot represent.

Columns are given at the body's render reference level at the render
wavelengths (680/550/440 nm). Unlike the Rayleigh side, aerosol burdens are
weather — every value here is a *representative clear-conditions* pick from
the cited range, and scaling them is legitimate tuning.
"""

from typing import NamedTuple


class LogNormalMie(NamedTuple):
    """Spherical-particle population for the Mie phase precompute."""

    refractive_index_real: float
    # Positive convention; the export negates it into the m = n - ik solver form.
    refractive_index_imag: float
    effective_radius_um: float
    effective_variance: float


class DoubleHenyeyGreenstein(NamedTuple):
    """p = w·HG(g_forward) + (1-w)·HG(g_back)."""

    forward_weight: float
    g_forward: float
    g_back: float


class Aerosol(NamedTuple):
    """One body's haze layer: phase model (by key into PHASE_MODELS, so bodies
    with the same particle population share one exported LUT) + column optics
    at the reference level."""

    phase: str
    scale_height_km: float
    scatter_per_km: tuple[float, float, float]
    absorption_per_km: tuple[float, float, float]


# MSL engineering-camera fit (Chen-Chen et al. 2019, Icarus 330, 16;
# implements Wolff et al. 2009 dust): w=0.743±0.106, g1=0.889±0.098,
# g2=0.094±0.250 at 650 nm, overall g=0.687. Measured at red wavelengths
# only; applied to all channels — the sky colour comes from the per-channel
# albedo split below, not the phase.
_MARS_DHG = {c: DoubleHenyeyGreenstein(0.743, 0.889, 0.094) for c in ("r", "g", "b")}

# Empirical stand-in for Tomasko et al. 2008's tabulated fractal-aggregate
# phase functions (paywalled): strong forward peak + modest back lobe, blue
# slightly more forward-peaked (smaller effective scatterer). Aggregates of
# ~3000×0.05 µm monomers are outside sphere-Mie's reach.
_TITAN_DHG = {
    "r": DoubleHenyeyGreenstein(0.85, 0.66, -0.38),
    "g": DoubleHenyeyGreenstein(0.86, 0.70, -0.40),
    "b": DoubleHenyeyGreenstein(0.87, 0.75, -0.42),
}


# Particle populations, keyed for LUT sharing across bodies.
PHASE_MODELS: dict[str, LogNormalMie | dict[str, DoubleHenyeyGreenstein]] = {
    "continental": LogNormalMie(1.44, 0.006, 0.30, 0.20),
    "mars_dust": _MARS_DHG,
    "h2so4_cloud": LogNormalMie(1.44, 0.0, 1.05, 0.07),
    "titan_tholin": _TITAN_DHG,
    "nh3_haze": LogNormalMie(1.42, 0.001, 0.55, 0.20),
    "ice_giant_haze": LogNormalMie(1.40, 0.0, 0.05, 0.30),
    "pluto_tholin": LogNormalMie(1.69, 0.018, 0.15, 0.25),
    "triton_haze": LogNormalMie(1.50, 0.001, 0.17, 0.25),
}


AEROSOLS: dict[str, Aerosol] = {
    # OPAC continental-average mixture (Hess, Koepke & Schult 1998, BAMS 79,
    # 831, table 3 at RH 80%): σ_ext(550) = 0.075/km, ω0 = 0.925, Ångström
    # α = 1.42 → scatter ∝ λ^-1.42; column τ(550) ≈ 0.09 with the 1.2 km
    # scale height ≈ the observed global-mean AOD. H = 1.2 km is Elterman's
    # 1968 tropospheric profile (the Bruneton/Nishita convention; OPAC's own
    # continental profile is a 2 km mixed layer). Phase: RH-swollen
    # water-soluble mode, n ≈ 1.44 (Shettle & Fenn 1979 dry 1.53-0.006i
    # toward water 1.33), r_eff 0.3 µm; Mie g ≈ 0.75 vs OPAC's 0.70.
    "continental": Aerosol(
        phase="continental",
        scale_height_km=1.2,
        scatter_per_km=(0.0513, 0.0694, 0.0952),
        absorption_per_km=(5.6e-3, 5.6e-3, 5.6e-3),
    ),
    # Mars dust, clear-season background: τ_ext ≈ 0.15 (low end of the
    # 0.15-0.4 clear-conditions range — higher picks storm-veil the surface
    # albedo features that define the disc) over an 11 km well-mixed column
    # (Conrath 1975 profile ≈ gas scale height) → β_ext ≈ 0.014/km, flat
    # across the visible (r_eff 1.6 µm » λ; Tomasko et al. 1999). Albedo
    # split: ω0(650) = 0.975 (Wolff et al. 2009 via Chen-Chen 2019); k rises
    # steeply shortward of 670 nm (Tomasko 1999), the g/b albedos
    # interpolate that rise and are the tunable part — they set the
    # butterscotch sky.
    "mars_dust": Aerosol(
        phase="mars_dust",
        scale_height_km=11.0,
        scatter_per_km=(0.0133, 0.0125, 0.0095),
        absorption_per_km=(3.4e-4, 1.1e-3, 4.1e-3),
    ),
    # Venus upper haze above the ~70 km low-latitude cloud tops the texture
    # shows — the deck is latitude-dependent, so structure.py ships VIRA's
    # 65 km global reference rather than this one:
    # τ(0.63 µm) 0.2-1.0, H = 4.4±1.0 km low latitudes (Titov et al. 2018,
    # SSR 214, 126) → mid-range τ ≈ 0.5 → β_sca ≈ 0.11/km, grey (1 µm
    # droplets). Absorption: the unknown UV absorber (0.32-0.5 µm band,
    # upper cloud; Titov 2018) tails into the blue channel — magnitude
    # tunable, composition literally unknown to science. Phase: Hansen &
    # Hovenier 1974 mode-2 H₂SO₄: r_eff 1.05±0.10 µm, v_eff 0.07, n = 1.44
    # at 550 nm (Palmer & Williams 1975: 75 wt% acid).
    "h2so4_cloud": Aerosol(
        phase="h2so4_cloud",
        scale_height_km=4.4,
        scatter_per_km=(0.111, 0.111, 0.111),
        absorption_per_km=(2e-3, 3.5e-3, 1.4e-2),
    ),
    # Titan tholin haze: extinction slope τ ∝ λ^-1.41 (30-80 km regime,
    # Tomasko et al. 2008 via Bazzon et al. 2014) anchored at τ(550) ≈ 4
    # over H = 60 km → optically thick, β_ext(550) ≈ 0.067/km. Albedo split
    # from tholin k: ω(680) ≈ 0.95, dropping to ~0.55 at 440 (Khare et al.
    # 1984: k = 0.0024 red edge → 0.11 blue edge) — the blue absorption is
    # what makes the disc orange rather than cream.
    "titan_tholin": Aerosol(
        phase="titan_tholin",
        scale_height_km=60.0,
        scatter_per_km=(4.7e-2, 5.7e-2, 5.0e-2),
        absorption_per_km=(2.5e-3, 1.0e-2, 4.1e-2),
    ),
    # Jupiter + Saturn stratospheric/NH₃ haze above the 1-bar deck: compact
    # sub-µm particles (r = 0.2-0.5 µm, Zhang et al. 2013 low latitudes;
    # NH₃-ice n ≈ 1.42). Thin veil — columns are tunable small numbers, the
    # deck itself is baked into the texture.
    "nh3_haze": Aerosol(
        phase="nh3_haze",
        scale_height_km=25.0,
        scatter_per_km=(1e-3, 1e-3, 1e-3),
        absorption_per_km=(1e-4, 1e-4, 1e-4),
    ),
    # Saturn variant: same particles, deeper column (H tracks its taller gas
    # scale height).
    "nh3_haze_saturn": Aerosol(
        phase="nh3_haze",
        scale_height_km=50.0,
        scatter_per_km=(1e-3, 1e-3, 1e-3),
        absorption_per_km=(1e-4, 1e-4, 1e-4),
    ),
    # Uranus/Neptune "Aerosol-3" (Irwin et al. 2022, JGR 127, e2022JE007189):
    # extended r ≈ 0.05 µm photochemical haze from ~1.6 bar up through the
    # stratosphere, ~λ⁻⁴ scattering — the visually dominant Aerosol-2 deck
    # (1.4-2.1 bar) is baked into the textures. λ⁻⁴ slope applied around a
    # tunable thin-veil magnitude.
    "ice_giant_haze": Aerosol(
        phase="ice_giant_haze",
        scale_height_km=28.0,
        scatter_per_km=(2.1e-4, 5e-4, 1.22e-3),
        absorption_per_km=(5e-5, 5e-5, 5e-5),
    ),
    # Neptune variant of the same haze, H tracking its gas scale height.
    "ice_giant_haze_neptune": Aerosol(
        phase="ice_giant_haze",
        scale_height_km=21.0,
        scatter_per_km=(2.1e-4, 5e-4, 1.22e-3),
        absorption_per_km=(5e-5, 5e-5, 5e-5),
    ),
    # Pluto: tholin aggregates (monomers ~0.01 µm, aggregate r ≳ 0.1-0.2 µm,
    # Gladstone et al. 2016 / Cheng et al. 2017), brightness scale height
    # ~50 km, measured vertical scattering τ ≈ 0.013-0.018 → β_sca(550) ≈
    # 3.6e-4/km at the top of the range. Blue: blue/red I/F > 2 → ~λ⁻³
    # slope. n = 1.69, k = 0.018 at 607.6 nm (Khare et al. 1984 tholins).
    # Faint column; visibility leans on the forward phase lobe + physical
    # backlit sun.
    "pluto_tholin": Aerosol(
        phase="pluto_tholin",
        scale_height_km=50.0,
        scatter_per_km=(1.9e-4, 3.6e-4, 7.0e-4),
        absorption_per_km=(5e-5, 5e-5, 5e-5),
    ),
    # Triton: hydrocarbon-ice haze, cross-section-averaged r = 0.173±0.012 µm,
    # H = 11.0±0.6 km, scattering τ ≈ 0.001-0.01 (~0.003 typical) — Rages &
    # Pollack 1992 (Icarus 99, 289) → β_sca(550) ≈ 2.7e-4/km, ~λ⁻³ slope.
    # Refractive index not pinned by the source; 1.50 assumed (ice/tholin mix).
    "triton_haze": Aerosol(
        phase="triton_haze",
        scale_height_km=11.0,
        scatter_per_km=(1.4e-4, 2.7e-4, 5.3e-4),
        absorption_per_km=(2e-5, 2e-5, 2e-5),
    ),
}
