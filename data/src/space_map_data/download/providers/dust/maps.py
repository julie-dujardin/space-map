"""Download the dust maps that the 3D Milky Way is built from.

Every provider keeps the files as published, below sources/dust-maps/. The cube
for the render is built from them later, so no file is converted here. Each
provider names the files it takes and the ones it leaves.

A Zenodo or Dataverse host states a licence in its record. A run stops when
that licence differs from the one the provider expects. Planck and Gaia state
none in a record, and a provider that is complete does not ask again. The tier
of each map is in its `terms`. Gaia values are CC BY-NC 3.0 IGO, so the Gaia map
is `non-commercial`, and so is every map built from Gaia stars, as in the
catalogue manifests. The cubes of the EXPLORE record state no licence at all, so
they are `undecided`.
"""

from collections.abc import Sequence
from dataclasses import replace

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.dust.remote import (
    DustMapDownloader,
    Listing,
    Terms,
    dataverse_listing,
    dataverse_url,
    head_file,
    zenodo_listing,
)
from space_map_data.download.providers.stars import gaia_bulk
from space_map_data.download.zenodo import ZENODO_URL
from space_map_data.utils.paths import SOURCES_DUST_MAPS_DIR

# The text of the licence field, as the API sends it.
_ZENODO_CC_BY = '"license": {"id": "cc-by-4.0"}'
_DATAVERSE_CC0 = (
    '"license":{"name":"CC0 1.0",'
    '"uri":"http://creativecommons.org/publicdomain/zero/1.0"'
)

_PLANCK_USE_URL = "https://www.cosmos.esa.int/web/planck/planck-data-use"
PLANCK_ACKNOWLEDGEMENT = (
    "Based on observations obtained with Planck (http://www.esa.int/Planck),"
    " an ESA science mission with instruments and contributions directly"
    " funded by ESA Member States, NASA, and Canada."
)

_GAIA_TABLES_URL = f"{gaia_bulk.BULK_URL}/gdr3/Astrophysical_parameters/"
# The file of each table, below the folder of the table.
_GAIA_CHUNKS = {
    "total_galactic_extinction_map": "TotalGalacticExtinctionMap_001.csv.gz",
    "total_galactic_extinction_map_opt": "TotalGalacticExtinctionMapOpt_001.csv.gz",
}


def _terms(
    license: str | None,
    url: str,
    distribution: str,
    note: str,
    quotes: Sequence[tuple[str, str]] = (),
) -> Terms:
    """A quote is the address that carries the text and the text."""
    return {
        "license": license,
        "terms_url": url,
        "distribution": distribution,
        "note": note,
        "quotes": [{"url": address, "text": text} for address, text in quotes],
    }


def _zenodo_terms(note: str, gaia: str, *records: int) -> Terms:
    """CC BY 4.0 as the API of each Zenodo record states it. The map is built
    from the Gaia release `gaia`, so its tier is the one of Gaia."""
    return _terms(
        f"CC BY 4.0. Derived from {gaia} (CC BY-NC 3.0 IGO).",
        f"https://zenodo.org/records/{records[0]}",
        "non-commercial",
        note,
        [(f"{ZENODO_URL}/{record}", _ZENODO_CC_BY) for record in records],
    )


def _dataverse_terms(doi: str, gaia: str) -> Terms:
    """CC0 as the API of the Dataverse dataset states it. The map is built from
    the Gaia release `gaia`, so its tier is the one of Gaia."""
    return _terms(
        f"CC0 1.0. Derived from {gaia} (CC BY-NC 3.0 IGO).",
        f"https://doi.org/{doi}",
        "non-commercial",
        f"Dataverse states the licence on the dataset. The fit uses {gaia} parallaxes.",
        [(dataverse_url(doi), _DATAVERSE_CC0)],
    )


