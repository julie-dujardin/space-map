"""Download the wide binaries of El-Badry, Rix & Heintz 2021.

The catalogue pairs Gaia EDR3 sources that move together: 1.8 million pairs
within 1 kpc, each with the probability `R_chance_align` that the pair is a
chance alignment. Its source ids are the Gaia DR3 ids. A source is in one
pair at most, so the catalogue has no triples.

The Zenodo record holds one FITS table of 217 columns. The provider keeps it
as published, and writes the columns of PAIR_COLUMNS to a small Parquet file
beside it. It reads the FITS as a stream, BATCH_ROWS rows at a time, so the
1.8 GB table is never in memory.

Writes, below sources/stars/el-badry-2021/:
- all_columns_catalog.fits.gz  the catalogue, checked against the MD5 of the
                               record
- pairs.parquet                one row per pair, the columns of PAIR_COLUMNS
- columns.json                 type, unit and description of each column
- record.json                  the Zenodo record
- metadata.json                the record, the MD5, the columns and TERMS

Not taken: the shifted control sample (all_columns_catalog_shift.fits.gz)
and the scripts of the record.
"""

import gzip
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import httpx
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from astropy.io import fits

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.catalogues.fetch import md5_of
from space_map_data.download.providers.stars.gaia_bulk import ARROW_TYPES, Column
from space_map_data.download.providers.three_d.resumable import (
    AS_STORED,
    download_resumable,
)
from space_map_data.utils.files import SYNC_BYTES, flush_to_disk
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "el-badry-2021"
ZENODO_URL = "https://zenodo.org/api/records"
RECORD = 4435257
DOI_URL = "https://doi.org/10.5281/zenodo.4435257"
SOURCE_FILE = "all_columns_catalog.fits.gz"
PAIRS_FILE, COLUMNS_FILE, RECORD_FILE = "pairs.parquet", "columns.json", "record.json"
# 128 MB of FITS rows.
BATCH_ROWS = 1 << 17
EPOCH = 2016.0

TERMS = {
    "license": "CC BY 4.0",
    "terms_url": "https://zenodo.org/records/4435257",
    "distribution": "open",
    "note": (
        "The catalogue repeats Gaia EDR3 values, which are CC BY-NC 3.0 IGO."
        " The pairs, separations, R_chance_align and binary_type are the"
        " authors' own."
    ),
    "quotes": [
        {
            "url": f"{ZENODO_URL}/{RECORD}",
            "text": '"license": {"id": "cc-by-4.0"}',
        }
    ],
}

# Each column of pairs.parquet: its type, unit and description. A name that
# ends in 1 or 2 is of that star of the pair. The values are those of the FITS
# column of the same name, of the same type, except `sep_arcsec`.
_F64, _F32 = pa.float64(), pa.float32()
PAIR_COLUMNS: dict[str, tuple[pa.DataType, str | None, str]] = {
    "source_id1": (pa.int64(), None, "Gaia DR3 source_id of star 1"),
    "source_id2": (pa.int64(), None, "Gaia DR3 source_id of star 2"),
    "ra1": (_F64, "deg", "Right ascension of star 1, ICRS, epoch J2016.0"),
    "dec1": (_F64, "deg", "Declination of star 1, ICRS, epoch J2016.0"),
    "ra2": (_F64, "deg", "Right ascension of star 2, ICRS, epoch J2016.0"),
    "dec2": (_F64, "deg", "Declination of star 2, ICRS, epoch J2016.0"),
    "parallax1": (_F64, "mas", "Parallax of star 1"),
    "parallax_error1": (_F32, "mas", "Standard error of parallax1"),
    "parallax2": (_F64, "mas", "Parallax of star 2"),
    "parallax_error2": (_F32, "mas", "Standard error of parallax2"),
    "pmra1": (_F64, "mas/yr", "Proper motion of star 1 in RA, times cos(dec)"),
    "pmra_error1": (_F32, "mas/yr", "Standard error of pmra1"),
    "pmdec1": (_F64, "mas/yr", "Proper motion of star 1 in declination"),
    "pmdec_error1": (_F32, "mas/yr", "Standard error of pmdec1"),
    "pmra2": (_F64, "mas/yr", "Proper motion of star 2 in RA, times cos(dec)"),
    "pmra_error2": (_F32, "mas/yr", "Standard error of pmra2"),
    "pmdec2": (_F64, "mas/yr", "Proper motion of star 2 in declination"),
    "pmdec_error2": (_F32, "mas/yr", "Standard error of pmdec2"),
    "phot_g_mean_mag1": (_F32, "mag", "Gaia G magnitude of star 1"),
    "phot_bp_mean_mag1": (_F32, "mag", "Gaia BP magnitude of star 1"),
    "phot_rp_mean_mag1": (_F32, "mag", "Gaia RP magnitude of star 1"),
    "phot_g_mean_mag2": (_F32, "mag", "Gaia G magnitude of star 2"),
    "phot_bp_mean_mag2": (_F32, "mag", "Gaia BP magnitude of star 2"),
    "phot_rp_mean_mag2": (_F32, "mag", "Gaia RP magnitude of star 2"),
    "ruwe1": (_F32, None, "Renormalised unit weight error of star 1"),
    "ruwe2": (_F32, None, "Renormalised unit weight error of star 2"),
    "sep_arcsec": (_F64, "arcsec", "Separation on the sky, the FITS pairdistance"),
    "sep_AU": (_F64, "AU", "Projected separation, sep_arcsec * 1000 / parallax1"),
    "R_chance_align": (_F64, None, "Probability that the pair is a chance alignment"),
    "binary_type": (pa.string(), None, "MSMS, WDMS, WDWD, MS??, WD?? or ????"),
}
PAIRS_SCHEMA = pa.schema([(name, kind) for name, (kind, _, _) in PAIR_COLUMNS.items()])
# The FITS columns that are not in PAIR_COLUMNS under their own name.
_SEPARATION, _TYPE, _EPOCHS = (
    "pairdistance",
    "binary_type",
    ("ref_epoch1", "ref_epoch2"),
)
_DERIVED = frozenset({"sep_arcsec", _TYPE})


