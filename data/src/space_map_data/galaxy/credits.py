"""The papers and datasets the model Galaxy reads, as export credits.

An entry has the fields of a dust source: a citation makes it a paper, so the client
keeps it off the credit bar and lists it on /credits. Papers hold facts, so their
tier is `open`.
"""

PAPERS = {
    "gravity-2022": (
        "GRAVITY distance to the Galactic centre",
        "GRAVITY Collaboration 2022, arXiv:2112.07478",
        "https://arxiv.org/abs/2112.07478",
    ),
    "bennett-bovy-2019": (
        "The Sun's height above the Galactic plane",
        "Bennett & Bovy 2019, arXiv:1809.03507",
        "https://arxiv.org/abs/1809.03507",
    ),
    "lian-2024": (
        "Surface brightness profile of the Milky Way",
        "Lian et al. 2024, arXiv:2406.05604",
        "https://github.com/lianjianhui/Source-data-for-MW-size-paper",
    ),
    "bland-hawthorn-gerhard-2016": (
        "The Galaxy in context",
        "Bland-Hawthorn & Gerhard 2016, arXiv:1602.07702",
        "https://arxiv.org/abs/1602.07702",
    ),
    "wegg-gerhard-2013": (
        "The Galactic bulge from red clump stars",
        "Wegg & Gerhard 2013, arXiv:1308.0593",
        "https://arxiv.org/abs/1308.0593",
    ),
    "wegg-2015": (
        "The Milky Way's long bar",
        "Wegg, Gerhard & Portail 2015, arXiv:1504.01401",
        "https://arxiv.org/abs/1504.01401",
    ),
    "sormani-2022": (
        "The nuclear stellar disc",
        "Sormani et al. 2022, arXiv:2111.12713",
        "https://arxiv.org/abs/2111.12713",
    ),
    "deason-2019": (
        "Luminosity of the stellar halo",
        "Deason et al. 2019, arXiv:1908.02763",
        "https://arxiv.org/abs/1908.02763",
    ),
    "chen-2019": (
        "The warp from classical Cepheids",
        "Chen et al. 2019, arXiv:1902.00998",
        "https://arxiv.org/abs/1902.00998",
    ),
    "reid-2019": (
        "Spiral arms from maser parallaxes",
        "Reid et al. 2019, arXiv:1910.03357",
        "https://arxiv.org/abs/1910.03357",
    ),
    "drimmel-2025": (
        "Spiral arms from classical Cepheids",
        "Drimmel et al. 2025, arXiv:2406.09127",
        "https://arxiv.org/abs/2406.09127",
    ),
    "eilers-2020": (
        "Spiral arms of old stars",
        "Eilers et al. 2020, arXiv:2003.01132",
        "https://arxiv.org/abs/2003.01132",
    ),
    "drimmel-spergel-2001": (
        "Dust disc and arms of the Milky Way",
        "Drimmel & Spergel 2001, arXiv:astro-ph/0101259",
        "https://arxiv.org/abs/astro-ph/0101259",
    ),
    "riello-2021": (
        "Gaia photometric relations",
        "Riello et al. 2021, arXiv:2012.01916",
        "https://arxiv.org/abs/2012.01916",
    ),
    "willmer-2018": (
        "Absolute magnitudes of the Sun",
        "Willmer 2018, arXiv:1804.07788",
        "https://arxiv.org/abs/1804.07788",
    ),
    "harris-1996": (
        "Catalogue of Milky Way globular clusters",
        "Harris 1996 (2010 edition), AJ 112, 1487",
        "https://physwww.mcmaster.ca/~harris/mwgc.dat",
    ),
    # The DOI, as the star tree cites the two, so /credits lists each once.
    "pietrzynski-2019": (
        "Distance to the Large Magellanic Cloud",
        "Pietrzyński et al. 2019, arXiv:1903.08096",
        "https://doi.org/10.1038/s41586-019-0999-4",
    ),
    "graczyk-2020": (
        "Distance and depth of the Small Magellanic Cloud",
        "Graczyk et al. 2020, arXiv:2010.08754",
        "https://doi.org/10.3847/1538-4357/abbb2b",
    ),
    "van-der-marel-2001": (
        "Star counts of the Large Magellanic Cloud",
        "van der Marel 2001, arXiv:astro-ph/0105340",
        "https://arxiv.org/abs/astro-ph/0105340",
    ),
    "van-der-marel-2002": (
        "Thickness of the Large Magellanic Cloud",
        "van der Marel et al. 2002, arXiv:astro-ph/0205161",
        "https://arxiv.org/abs/astro-ph/0205161",
    ),
    "van-der-marel-kallivayalil-2014": (
        "Orientation of the Large Magellanic Cloud",
        "van der Marel & Kallivayalil 2014, arXiv:1305.4641",
        "https://arxiv.org/abs/1305.4641",
    ),
    "bothun-thompson-1988": (
        "Colours of the Magellanic Clouds",
        "Bothun & Thompson 1988, AJ 96, 877",
        "https://ui.adsabs.harvard.edu/abs/1988AJ.....96..877B",
    ),
    "lvdb": (
        "Local Volume Database",
        "Pace 2025, OJAp 8, 142",
        "https://github.com/apace7/local_volume_database",
    ),
}


def paper_credits(keys) -> list[dict]:
    """Credit entries for `keys`, in that order."""
    return [
        {
            "key": key,
            "name": PAPERS[key][0],
            "citation": PAPERS[key][1],
            "source": PAPERS[key][2],
            "license": "CC0 1.0" if key == "lvdb" else None,
            "distribution": "open",
        }
        for key in keys
    ]