class EdenhoferDustDownloader(DustMapDownloader):
    """Edenhofer et al. 2024, 3D dust to 1.25 kpc, all sky.

    The record offers the mean only together with the standard deviation, as
    HEALPix spheres in log distance. Not taken: the posterior samples
    (19.5 GB and 24.7 GB), the Cartesian and l,b,d interpolations (2 pc voxels,
    8 to 19 GB each) and the catalogues of stars. `interp2box.py` makes any
    box from the HEALPix file.
    """

    name = PROVIDERS.EDENHOFER_DUST
    record = 10658339
    # The unit of the map is the extinction of Zhang, Green & Rix 2023 (ZGR23),
    # whose record holds the extinction curve. The record is a version of
    # Zenodo 7692680, the one that Edenhofer et al. cite.
    curve_record = 7811871
    curve_prefix = "zgr23/"
    directory = SOURCES_DUST_MAPS_DIR / "edenhofer-2024"
    page_url = f"https://zenodo.org/records/{record}"
    sources = (f"{ZENODO_URL}/{record}", f"{ZENODO_URL}/{curve_record}")
    wanted = (
        "mean_and_std_healpix.fits",
        "validation_with_less_data_but_2kpc_mean_and_std_healpix.fits",
        "readme.md",
        "interp2box.py",
        "interp2lbd.py",
        "zgr23/extinction_curve.txt",
        "zgr23/README.md",
    )
    expected_license = "cc-by-4.0"
    terms = _zenodo_terms(
        "Zenodo states the licence on the record. The files in zgr23/ come from"
        f" Zenodo {curve_record}, Zhang, Green & Rix, v1.2, with the same licence.",
        "Gaia DR3",
        record,
        curve_record,
    )

    def listing(self) -> Listing:
        main = zenodo_listing(self.client, self.record)
        curve = zenodo_listing(self.client, self.curve_record)
        if curve.license != main.license:
            raise DownloadError(f"Zenodo {self.curve_record}: another licence")
        files = dict(main.files)
        for name, file in curve.files.items():
            files[self.curve_prefix + name] = replace(
                file, name=self.curve_prefix + name
            )
        records = dict(main.records)
        for path, content in curve.records.items():
            records[self.curve_prefix + path] = content
        return Listing(files, main.license, records)


class BayestarDustDownloader(DustMapDownloader):
    """Green et al. 2019 (Bayestar19), 3D dust north of declination -30 degrees.

    The HDF5 file is the one that `dustmaps` reads. The FITS file holds the same
    map and is not taken.
    """

    name = PROVIDERS.BAYESTAR_DUST
    doi = "10.7910/DVN/2EJ9TX"
    directory = SOURCES_DUST_MAPS_DIR / "bayestar19"
    page_url = f"https://doi.org/{doi}"
    sources = (dataverse_url(doi),)
    wanted = ("bayestar2019.h5",)
    expected_license = "CC0 1.0"
    terms = _dataverse_terms(doi, "Gaia DR2")

    def listing(self) -> Listing:
        return dataverse_listing(self.client, self.doi)


class DecapsDustDownloader(DustMapDownloader):
    """Zucker et al. 2025 (DECaPS), 3D dust of the southern plane.

    The mean file holds the mean map and the quality flags, with the reliable
    distance range of each pixel. Not taken: the file with five samples, 33.8 GB.
    """

    name = PROVIDERS.DECAPS_DUST
    doi = "10.7910/DVN/J9JCKO"
    directory = SOURCES_DUST_MAPS_DIR / "decaps-2025"
    page_url = f"https://doi.org/{doi}"
    sources = (dataverse_url(doi),)
    wanted = ("decaps_mean.h5",)
    expected_license = "CC0 1.0"
    terms = _dataverse_terms(doi, "Gaia DR3")

    def listing(self) -> Listing:
        return dataverse_listing(self.client, self.doi)


class PlanckDustDownloader(DustMapDownloader):
    """Planck 2013 results XI, the all-sky model of thermal dust emission.

    One FITS file of HEALPix Nside 2048 from IRSA, with the optical depth at
    353 GHz and the dust temperature and index. IRSA lists no checksum.
    """

    name = PROVIDERS.PLANCK_DUST
    directory = SOURCES_DUST_MAPS_DIR / "planck-2013"
    page_url = "https://irsa.ipac.caltech.edu/data/Planck/release_1/all-sky-maps/maps/"
    file = "HFI_CompMap_ThermalDustModel_2048_R1.20.fits"
    url = page_url + file
    sources = (url,)
    wanted = (file,)
    expected_license = None
    # The tier of the catalogue manifests for a source that states no licence.
    terms = _terms(
        None,
        _PLANCK_USE_URL,
        "non-commercial",
        "Neither IRSA nor ESA states a licence. ESA asks for an acknowledgement"
        " and for a copy of each paper.",
        [(_PLANCK_USE_URL, PLANCK_ACKNOWLEDGEMENT)],
    )

    def listing(self) -> Listing:
        return Listing(
            {self.file: head_file(self.client, self.url, self.file, None)}, None
        )


