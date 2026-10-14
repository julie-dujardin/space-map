"""Geometric albedos of whole bodies in the V band, from published photometry.
Keyed by object id, as the export writes it.

`export/small_body_color.py` sets the brightness of a surface colour from
these. A body here takes this value before its Horizons albedo
(`moon_albedos.json`), its SBDB albedo or the albedo of its TrueColorTools
entry.

The values are at phase 0, with the opposition surge in them. The planets are
the whole disc, with the clouds. The values of Saturn's inner moons are from
Hubble images at true opposition.
"""

from typing import NamedTuple

from space_map_data.constants.measured_shapes import Reference


class GeometricAlbedo(NamedTuple):
    """V-band geometric albedo of the whole disc, and the work it comes from."""

    value: float
    reference: Reference


_MALLAMA_2017 = Reference(
    title="Mallama, Krobusek and Pavlov 2017, Comprehensive wide-band magnitudes "
    "and albedos for the planets, with applications to exo-planets and Planet "
    "Nine, Icarus 282, 19 (Table 7)",
    url="https://doi.org/10.1016/j.icarus.2016.09.023",
)
_VERBISCER_2007 = Reference(
    title="Verbiscer et al. 2007, Enceladus: cosmic graffiti artist caught in "
    "the act, Science 315, 815 (Table S1)",
    url="https://doi.org/10.1126/science.1134681",
)
_HELFENSTEIN_2025 = Reference(
    title="Helfenstein and Verbiscer 2025, On error estimates for Hapke "
    "photometric model parameters from disk-integrated phase curves of airless "
    "planetary bodies, Planetary Science Journal 6, 144 (Table 9)",
    url="https://doi.org/10.3847/PSJ/adcd5d",
)
_BLACKBURN_2010 = Reference(
    title="Blackburn et al. 2010, Solar phase curves and phase integrals for the "
    "leading and trailing hemispheres of Iapetus from the Cassini Visual "
    "Infrared Mapping Spectrometer, Icarus 209, 738",
    url="https://doi.org/10.1016/j.icarus.2010.04.011",
)

GEOMETRIC_ALBEDOS: dict[str, GeometricAlbedo] = {
    "naif-199": GeometricAlbedo(0.142, _MALLAMA_2017),  # Mercury
    "naif-299": GeometricAlbedo(0.689, _MALLAMA_2017),  # Venus
    "naif-399": GeometricAlbedo(0.434, _MALLAMA_2017),  # Earth
    "naif-499": GeometricAlbedo(0.170, _MALLAMA_2017),  # Mars
    "naif-599": GeometricAlbedo(0.538, _MALLAMA_2017),  # Jupiter
    "naif-699": GeometricAlbedo(0.499, _MALLAMA_2017),  # Saturn, globe only
    "naif-799": GeometricAlbedo(0.488, _MALLAMA_2017),  # Uranus
    "naif-899": GeometricAlbedo(0.442, _MALLAMA_2017),  # Neptune
    "naif-601": GeometricAlbedo(0.962, _VERBISCER_2007),  # Mimas
    "naif-602": GeometricAlbedo(1.375, _VERBISCER_2007),  # Enceladus
    "naif-603": GeometricAlbedo(1.229, _VERBISCER_2007),  # Tethys
    "naif-604": GeometricAlbedo(0.998, _VERBISCER_2007),  # Dione
    "naif-605": GeometricAlbedo(0.949, _VERBISCER_2007),  # Rhea
    # Iapetus: the mean of the dark leading (0.032) and the bright trailing
    # (0.46) hemisphere at 510 nm, as TrueColorTools reads Figs. 4 and 5.
    # Each hemisphere alone is wrong for the whole globe.
    "naif-608": GeometricAlbedo(0.246, _BLACKBURN_2010),
    "naif-999": GeometricAlbedo(0.506, _HELFENSTEIN_2025),  # Pluto
    "naif-901": GeometricAlbedo(0.408, _HELFENSTEIN_2025),  # Charon
}