class ElBadryBinariesDownloader(Downloader):
    name = PROVIDERS.EL_BADRY_BINARIES

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        meta = json.loads(self.metadata_file.read_text())
        # A change of PAIR_COLUMNS writes pairs.parquet again from the FITS.
        return meta.get("record") == RECORD and meta.get("columns") == list(
            PAIR_COLUMNS
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(f"{ZENODO_URL}/{RECORD}", timeout=120.0)
        if response.status_code != 200:
            raise DownloadError(f"HTTP {response.status_code} for Zenodo {RECORD}")
        try:
            entry = {f["key"]: f for f in response.json()["files"]}[SOURCE_FILE]
            url = entry["links"]["self"]
            expected = entry["checksum"].removeprefix("md5:")
        except (ValueError, KeyError, TypeError) as error:
            raise DownloadError(f"Zenodo {RECORD}: unexpected record") from error
        source = self.out_dir / SOURCE_FILE
        # The file takes its name only after its MD5 check.
        if not source.exists() and not download_resumable(
            self.client,
            url,
            source,
            headers=AS_STORED,
            check=_md5_check(expected),
            sync_bytes=SYNC_BYTES,
        ):
            raise DownloadError(f"{url}: the fetch failed")
        rows = write_pairs(source, self.out_dir / PAIRS_FILE)
        (self.out_dir / COLUMNS_FILE).write_text(
            json.dumps([asdict(c) for c in pair_columns()], indent=2) + "\n"
        )
        (self.out_dir / RECORD_FILE).write_bytes(response.content)
        logger.info("El-Badry et al. 2021: %d pairs", rows)
        self._save_metadata(
            url,
            rows,
            complete=True,
            record=RECORD,
            md5=expected,
            columns=list(PAIR_COLUMNS),
            terms=TERMS,
        )


def pair_columns() -> list[Column]:
    """The type, unit and description of each column of pairs.parquet."""
    names = {kind: name for name, kind in ARROW_TYPES.items()}
    return [
        Column(name, names[kind], unit, description)
        for name, (kind, unit, description) in PAIR_COLUMNS.items()
    ]


def write_pairs(source: Path, dest: Path) -> int:
    """Write the columns of PAIR_COLUMNS from the FITS to `dest`. Returns the rows.

    Every position must be at EPOCH. The file is flushed to disk after each
    batch, because `dest` is on a network mount.
    """
    with fits.open(source) as hdul:
        header = hdul[1].header
        start = hdul.fileinfo(1)["datLoc"]
        # FITS stores big-endian numbers.
        dtype = hdul[1].columns.dtype.newbyteorder(">")
    rows, width = int(header["NAXIS2"]), int(header["NAXIS1"])
    if dtype.itemsize != width:
        raise DownloadError(
            f"{source.name}: rows of {width} bytes, columns of {dtype.itemsize}"
        )
    names = dtype.names or ()
    needed = (set(PAIR_COLUMNS) - _DERIVED) | {_SEPARATION, _TYPE, *_EPOCHS}
    missing = sorted(needed - set(names))
    if missing:
        raise DownloadError(f"{source.name}: no columns {', '.join(missing)}")

    part = dest.with_name(dest.name + ".part")
    done = 0
    with gzip.open(source, "rb") as raw, part.open("wb") as out:
        raw.seek(start)
        writer = pq.ParquetWriter(out, PAIRS_SCHEMA, compression="zstd")
        try:
            while done < rows:
                count = min(BATCH_ROWS, rows - done)
                data = raw.read(count * width)
                if len(data) != count * width:
                    raise DownloadError(f"{source.name}: the file ends at row {done}")
                writer.write_table(
                    _pairs(np.frombuffer(data, dtype=dtype), source.name)
                )
                flush_to_disk(out)
                done += count
        finally:
            writer.close()
        flush_to_disk(out)
    part.replace(dest)
    return done


def read_pairs(
    path: Path = OUT_DIR / PAIRS_FILE, columns: list[str] | None = None
) -> pa.Table:
    """The pairs, with these columns of PAIR_COLUMNS. All of them take 1.7 GB."""
    return pq.read_table(path, columns=columns)


def _pairs(block: np.ndarray, name: str) -> pa.Table:
    for epoch in _EPOCHS:
        if not np.all(block[epoch] == EPOCH):
            raise DownloadError(f"{name}: a {epoch} is not {EPOCH}")
    columns = {}
    for field in PAIRS_SCHEMA:
        if field.name == "sep_arcsec":
            values = block[_SEPARATION].astype(np.float64) * 3600.0
        elif field.name == _TYPE:
            columns[field.name] = pc.utf8_trim_whitespace(
                pa.array(block[_TYPE]).cast(pa.string())
            )
            continue
        else:
            values = block[field.name].astype(block[field.name].dtype.newbyteorder("="))
        # A missing Gaia value is NaN in the FITS and null in Parquet.
        mask = np.isnan(values) if values.dtype.kind == "f" else None
        columns[field.name] = pa.array(values, field.type, mask=mask)
    return pa.table(columns, schema=PAIRS_SCHEMA)


def _md5_check(expected: str) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        found = md5_of(path)
        if found != expected:
            raise DownloadError(f"{SOURCE_FILE}: MD5 {found}, Zenodo lists {expected}")

    return check
