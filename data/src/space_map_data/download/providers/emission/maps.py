"""Download the ionised-gas data that the 3D Milky Way's emission is built from.

The files are kept as published, below sources/emission/. Like the dust maps, each
provider names the files it takes and the tier of the data in its `terms`.
"""

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.dust.remote import (
    DustMapDownloader,
    Listing,
    Terms,
    head_file,
    zenodo_listing,
)
from space_map_data.download.zenodo import ZENODO_URL
from space_map_data.utils.paths import SOURCES_EMISSION_DIR

# The text of the licence field, as the Zenodo API sends it.
_ZENODO_CC_BY = '"license": {"id": "cc-by-4.0"}'


def _terms(
    license: str | None,
    url: str,
    distribution: str,
    note: str,
    quotes: tuple[tuple[str, str], ...] = (),
) -> Terms:
    """A quote is the address that carries the text and the text."""
    return {
        "license": license,
        "terms_url": url,
        "distribution": distribution,
        "note": note,
        "quotes": [{"url": address, "text": text} for address, text in quotes],
    }


class McCallumHalphaDownloader(DustMapDownloader):
    """McCallum et al. 2025, the H-alpha emissivity of the gas within 1.25 kpc.

    A photoionisation model of the local O stars through the Edenhofer 2024 dust,
    on a 1024^3 grid over 2.5 kpc. Not taken: the electron density cube (4.3 GB),
    which the render does not read.
    """

    name = PROVIDERS.MCCALLUM_HALPHA
    record = 15041318
    directory = SOURCES_EMISSION_DIR / "mccallum-2025"
    page_url = f"https://zenodo.org/records/{record}"
    sources = (f"{ZENODO_URL}/{record}",)
    wanted = ("ha_grid.fits", "sky_map_ha.fits", "ionizing_sources.fits", "README.md")
    expected_license = "cc-by-4.0"
    # The cube is built on the Edenhofer map and on Gaia parallaxes of the stars.
    terms = _terms(
        "CC BY 4.0. Derived from Gaia DR3 (CC BY-NC 3.0 IGO).",
        page_url,
        "non-commercial",
        "Zenodo states the licence on the record. The density comes from"
        " the Edenhofer 2024 dust map and the O-star distances from Gaia.",
        ((f"{ZENODO_URL}/{record}", _ZENODO_CC_BY),),
    )

    def listing(self) -> Listing:
        return zenodo_listing(self.client, self.record)


class FinkbeinerHalphaDownloader(DustMapDownloader):
    """Finkbeiner 2003, the full-sky H-alpha map (VTSS, SHASSA and WHAM) at 6 arcmin.

    The HEALPix Nside 1024 files of LAMBDA, V1.1: the map, its error and its mask.
    Not taken: the Cartesian copies and the Nside 512 files of 2003. LAMBDA lists
    no checksum.
    """

    name = PROVIDERS.FINKBEINER_HALPHA
    directory = SOURCES_EMISSION_DIR / "finkbeiner-2003"
    page_url = "https://lambda.gsfc.nasa.gov/product/foreground/fg_halpha_get.html"
    base_url = "https://lambda.gsfc.nasa.gov/data/foregrounds/fink_halpha/"
    wanted = (
        "Halpha_fwhm06_1024.fits",
        "Halpha_error_fwhm06_1024.fits",
        "Halpha_mask_fwhm06_1024.fits",
    )
    sources = (base_url,)
    expected_license = None
    # The tier of the catalogue manifests for a source that states no licence.
    terms = _terms(
        None,
        page_url,
        "non-commercial",
        "LAMBDA states no licence. Credit Finkbeiner 2003.",
    )

    def listing(self) -> Listing:
        return Listing(
            {
                name: head_file(self.client, self.base_url + name, name, None)
                for name in self.wanted
            },
            None,
        )


class WiseHiiDownloader(DustMapDownloader):
    """Anderson et al. 2014, the WISE Catalog of Galactic H II Regions, V3.0.

    The CSV of the catalogue's site, as the site's own table exports it. The site
    lists no checksum and serves no https.
    """

    name = PROVIDERS.WISE_HII
    directory = SOURCES_EMISSION_DIR / "wise-hii-v3"
    page_url = "http://astro.phys.wvu.edu/wise/"
    file = "WISE_HII_V3.0_website.csv"
    url = page_url + "catalog/" + file
    sources = (url,)
    wanted = (file,)
    expected_license = None
    terms = _terms(
        None,
        page_url,
        "non-commercial",
        "The site states no licence. Credit Anderson et al. 2014 (ApJS 212,"
        " 1) and the catalogue's site.",
    )

    def listing(self) -> Listing:
        return Listing(
            {self.file: head_file(self.client, self.url, self.file, None)}, None
        )
