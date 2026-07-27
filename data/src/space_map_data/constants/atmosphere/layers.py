"""Layered aerosol vertical structure — data for the future piecewise-density
shader upgrade (the current shader is single-exponential per body; these are
the published profiles it can't represent yet).

Each body keeps its source's own shape and units rather than being forced into
one generic schema; the consumer that eventually samples these decides the
parameterisation.
"""

from typing import NamedTuple


class VenusCloudLayer(NamedTuple):
    """One row of the canonical Pioneer-Venus LCPS structure (Knollenberg &
    Hunten 1980, JGR 85, 8039), as tabulated by Titov et al. 2018 (SSR
    214, 126, table 1). τ at 0.63 µm; per-mode mean diameter µm / number
    density cm⁻³."""

    name: str
    base_km: float
    top_km: float
    tau_min: float
    tau_max: float
    modes: tuple[tuple[float, float], ...]


# Additional structure (Titov 2018): sub-cloud hazes down to ~30 km; upper
# haze reaches ~110 km with extinction falling > 2 orders over 25 km; cloud
# top 72±1 km at low latitudes descending to 61-67 km at the poles; global
# mean total opacity at 1 µm ≈ 34.7 (Haus et al. 2013). Detached haze layers
# at 80-85 km appear in ~60% of high-resolution profiles.
VENUS_CLOUD_LAYERS: tuple[VenusCloudLayer, ...] = (
    VenusCloudLayer("upper haze", 70.0, 90.0, 0.2, 1.0, ((0.4, 500.0),)),
    VenusCloudLayer("upper cloud", 56.5, 70.0, 6.0, 8.0, ((0.4, 1500.0), (2.0, 50.0))),
    VenusCloudLayer(
        "middle cloud", 50.5, 56.5, 8.0, 10.0, ((0.3, 300.0), (2.5, 50.0), (7.0, 10.0))
    ),
    VenusCloudLayer(
        "lower cloud", 47.5, 50.5, 6.0, 12.0, ((0.4, 1200.0), (2.0, 50.0), (8.0, 50.0))
    ),
)


class TitanHazeRegime(NamedTuple):
    """Tomasko et al. 2008 three-regime extinction structure (via Bazzon et
    al. 2014): optical depth ∝ λ^-slope within each altitude band."""

    base_km: float
    top_km: float | None
    wavelength_slope: float


# Number density ~5 cm⁻³ at 80 km falling with a 65 km scale height (Tomasko
# 2008); Doose et al. 2016 revision: optical-depth scale height ~50 km above
# ~100 km, transitioning to roughly linear optical-depth growth below, with a
# condensate extinction increase under 55 km.
TITAN_HAZE_REGIMES: tuple[TitanHazeRegime, ...] = (
    TitanHazeRegime(80.0, None, 2.34),
    TitanHazeRegime(30.0, 80.0, 1.41),
    TitanHazeRegime(0.0, 30.0, 0.97),
)

# Detached haze layer: sharp extinction layer at 450-550 km, peak visibility
# ~500 km in the Cassini era — ~150 km above the Voyager-era layer — and
# descended to ~350-380 km across the 2009 equinox (Lavvas, Yelle & Vuitton
# 2009, Icarus 201, 626; West et al. 2011, GRL 38, L06204).
TITAN_DETACHED_LAYER_KM = (450.0, 550.0)

# Mars: Conrath 1975 (Icarus 24, 36) dust profile
# q(p) = q0 · exp(ν · (1 − p0/p)), p0 = 610 Pa — well-mixed near the surface,
# exponential fall-off above. ν = 0.007 ≈ deep mixing to ~60-70 km (dusty /
# storm conditions; Guzewich et al. 2013 usage); ν ≈ 0.3 confines dust to the
# lowest scale height (clear conditions). Global storms lift dust ≥ 50 km.
MARS_CONRATH_NU_DUSTY = 0.007
MARS_CONRATH_NU_CLEAR = 0.3

# Earth stratospheric background (Junge) layer: volcanically-quiescent
# extinction at 525 nm is ~1e-5 to 1e-4 km⁻¹ around 20-25 km; minimum
# tropical stratospheric AOD 0.0028 (GloSSAC v2 climatology — Thomason et
# al. 2018, ESSD 10, 469, CC-BY; netCDF at NASA ASDC for real profiles).
EARTH_STRATOSPHERIC_LAYER = {
    "center_km": 22.0,
    "extinction_per_km_525nm": (1e-5, 1e-4),
    "min_stratospheric_aod": 0.0028,
}

# Pluto's embedded haze layering (Gladstone et al. 2016; Cheng et al. 2017):
# ~20 layers, 1-4 km thick, mean separation 10.5 km, lowest at ~6 km altitude;
# haze brightness scale height steepens from ~50 km to ~30 km at 100-200 km.
PLUTO_HAZE_LAYERS = {
    "count": 20,
    "thickness_km": (1.0, 4.0),
    "mean_separation_km": 10.5,
    "lowest_km": 6.0,
}
