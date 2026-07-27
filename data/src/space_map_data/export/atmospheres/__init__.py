"""Write `v1/atmospheres.json` — per-body scattering parameters for the
frontend's atmosphere shells, derived from the cited constants in
`constants/atmosphere/` (gas optics, reference-level conditions, aerosol
microphysics) rather than hand-tuned frontend tables.

Always-loaded like `systems/global.json`: the frontend fetches it once at boot
and builds a shell for every body present. Distinct aerosol phase LUTs are
shared via the `phases` table (bodies with the same aerosol assumption point at
one entry).
"""

import logging
import time
from pathlib import Path

import orjson

from space_map_data.constants.atmosphere.aerosols import AEROSOLS, PHASE_MODELS
from space_map_data.constants.atmosphere.bodies import (
    ATMOSPHERE_BODIES,
    RENDER_WAVELENGTHS_M,
)
from space_map_data.export.atmospheres.absorber import absorber_band
from space_map_data.export.atmospheres.phase import PHASE_N, build_phase_lut
from space_map_data.export.atmospheres.rayleigh import (
    mean_molar_mass_g_mol,
    rayleigh_beta_per_m,
    scale_height_km,
)
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

# Shell top: where the optical contribution dies. 8 Rayleigh scale heights
# leaves e^-8 ~ 3e-4 of the column; aerosols fade faster per height but start
# denser, 6 is enough. Reproduces the previously hand-picked per-body tops.
_TOP_RAYLEIGH_SCALE_HEIGHTS = 8.0
_TOP_MIE_SCALE_HEIGHTS = 6.0


def build_atmospheres() -> dict:
    """Assemble the full atmospheres payload (bodies + shared phase LUTs)."""
    bodies: dict[str, dict] = {}
    phases: dict[str, list[float]] = {}

    for object_id, body in ATMOSPHERE_BODIES.items():
        aerosol = AEROSOLS[body.aerosol]
        if aerosol.phase not in phases:
            lut, asymmetry = build_phase_lut(
                PHASE_MODELS[aerosol.phase], RENDER_WAVELENGTHS_M
            )
            phases[aerosol.phase] = lut
            logger.info(
                "Phase LUT %s: g=(%.3f, %.3f, %.3f)",
                aerosol.phase,
                asymmetry["r"],
                asymmetry["g"],
                asymmetry["b"],
            )

        rayleigh_per_km = [
            rayleigh_beta_per_m(
                body.composition, body.pressure_pa, body.temperature_k, wl
            )
            * 1000.0
            for wl in RENDER_WAVELENGTHS_M.values()
        ]
        molar_mass = mean_molar_mass_g_mol(body.composition)
        rayleigh_h_km = scale_height_km(
            molar_mass, body.temperature_k, body.gravity_m_s2
        )
        top_km = max(
            _TOP_RAYLEIGH_SCALE_HEIGHTS * rayleigh_h_km,
            _TOP_MIE_SCALE_HEIGHTS * aerosol.scale_height_km,
        )

        absorption_per_km, absorption_center_km, absorption_width_km = absorber_band(
            body.absorber
        )
        entry: dict = {
            "top_altitude_km": round(top_km),
            "rayleigh_scatter_per_km": [_sig(v) for v in rayleigh_per_km],
            "rayleigh_scale_height_km": round(rayleigh_h_km, 1),
            "mie_scatter_per_km": list(aerosol.scatter_per_km),
            "mie_absorption_per_km": list(aerosol.absorption_per_km),
            "mie_scale_height_km": aerosol.scale_height_km,
            "phase": aerosol.phase,
            "absorption_per_km": absorption_per_km,
            "absorption_center_km": absorption_center_km,
            "absorption_width_km": absorption_width_km,
            "baked_compensation": body.tuning.baked_compensation,
            "multi_scatter_gain": body.tuning.multi_scatter_gain,
            "sun_intensity": body.tuning.sun_intensity,
        }
        if body.tuning.realistic_sun_always:
            entry["realistic_sun_always"] = True
        bodies[object_id] = entry

    return {"phase_n": PHASE_N, "phases": phases, "bodies": bodies}


def _sig(value: float, digits: int = 4) -> float:
    """Round to `digits` significant figures — payload hygiene, the shader
    doesn't care past that."""
    if value == 0:
        return 0.0
    return float(f"{value:.{digits}g}")


def write_atmospheres(out_dir: Path) -> None:
    t0 = time.monotonic()
    payload = build_atmospheres()
    (out_dir / "atmospheres.json").write_bytes(orjson.dumps(payload))
    logger.info(
        "Wrote atmospheres.json (%d bodies, %d phase LUTs) in %.1fs",
        len(payload["bodies"]),
        len(payload["phases"]),
        time.monotonic() - t0,
    )


def export_atmospheres_only() -> None:
    """`space-map-export --only atmospheres` — additive, no DB needed."""
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_atmospheres(out_dir)
