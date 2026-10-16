"""Citable sources behind the rover traverses, for the /credits page.

Same shape as the other registries, keyed by the `sources` strings of the
traverse files (`probes/traverses.py`). A traverse puts a craft on its body, so
the panel of the craft credits these works.
"""

from typing import NamedTuple


class TraverseReference(NamedTuple):
    title: str
    url: str
    contribution: str
    # Two or three words for a panel credit line, in the style of the other
    # registries' notes.
    note: str = ""


TRAVERSE_SOURCES: dict[str, TraverseReference] = {
    "clpds": TraverseReference(
        "Lunar and Planetary Data Release System (CNSA / GRAS)",
        "https://clpds.bao.ac.cn/",
        "Positions of Yutu-2 and Zhurong, from the labels of their camera images",
        "rover positions",
    ),
    "mer_traverse": TraverseReference(
        "MER Analyst's Notebook, corrected traverse tables (PDS Geosciences Node)",
        "https://an.rsl.wustl.edu/merb/merxbrowser/meri/MER/traverse/",
        "Positions of Spirit and Opportunity at each stop of their drives",
        "rover positions",
    ),
    "viking_sites": TraverseReference(
        "NASA Science, Viking mission page",
        "https://science.nasa.gov/mission/viking/",
        "Planetocentric landing sites of Viking 1 and 2, which agree with the "
        "HiRISE images of the landers",
        "landing site",
    ),
    "karachevtseva_2013": TraverseReference(
        "Karachevtseva et al. 2013 (Planetary and Space Science 85)",
        "https://doi.org/10.1016/j.pss.2013.06.002",
        "Places of Lunokhod 1 at each lunar night, from its route mapped on LRO images",
        "Lunokhod 1 route",
    ),
    "karachevtseva_2017": TraverseReference(
        "Karachevtseva et al. 2017 (Icarus 283)",
        "https://doi.org/10.1016/j.icarus.2016.05.021",
        "Places of Lunokhod 2 at each lunar night and at its dated points of "
        "interest, from its route mapped on LRO images",
        "Lunokhod 2 route",
    ),
}
