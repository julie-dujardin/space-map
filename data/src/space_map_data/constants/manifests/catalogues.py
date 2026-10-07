"""Catalogue download manifests, one YAML file for each object class.

An entry names one published catalogue, its reuse terms and where its files
are. The fields:

- `key`: directory name of the catalogue, a lower-case slug.
- `title`, `reference`: the name of the catalogue and the paper to cite.
- `license`: the licence the source states, or `None stated` with the wording
  of its request for credit.
- `terms_url`: the page that carries that wording.
- `distribution`: who may serve data made from the catalogue. `open`,
  `non-commercial` and `site-only` are the tiers of the texture manifests.
  `undecided` marks a source that states no licence.
- `cds`: `catalogue` is the CDS identifier, `files` the files to take.
- `zenodo`: `record` is the record number, `files` the files to take. No
  `files` takes every file.
- `urls`: plain URLs. An item is a URL, or a mapping with `url` and the
  optional `name`, `method` and `data` (form fields of a POST). When one item
  is a POST, the items are always fetched together and in order, because the
  form answer and the files it makes share one session.
- `refresh_days`: for a catalogue that changes. Absent means fetch once.

A file name is used once in an entry. `ReadMe` and `record.json` are taken.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

MANIFESTS_DIR = Path(__file__).parent / "catalogues"

# `undecided` marks a source that states no licence. It is not cleared for
# any export.
DISTRIBUTIONS = frozenset({"open", "non-commercial", "site-only", "undecided"})
# The provider writes these two files itself.
_PROVIDER_FILES = frozenset({"ReadMe", "record.json"})

_KEY = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_TEXT_FIELDS = ("title", "reference", "license", "terms_url", "distribution")
_FIELDS = frozenset({"key", *_TEXT_FIELDS, "cds", "zenodo", "urls", "refresh_days"})
_URL_FIELDS = frozenset({"url", "name", "method", "data"})


@dataclass(frozen=True)
class RemoteFile:
    """One file at a plain URL."""

    url: str
    name: str
    method: str = "GET"
    data: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CdsFiles:
    """Files of one catalogue in the CDS archive."""

    catalogue: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class ZenodoFiles:
    """Files of one Zenodo record. No names means every file."""

    record: int
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalogue:
    key: str
    title: str
    reference: str
    license: str
    terms_url: str
    distribution: str
    cds: CdsFiles | None = None
    zenodo: ZenodoFiles | None = None
    urls: tuple[RemoteFile, ...] = ()
    # The upstream changes. Fetch it again after this many days.
    refresh_days: int | None = None


def load_catalogues(group: str) -> list[Catalogue]:
    """The catalogues of one object class, in manifest order."""
    manifest = MANIFESTS_DIR / f"{group}.yaml"
    entries = (yaml.safe_load(manifest.read_text()) or {}).get("catalogues") or []
    catalogues = [_catalogue(entry, manifest.name) for entry in entries]
    repeated = _repeated(catalogue.key for catalogue in catalogues)
    if repeated:
        raise ValueError(f"{manifest.name}: repeated keys {repeated}")
    return catalogues


def _catalogue(entry: dict, manifest: str) -> Catalogue:
    key = entry.get("key")
    where = f"{manifest}: {key!r}"
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError(f"{where}: the key must be a lower-case slug")
    unknown = sorted(set(entry) - _FIELDS)
    if unknown:
        raise ValueError(f"{where}: unknown fields {unknown}")
    for field in _TEXT_FIELDS:
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise ValueError(f"{where}: `{field}` is missing")
    if entry["distribution"] not in DISTRIBUTIONS:
        raise ValueError(f"{where}: unknown distribution {entry['distribution']!r}")
    refresh_days = entry.get("refresh_days")
    if refresh_days is not None and (
        not isinstance(refresh_days, int) or refresh_days < 1
    ):
        raise ValueError(f"{where}: `refresh_days` must be a whole number of days")

    cds = entry.get("cds")
    zenodo = entry.get("zenodo")
    urls = tuple(_remote_file(item, where) for item in entry.get("urls") or [])
    if not (cds or zenodo or urls):
        raise ValueError(f"{where}: no `cds`, `zenodo` or `urls`")
    catalogue = Catalogue(
        key=key,
        title=entry["title"],
        reference=entry["reference"],
        license=entry["license"],
        terms_url=entry["terms_url"],
        distribution=entry["distribution"],
        cds=CdsFiles(cds["catalogue"], tuple(cds["files"])) if cds else None,
        zenodo=(
            ZenodoFiles(int(zenodo["record"]), tuple(zenodo.get("files") or ()))
            if zenodo
            else None
        ),
        urls=urls,
        refresh_days=refresh_days,
    )
    names = [remote.name for remote in urls]
    if catalogue.cds is not None:
        names += catalogue.cds.files
    if catalogue.zenodo is not None:
        names += catalogue.zenodo.files
    repeated = _repeated(names)
    if repeated:
        raise ValueError(f"{where}: repeated file names {repeated}")
    taken = sorted(_PROVIDER_FILES.intersection(names))
    if taken:
        raise ValueError(f"{where}: the provider writes {taken} itself")
    return catalogue


def _remote_file(item: str | dict, where: str) -> RemoteFile:
    if isinstance(item, str):
        return RemoteFile(url=item, name=_last_segment(item))
    unknown = sorted(set(item) - _URL_FIELDS)
    if unknown:
        raise ValueError(f"{where}: unknown URL fields {unknown}")
    url = item["url"]
    return RemoteFile(
        url=url,
        name=item.get("name") or _last_segment(url),
        method=item.get("method", "GET"),
        data=tuple((item.get("data") or {}).items()),
    )


def _last_segment(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _repeated(names) -> list[str]:
    return sorted(name for name, count in Counter(names).items() if count > 1)
