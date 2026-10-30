"""Planets, their host stars, and star systems in the search index.

Source files, in the extrasolar export (`space-map-extrasolar/v1/x/`):

    metadata.json               the planets and systems sections, with their tokens and paths
    planets/index.json.gz       every host, with its system
    planets/{system}.json.gz    the hosts and planets of one system
    systems/index.json.gz       the star systems that a page draws up close, with their held stars

A host is an object document with the ID `x-<id>`, which the app routes as
any star of the catalogue. So is a star system of the systems index, and a
held star in it: a star with no point of its own ("Kepler-16 A"), with the ID
and name of its system. A host or a system with an entry has main's object
document under that ID, with or without a description, so it gets the planet
and system facts on that document instead: a second document with the same
ID replaces the first, and main's has the localized names, the image and the
sitelinks. A planet is a document of its own kind, keyed as its page is:
`x-<host>-b-<n>`. A planet with an entry takes the descriptions and aliases,
the sitelinks and the thumbnail of main's document of that entry, which is
not indexed on its own.

The names are those of the pages (`export.names`), from the `name` and
`names` of the system files: `name` and `name_{lang}`, and for a planet
`host_name` and `host_name_{lang}`.
"""

import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space_map_data.export.objects.stars import PLANET_ID

from .base import extrasolar_pk, planet_pk
from .objects import build_object_documents

logger = logging.getLogger(__name__)

# The type of a held star's document, as of a star's.
HELD_TYPE = "star"
# The fields of a system or held star document that another document with
# its ID takes.
SYSTEM_FACTS = ("stars", "system_id", "system_name")
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
    } | {f"name_{lang}": n for lang, n in host["names"].items()}


