"""The datasets and papers the emission reads, as export credits, in the fields of a
dust source. Each holds a citation, so the client lists it on /credits only."""

from space_map_data.download.providers.emission.maps import (
    FinkbeinerHalphaDownloader,
    McCallumHalphaDownloader,
    WiseHiiDownloader,
)


def _dataset(key: str, name: str, citation: str, provider) -> dict:
    terms = provider.terms
    return {
        "key": key,
        "name": name,
        "citation": citation,
        "source": provider.page_url,
        "license": terms["license"],
        "distribution": terms["distribution"],
    }


# Papers hold facts, so their tier is `open`.
PAPERS = {
    "makai-2017": (
        "Infrared and radio flux densities of Galactic H II regions",
        "Makai et al. 2017, doi:10.3847/1538-4357/aa84b6",
        "https://doi.org/10.3847/1538-4357/aa84b6",
    ),
    "mascoop-2021": (
        "Luminosity function of Galactic H II regions",
        "Mascoop et al. 2021, arXiv:2102.09033",
        "https://arxiv.org/abs/2102.09033",
    ),
    "ortiz-leon-2017": (
        "The distance to the Serpens/W40 complex",
        "Ortiz-Leon et al. 2017, arXiv:1610.03128",
        "https://arxiv.org/abs/1610.03128",
    ),
    "haffner-2009": (
        "The warm ionized medium in spiral galaxies",
        "Haffner et al. 2009, arXiv:0901.0941",
        "https://arxiv.org/abs/0901.0941",
    ),
    "brandt-draine-2012": (
        "Scattered H-alpha and diffuse Galactic light",
        "Brandt & Draine 2012, arXiv:1109.4175",
        "https://arxiv.org/abs/1109.4175",
    ),
    "draine-2003": (
        "Scattering by interstellar dust grains",
        "Draine 2003, arXiv:astro-ph/0304060",
        "https://www.astro.princeton.edu/~draine/dust/dustmix.html",
    ),
}


def credits() -> list[dict]:
    datasets = [
        _dataset(
            "mccallum-2025",
            "McCallum et al. 2025 3D H-alpha emissivity",
            "McCallum et al. 2025, arXiv:2503.14348",
            McCallumHalphaDownloader,
        ),
        _dataset(
            "finkbeiner-2003",
            "Full-sky H-alpha map (VTSS, SHASSA, WHAM)",
            "Finkbeiner 2003, arXiv:astro-ph/0301558",
            FinkbeinerHalphaDownloader,
        ),
        _dataset(
            "wise-hii-v3",
            "WISE Catalog of Galactic H II Regions V3.0",
            "Anderson et al. 2014, arXiv:1312.6202",
            WiseHiiDownloader,
        ),
    ]
    papers = [
        {
            "key": key,
            "name": name,
            "citation": citation,
            "source": source,
            "license": None,
            "distribution": "open",
        }
        for key, (name, citation, source) in PAPERS.items()
    ]
    return datasets + papers
