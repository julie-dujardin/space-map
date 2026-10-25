"""Planets and their host stars in the search index.

Source files, in the extrasolar export (`space-map-extrasolar/v1/x/`):

    metadata.json               the planets section, with its token and paths
    planets/index.json.gz       every host, with its system
    planets/{system}.json.gz    the hosts and planets of one system

A host is an object document with the ID `x-<id>`, which the app routes as
any star of the catalogue. A host with an entry has main's object document
under that ID, with or without a description, so it gets the planet facts on
that document instead: a second document with the same ID replaces the
first, and main's has the localized names, the image and the sitelinks. A
planet is a document of its own kind, keyed as its page is: `x-<host>-b-<n>`.
"""

import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .base import extrasolar_pk, planet_pk
from .objects import build_object_documents

logger = logging.getLogger(__name__)

# Catalogues whose catalogue id is a name of the star. The archive's are
# numbers such as `2.58355`.
NAME_CATALOGUES = frozenset({"iau", "exoplanet-eu", "open-exoplanet-catalogue"})
# How a numbered catalogue id reads, by (catalogue, release).
NUMBERED = {
    ("gaia", "dr3"): "Gaia DR3 {}",
    ("hip", "2007"): "HIP {}",
    ("hd", "1949"): "HD {}",
}


def _read(root: Path, path: str, token: str) -> dict:
    content = json.loads(gzip.decompress((root / path).read_bytes()))
    if content["token"] != token:
        raise ValueError(f"{path}: token {content['token']}, expected {token}")
    return content


def designations(host: dict) -> list[str]:
    """The names and numbers a host goes by, besides its name."""
    found = []
    if host["catalogue_name"]:
        found.append(host["catalogue_name"])
    for item in host["cross_ids"]:
        catalogue, release, value = (
            item["catalogue"],
            item["release"],
            item["catalogue_id"],
        )
        if (catalogue, release) in NUMBERED:
            found.append(NUMBERED[catalogue, release].format(value))
        elif catalogue in NAME_CATALOGUES:
            found.append(value)
    return list(dict.fromkeys(found))


def host_document(host: dict) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": f"x-{host['id']}",
        "type": host["class"].replace(" ", "_"),
        "extrasolar": True,
        "planets": len(host["planets"]),
    }
    names = [name for name in designations(host) if name != host["name"]]
    if names:
        obj["designations"] = names
    return {
        "id": extrasolar_pk(host["id"]),
        "kind": "object",
        "name": host["name"],
        "object": obj,
    }


def planet_document(planet: dict, system: int, host_name: str) -> dict[str, Any]:
    values = planet["values"]
    fields: dict[str, Any] = {
        "host_id": f"x-{planet['host']}",
        "number": planet["number"],
        "system_id": f"x-{system}",
        "host_name": host_name,
        "designation": planet["designation"],
        "class": planet["class"],
        "status": planet["status"],
    }
    aliases = [name for name in planet["aliases"] if name != planet["name"]]
    if aliases:
        fields["aliases"] = aliases
    for name in ("discovery_year", "discovery_method"):
        if name in values:
            fields[name] = values[name]
    return {
        "id": planet_pk(planet["host"], planet["number"]),
        "kind": "planet",
        "name": planet["name"],
        "planet": fields,
    }


def _add_planet_facts(obj: dict[str, Any], host: dict[str, Any]) -> None:
    """Put the planet facts of the host object `host` on main's object `obj`.
    Main's type and names stay."""
    obj["extrasolar"] = True
    obj["planets"] = host["planets"]
    found = obj.get("designations", [])
    names = [name for name in host.get("designations", []) if name not in found]
    if names:
        obj["designations"] = found + names


def build_extrasolar_documents(
    extrasolar_dir: Path, export_dir: Path | None = None
) -> Iterator[dict[str, Any]]:
    """The object documents of the main export in `export_dir`, then the host
    and planet documents of the extrasolar export. A host with an object
    document gets its planet facts there and no document of its own."""
    hosts, planets = _read_documents(extrasolar_dir)
    objects = (
        () if export_dir is None else build_object_documents(export_dir, set(hosts))
    )
    merged = 0
    for doc in objects:
        host = hosts.pop(doc["id"], None)
        if host is not None:
            _add_planet_facts(doc["object"], host["object"])
            merged += 1
        yield doc
    logger.info("Put the planet facts of %d hosts on their star documents", merged)
    yield from hosts.values()
    yield from planets


def _read_documents(
    extrasolar_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The host documents by ID and the planet documents of the export."""
    root = extrasolar_dir / "v1" / "x"
    metadata_path = root / "metadata.json"
    if not metadata_path.exists():
        logger.warning("No extrasolar export at %s: no planets to index", root)
        return {}, []
    section = json.loads(metadata_path.read_text()).get("planets")
    if section is None:
        logger.warning("The extrasolar export at %s has no planets", root)
        return {}, []
    token = section["token"]
    index = _read(root, section["index"], token)
    hosts: dict[str, dict[str, Any]] = {}
    planets: list[dict[str, Any]] = []
    for key in sorted({host["system"] for host in index["hosts"]}):
        system = _read(root, section["system"].replace("{key}", str(key)), token)
        names = {host["id"]: host["name"] for host in system["hosts"]}
        for host in system["hosts"]:
            if host["planets"]:
                doc = host_document(host)
                hosts[doc["id"]] = doc
        for planet in system["planets"]:
            planets.append(planet_document(planet, key, names[planet["host"]]))
    logger.info("Indexing %d planets and %d host stars", len(planets), len(hosts))
    return hosts, planets
