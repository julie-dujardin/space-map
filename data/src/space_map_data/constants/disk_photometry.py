"""Published disk-resolved photometry of airless bodies: how the brightness of a
body falls from the centre of its disc to the limb. Keyed by object id, as the
export writes it.

`export/disk_photometry.py` turns each fit into the one number the renderer
takes: a factor on the lunar weight of McEwen (1996). A body with no record
keeps the weight of McEwen. Only measured fits are here. A body with an
atmosphere is drawn with the Lambert law, so it needs no record.

The Saturnian k values are from Buratti (1984). Hedman et al. (2020, AJ 159,
129, arXiv:1912.09192) quote them, and the values here are read from that
quote. Buratti gives a range for Dione (0.53-0.56) and Rhea (0.52-0.54); the
record keeps the middle of the range.
"""

from typing import NamedTuple

from space_map_data.constants.measured_shapes import Reference


class MinnaertFit(NamedTuple):
    """Minnaert exponent k = k0 + k1 * phase (degrees), r ∝ µ0^k µ^(k-1)."""

    k0: float
    k1: float
    phase_min_deg: float
    phase_max_deg: float
    reference: Reference


class LunarLambertFit(NamedTuple):
    """Lunar weight L = c0 + c1 * phase (degrees) of r ∝ 2L µ0/(µ0+µ) + (1-L) µ0,
    the form of McEwen."""

    c0: float
    c1: float
    phase_min_deg: float
    phase_max_deg: float
    reference: Reference


_BURATTI_1984 = Reference(
    title="Buratti 1984, Voyager disk resolved photometry of the Saturnian "
    "satellites, Icarus 59, 392",
    url="https://ui.adsabs.harvard.edu/abs/1984Icar...59..392B",
)

DISK_PHOTOMETRY: dict[str, MinnaertFit | LunarLambertFit] = {
    "naif-601": MinnaertFit(0.65, 0.0, 5, 17, _BURATTI_1984),  # Mimas
    "naif-602": MinnaertFit(0.78, 0.0, 5, 17, _BURATTI_1984),  # Enceladus
    "naif-603": MinnaertFit(0.63, 0.0, 5, 17, _BURATTI_1984),  # Tethys
    "naif-604": MinnaertFit(0.545, 0.0, 5, 17, _BURATTI_1984),  # Dione
    "naif-605": MinnaertFit(0.53, 0.0, 5, 17, _BURATTI_1984),  # Rhea
    # Methone, from Cassini images at 45-65°, as Hedman et al. (2020) quote it.
    "naif-632": MinnaertFit(
        0.887,
        -0.003,
        45,
        65,
        Reference(
            title="Thomas et al. 2013, The inner small satellites of Saturn: "
            "a variety of worlds, Icarus 226, 999",
            url="https://ui.adsabs.harvard.edu/abs/2013Icar..226..999T",
        ),
    ),
    # Ceres, Dawn clear filter, Table 3.
    "naif-2000001": LunarLambertFit(
        0.896,
        -8.87e-3,
        7,
        121,
        Reference(
            title="Schröder et al. 2017, Resolved spectrophotometric properties "
            "of the Ceres surface from Dawn Framing Camera images, Icarus 288, 201",
            url="https://doi.org/10.1016/j.icarus.2017.01.026",
        ),
    ),
    # Vesta, Dawn clear filter on approach, Table 3.
    "spkid-20000004": LunarLambertFit(
        0.830,
        -7.22e-3,
        7.5,
        109,
        Reference(
            title="Schröder et al. 2014, Resolved photometry of Vesta reveals "
            "physical properties of crater regolith, Planetary and Space Science",
            url="https://doi.org/10.1016/j.pss.2014.08.001",
        ),
    ),
}
