"""Absorber-band coefficients (ozone on Earth) from column density and cross sections.

Density is a linear tent of half-width `width_km` peaking at `center_km`; a tent
of peak density n integrates to n*width, so n = N/width reproduces column N, and
beta(lambda) = n * sigma(lambda).
"""

from space_map_data.constants.atmosphere.bodies import AbsorberBand


def absorber_band(
    band: AbsorberBand | None,
) -> tuple[list[float], float, float]:
    """(absorption_per_km RGB, center_km, width_km); zeros when absent.

    width_km=1 in the empty case mirrors the frontend's divide-by-zero guard.
    """
    if band is None:
        return [0.0, 0.0, 0.0], 0.0, 1.0
    peak_density_m3 = band.column_m2 / (band.width_km * 1000.0)
    per_km = [
        round(peak_density_m3 * sigma * 1000.0, 9) for sigma in band.cross_section_m2
    ]
    return per_km, band.center_km, band.width_km