class GaiaExtinctionMapDownloader(DustMapDownloader):
    """The Gaia DR3 total Galactic extinction map, two tables of one chunk each.

    `total_galactic_extinction_map_opt` is the optimised map and
    `total_galactic_extinction_map` is the fitting table that it comes from.
    Both are `non-commercial`.
    """

    name = PROVIDERS.GAIA_EXTINCTION_MAP
    directory = SOURCES_DUST_MAPS_DIR / "gaia-dr3-extinction"
    page_url = _GAIA_TABLES_URL
    sources = tuple(f"{_GAIA_TABLES_URL}{table}/" for table in _GAIA_CHUNKS)
    wanted = tuple(f"{table}/{file}" for table, file in _GAIA_CHUNKS.items())
    keep = frozenset(f"{table}/{gaia_bulk.MD5_FILE}" for table in _GAIA_CHUNKS)
    expected_license = None
    terms = _terms(
        "CC BY-NC 3.0 IGO",
        "https://www.cosmos.esa.int/web/gaia-users/license",
        "non-commercial",
        "Credit ESA/Gaia/DPAC.",
        [
            (
                "https://www.cosmos.esa.int/web/gaia-users/license",
                "Gaia data are distributed under the CC BY-NC 3.0 IGO license",
            )
        ],
    )

    def listing(self) -> Listing:
        files = {}
        for chunk in self.wanted:
            table, name = chunk.split("/")
            base = f"{self.page_url}{table}/"
            folder = self.out_dir / table
            folder.mkdir(parents=True, exist_ok=True)
            sums = gaia_bulk.fetch_md5sums(self.client, base, folder)
            if name not in sums:
                raise DownloadError(f"{base}: unexpected record, no MD5 for {name}")
            files[chunk] = head_file(self.client, base + name, chunk, sums[name])
        return Listing(files, None)


class ExploreDustDownloader(DustMapDownloader):
    """The EXPLORE dust cubes of Lallement et al. 2022 and Vergely et al. 2022.

    The record holds the input of the G-Tomo app, in FITS and HDF5. The files
    are named by the resolution kernel of the cube, 5, 10, 25 or 50 pc. The
    grid steps are 3, 5, 10 and 20 pc. The record states no licence. The HDF5
    copies are taken, with the l,b,d grid. Not taken: the FITS copies of the
    same cubes and the error cubes at 50 pc.
    """

    name = PROVIDERS.EXPLORE_DUST
    record = 10405177
    directory = SOURCES_DUST_MAPS_DIR / "explore-lallement-vergely"
    page_url = f"https://zenodo.org/records/{record}"
    sources = (f"{ZENODO_URL}/{record}",)
    wanted = (
        "explore_cube_density_values_005pc_v2.h5",
        "explore_cube_density_values_010pc_v2.h5",
        "explore_cube_density_values_025pc_v1.h5",
        "explore_cube_density_values_025pc_v2.h5",
        "explore_cube_density_values_050pc_v1.h5",
        "explore_cube_density_values_050pc_v2.h5",
        "grid_lbdext_0.5deg_5pc.h5",
    )
    expected_license = None
    terms = _terms(
        None,
        page_url,
        "undecided",
        "The Zenodo record has no licence field. Ask the authors before shipping.",
    )

    def listing(self) -> Listing:
        return zenodo_listing(self.client, self.record)


class DharmawardenaDustDownloader(DustMapDownloader):
    """Dharmawardena et al. 2024, all-sky dust density to 2.8 kpc.

    The median density and the median extinction on the l,b,d grid, with the
    bounds of the grid. Not taken: the 16th and 84th percentiles (3.1 GB each)
    and the Cartesian cube (21.7 GB), which the paper calls fit for
    visualisation only. The files are NumPy arrays.
    """

    name = PROVIDERS.DHARMAWARDENA_DUST
    record = 11448780
    directory = SOURCES_DUST_MAPS_DIR / "dharmawardena-2024"
    page_url = f"https://zenodo.org/records/{record}"
    sources = (f"{ZENODO_URL}/{record}",)
    wanted = (
        "Density_Median_lbd.pkl.npy",
        "Ext_Median_lbd.pkl.npy",
        "lbdGrid_l_bounds.pkl.npy",
        "lbdGrid_b_bounds.pkl.npy",
        "lbdGrid_d_bounds.pkl.npy",
        "read_and_plot.ipynb",
    )
    expected_license = "cc-by-4.0"
    terms = _zenodo_terms(
        "Zenodo states the licence on the record. Its input catalogue holds Gaia DR2"
        " astrometry.",
        "Gaia DR2",
        record,
    )

    def listing(self) -> Listing:
        return zenodo_listing(self.client, self.record)
