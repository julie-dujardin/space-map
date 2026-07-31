"""Citable sources behind the interior facts, for the /credits page.

One entry per work a number actually comes from, keyed by the `source` strings
used in `bodies.py` and `taxonomy.py`. Per-value provenance stays as comments
next to each constant; this is what gets exported.
"""

from typing import NamedTuple


class InteriorReference(NamedTuple):
    title: str
    url: str
    contribution: str


INTERIOR_SOURCES: dict[str, InteriorReference] = {
    # --- per-body interiors ------------------------------------------------
    "mcdonough_2003": InteriorReference(
        "McDonough 2003 (Treatise on Geochemistry 2.15)",
        "https://doi.org/10.1016/B0-08-043751-6/02015-6",
        "Earth's inner core, outer core and mantle masses; core element budget",
    ),
    "mcdonough_1995": InteriorReference(
        "McDonough & Sun 1995 (Chemical Geology 120)",
        "https://doi.org/10.1016/0009-2541(94)00140-4",
        "Bulk silicate Earth oxide composition",
    ),
    "dziewonski_1981": InteriorReference(
        "Dziewonski & Anderson 1981 (Phys. Earth Planet. Inter. 25)",
        "https://doi.org/10.1016/0031-9201(81)90046-7",
        "Preliminary Reference Earth Model — layer boundaries",
    ),
    "stahler_2021": InteriorReference(
        "Stähler et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abi7730",
        "Mars core radius and density from InSight seismic reflections",
    ),
    "knapmeyer_endrun_2021": InteriorReference(
        "Knapmeyer-Endrun et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf8966",
        "Mars crustal thickness and density from InSight receiver functions",
    ),
    "iess_2014": InteriorReference(
        "Iess et al. 2014 (Science 344)",
        "https://doi.org/10.1126/science.1250551",
        "Enceladus gravity field, ice-shell and ocean densities, core size",
    ),
    "khan_2021": InteriorReference(
        "Khan et al. 2021 (Science 373)",
        "https://doi.org/10.1126/science.abf2966",
        "Mars upper-mantle structure from InSight",
    ),
    # --- taxonomy → meteorite analogue ------------------------------------
    "demeo_2009": InteriorReference(
        "DeMeo et al. 2009 (Icarus 202)",
        "https://doi.org/10.1016/j.icarus.2009.02.005",
        "Bus-DeMeo taxonomy — the class definitions the estimates key off",
    ),
    "mahlke_2022": InteriorReference(
        "Mahlke, Carry & Mattei 2022 (A&A 665)",
        "https://doi.org/10.1051/0004-6361/202243587",
        "Asteroid taxonomy from spectra plus albedo",
    ),
    "krot_2014": InteriorReference(
        "Krot et al. 2014 (Treatise on Geochemistry 1.1)",
        "https://doi.org/10.1016/B978-0-08-095975-7.00102-9",
        "Meteorite classification and modal metal/sulphide/silicate abundances",
    ),
    "jarosewich_1990": InteriorReference(
        "Jarosewich 1990 (Meteoritics 25)",
        "https://doi.org/10.1111/j.1945-5100.1990.tb00717.x",
        "Bulk chemical analyses of stony and iron meteorites",
    ),
    "wasson_1988": InteriorReference(
        "Wasson & Kallemeyn 1988 (Phil. Trans. R. Soc. A 325)",
        "https://doi.org/10.1098/rsta.1988.0066",
        "Chondrite compositions — carbonaceous water and carbon contents",
    ),
    "berthier_2023": InteriorReference(
        "Berthier et al. 2023 (A&A 671)",
        "https://doi.org/10.1051/0004-6361/202244878",
        "SsODNet — the aggregated best-estimate taxonomies we ingest",
    ),
}
