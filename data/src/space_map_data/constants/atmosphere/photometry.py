"""Ground albedos + solar limb darkening. Consumed by export/atmospheres/
(`ground_albedo` per body + the `sun` limb-darkening block)."""

from typing import NamedTuple


class SurfaceAlbedo(NamedTuple):
    """Bond (bolometric energy budget) and visual geometric albedo. For the
    cloud-shrouded bodies these describe what the shell sits above (cloud
    top), not the solid surface."""

    bond: float
    geometric: float


# NSSDCA planetary fact sheets (2024-2025 revisions, archived copies), except
# where noted. Earth's split: mean TOA albedo 0.29 vs global clear-sky
# *surface* albedo ~0.15 — clouds roughly double surface→planetary (Stephens
# et al. 2015, Rev. Geophys. 53, 141); use ~0.15 for the ground-coupling term
# since the shell renders above the surface texture, clouds included in it.
SURFACE_ALBEDOS: dict[str, SurfaceAlbedo] = {
    "naif-299": SurfaceAlbedo(bond=0.77, geometric=0.689),  # cloud top
    "naif-399": SurfaceAlbedo(bond=0.294, geometric=0.434),
    "naif-499": SurfaceAlbedo(bond=0.250, geometric=0.170),
    "naif-999": SurfaceAlbedo(bond=0.72, geometric=0.52),
    # Triton: literature Bond spread is real — 0.65 (Nelson et al. 1990) to
    # 0.85±0.05 (Hillier et al. 1991); geometric 0.72 (NSSDCA).
    "naif-801": SurfaceAlbedo(bond=0.75, geometric=0.72),
}

# Albedo the sky's ground-bounce coupling uses: Bond (it weights an energy
# term), except Earth per the note above — the shell renders over a texture
# whose clouds already carry their share of the bounce.
GROUND_BOUNCE_ALBEDOS: dict[str, float] = {
    object_id: albedo.bond for object_id, albedo in SURFACE_ALBEDOS.items()
} | {"naif-399": 0.15}

# Triton spectral geometric albedos in the Voyager filters (Nelson et al.
# 1990, GRL 17, 1761) — the uv→green rise is the slightly pink-neutral RGB
# slope for ground coupling.
TRITON_FILTER_ALBEDOS = {"uv": 0.59, "violet": 0.68, "green": 0.81, "ir": 0.75}

# Titan's surface reflectance peaks ~0.18 at 830 nm with a red slope through
# the visible (Huygens DISR — Schröder & Keller 2008, PSS 56, 753). Only
# matters under the haze.
TITAN_SURFACE_REFLECTANCE_830NM = 0.18


# Solar limb darkening: I(µ)/I(1) = µ^α(λ) — the single-parameter power law
# of Hestroffer & Magnan 1998 (A&A 333, 338), fitted to Pierce & Slaughter
# 1977 / Neckel & Labs 1994 over 81% of the disc; matches observation to a
# few percent everywhere but the extreme limb. α(λ) ≈ -0.023 + 0.292/λ[µm],
# valid 416-1099 nm.
def sun_limb_darkening_alpha(wavelength_m: float) -> float:
    return -0.023 + 0.292 / (wavelength_m * 1e6)


# Evaluated at the render wavelengths (680/550/440 nm); table anchors from
# their Table 2: α(669.4) = 0.407, α(560.0) = 0.496, α(443.9) = 0.649.
SUN_LIMB_DARKENING_ALPHA_RGB = (0.406, 0.508, 0.641)
