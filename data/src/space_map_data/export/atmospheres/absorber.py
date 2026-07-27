"""Absorber-band coefficients (ozone on Earth) from column density + cross
sections.

The shader models the absorber as a linear tent: density rises from 0 at
`center - width` to a peak at `center` and back to 0 at `center + width`. A
tent of peak number density n integrates to a column of n * width, so the peak
density that reproduces a measured column N is n = N / width, and the peak
volume absorption coefficient is beta(lambda) = n * sigma(lambda).
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