def planet_document(planet: dict, system: int, host: dict) -> dict[str, Any]:
    values = planet["values"]
    fields: dict[str, Any] = {
        "host_id": f"x-{planet['host']}",
        "number": planet["number"],
        "system_id": f"x-{system}",
        "host_name": host["name"],
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
    fields |= {f"host_name_{lang}": n for lang, n in host["names"].items()}
    return {
        "id": planet_pk(planet["host"], planet["number"]),
        "kind": "planet",
        "name": planet["name"],
        "planet": fields,
    } | {f"name_{lang}": n for lang, n in planet["names"].items()}


def system_document(system: dict) -> dict[str, Any]:
    """The document of a star system of the systems index."""
    return {
        "id": extrasolar_pk(system["id"]),
        "kind": "object",
        "name": system["name"],
        "object": {
            "id": extrasolar_pk(system["id"]),
            "type": system["class"].replace(" ", "_"),
            "extrasolar": True,
            "stars": system["stars"],
        },
    }


def held_document(held: dict, system: dict) -> dict[str, Any]:
    """The document of a held star of the systems index, in `system`."""
    return {
        "id": extrasolar_pk(held["id"]),
        "kind": "object",
        "name": held["name"],
        "object": {
            "id": extrasolar_pk(held["id"]),
            "type": HELD_TYPE,
            "extrasolar": True,
            "system_id": extrasolar_pk(system["id"]),
            "system_name": system["name"],
        },
    }


# Root fields of an object document that a planet document takes from it.
_ENTRY_FIELDS = ("sitelinks_count", "thumbnail")
_ENTRY_PREFIXES = ("description_",)


def _add_entry(planet: dict[str, Any], doc: dict[str, Any]) -> None:
    """Put the fields of main's object document `doc` of a planet's entry on
    the planet document `planet`."""
    for key, value in doc.items():
        if key in _ENTRY_FIELDS or key.startswith(_ENTRY_PREFIXES):
            planet[key] = value
    for key, value in doc["object"].items():
        if key.startswith("aliases_"):
            planet["planet"][key] = value


def _add_planet_facts(obj: dict[str, Any], host: dict[str, Any]) -> None:
    """Put the planet facts of the host object `host` on main's object `obj`.
    Main's type and names stay."""
    obj["extrasolar"] = True
    obj["planets"] = host["planets"]
    found = obj.get("designations", [])
    names = [name for name in host.get("designations", []) if name not in found]
    if names:
        obj["designations"] = found + names


def _add_system_facts(obj: dict[str, Any], system: dict[str, Any]) -> None:
    """Put the system facts of the object `system` of the systems index on
    the object `obj` of another document with its ID. Its type stays."""
    obj["extrasolar"] = True
    obj.update({key: system[key] for key in SYSTEM_FACTS if key in system})


def build_extrasolar_documents(
    extrasolar_dir: Path, export_dir: Path | None = None
) -> Iterator[dict[str, Any]]:
    """The object documents of the main export in `export_dir`, then the host
    and planet documents of the extrasolar export. A host with an object
    document gets its planet facts there and no document of its own. A planet
    with an entry gets the descriptions, aliases, sitelinks and thumbnail of
    the entry on its own document."""
    hosts, planets = _read_documents(extrasolar_dir)
    systems = _read_systems(extrasolar_dir)
    objects = (
        ()
        if export_dir is None
        else build_object_documents(
            export_dir, set(hosts) | set(planets) | set(systems)
        )
    )
    merged = 0
    entries = 0
    for doc in objects:
        if PLANET_ID.match(doc["id"]):
            # The entry of a planet the extrasolar export does not serve has no page.
            if (planet := planets.get(doc["id"])) is not None:
                _add_entry(planet, doc)
                entries += 1
            continue
        host = hosts.pop(doc["id"], None)
        if host is not None:
            _add_planet_facts(doc["object"], host["object"])
            merged += 1
        system = systems.pop(doc["id"], None)
        if system is not None:
            _add_system_facts(doc["object"], system["object"])
            merged += 1
        yield doc
    logger.info(
        "Put the facts of %d hosts and systems on their object documents, and"
        " the entries of %d planets on their planet documents",
        merged,
        entries,
    )
    for key, host in hosts.items():
        if (system := systems.pop(key, None)) is not None:
            _add_system_facts(host["object"], system["object"])
        yield host
    yield from systems.values()
    yield from planets.values()


def _read_documents(
    extrasolar_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The host and the planet documents of the export, by ID."""
    root = extrasolar_dir / "v1" / "x"
    metadata_path = root / "metadata.json"
    if not metadata_path.exists():
        logger.warning("No extrasolar export at %s: no planets to index", root)
        return {}, {}
    section = json.loads(metadata_path.read_text()).get("planets")
    if section is None:
        logger.warning("The extrasolar export at %s has no planets", root)
        return {}, {}
    token = section["token"]
    index = _read(root, section["index"], token)
    hosts: dict[str, dict[str, Any]] = {}
    planets: dict[str, dict[str, Any]] = {}
    for key in sorted({host["system"] for host in index["hosts"]}):
        system = _read(root, section["system"].replace("{key}", str(key)), token)
        by_id = {host["id"]: host for host in system["hosts"]}
        for host in system["hosts"]:
            if host["planets"]:
                doc = host_document(host)
                hosts[doc["id"]] = doc
        for planet in system["planets"]:
            doc = planet_document(planet, key, by_id[planet["host"]])
            planets[doc["id"]] = doc
    logger.info("Indexing %d planets and %d host stars", len(planets), len(hosts))
    return hosts, planets


def _read_systems(extrasolar_dir: Path) -> dict[str, dict[str, Any]]:
    """The documents of the systems index, by ID: each named system and each
    named held star."""
    root = extrasolar_dir / "v1" / "x"
    metadata_path = root / "metadata.json"
    if not metadata_path.exists():
        return {}
    section = json.loads(metadata_path.read_text()).get("systems")
    if section is None:
        logger.warning("The extrasolar export at %s has no systems index", root)
        return {}
    index = _read(root, section["index"], section["token"])
    docs: dict[str, dict[str, Any]] = {}
    for system in index["systems"]:
        if system["name"]:
            doc = system_document(system)
            docs[doc["id"]] = doc
        for held in system["held"]:
            doc = held_document(held, system)
            docs[doc["id"]] = doc
    logger.info("Indexing %d star systems and held stars", len(docs))
    return docs
