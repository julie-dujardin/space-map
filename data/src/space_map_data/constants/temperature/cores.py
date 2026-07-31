"""Modelled central temperatures, in kelvin, as low-high brackets.

Separate from bodies.py because these are a different kind of claim. Nobody
has measured a planetary core: every value is the output of an interior model,
and published values for one body can differ by a factor of several depending
on the equation of state, the heavy-element distribution, and — since Juno —
whether the core is treated as distinct at all. A bracket is the honest form;
a single number would imply precision that does not exist.

Not exported yet. Kept here so the values and their provenance exist before
any decision about how to show them.
"""

from typing import NamedTuple


class CoreTemperature(NamedTuple):
    low_k: float
    high_k: float
    sources: tuple[str, ...]  # keys into TEMPERATURE_SOURCES


CORE_TEMPERATURES: dict[str, CoreTemperature] = {
    # The one core that is genuinely well constrained — helioseismology and
    # the neutrino flux both pin it. The bracket is model spread, not error.
    "naif-10": CoreTemperature(15.5e6, 15.7e6, ("bahcall2005",)),
    # Core-mantle boundary rather than centre: Hauck's 1475-1825 C is what
    # Mercury's models actually constrain. The centre is somewhat hotter.
    "naif-199": CoreTemperature(1750.0, 2100.0, ("hauck2013",)),
    # Venus has no seismic data at all, so this is the widest bracket of the
    # terrestrials — thermal-evolution models, anchored on an Earth-like
    # composition.
    "naif-299": CoreTemperature(4000.0, 5000.0, ("dumoulin2017",)),
    # Inner-core boundary 5530 K from the iron melting curve; the centre runs
    # a few hundred K hotter. Pure-iron melting is 6230 +/- 500 K, and light
    # elements depress it — which is why the bracket is asymmetric about it.
    "naif-399": CoreTemperature(5400.0, 6000.0, ("anzellini2013",)),
    # Apollo seismology puts a small partly-molten core at the centre; the
    # bracket straddles the iron-sulfur melting range that implies.
    "naif-301": CoreTemperature(1600.0, 1900.0, ("weber2011",)),
    # InSight sized and weighed the core; the temperature follows from the
    # mantle adiabat rather than from the seismology directly.
    "naif-499": CoreTemperature(2000.0, 2400.0, ("stahler2021",)),
    # Jupiter and Saturn: the low ends are classical three-layer adiabats, the
    # high ends post-Juno dilute-core models. The gap between them is the
    # open question, not a measurement uncertainty.
    "naif-599": CoreTemperature(15000.0, 36000.0, ("guillot2005", "helled2024")),
    "naif-699": CoreTemperature(8000.0, 12000.0, ("guillot2005", "helled2024")),
    # Ice giants: standard adiabatic models land near 6000 K, but models that
    # drop the fully-convective assumption reach several times that. Voyager 2
    # is the only visit, so nothing narrows it.
    "naif-799": CoreTemperature(6000.0, 28000.0, ("scheibe2019",)),
    "naif-899": CoreTemperature(6000.0, 28000.0, ("scheibe2019",)),
}
