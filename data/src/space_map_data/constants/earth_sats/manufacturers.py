"""Satellite / launcher manufacturers.

A manufacturer is the entity that *built* the hardware. Many manufacturers
also operate their own fleet (SpaceX, Rocket Lab, ICEYE, ...) — those entries
share the Wikidata QID with the matching :class:`OperatorSpec`, but keep a
distinct ``mfr-`` group slug so the URL/page never claims that a company
operates satellites it merely manufactured (Boeing builds many GEO sats for
Inmarsat/Intelsat/ABS etc.).

``slug`` is unique within MANUFACTURERS; the group registry prefixes with
``mfr-`` to avoid collisions with constellation/operator/launch-site slugs.
Coverage is intentionally partial — only well-known primes with stable
constellation attribution are listed today.
"""

from collections import defaultdict
from dataclasses import dataclass

# Group slug namespace: manufacturer group slugs are
# ``f"{MANUFACTURER_SLUG_PREFIX}{m.slug}"`` so they don't collide with bare
# constellation slugs, ``op-*`` operator slugs, or ``site-*`` launch-site slugs.
MANUFACTURER_SLUG_PREFIX = "mfr-"


@dataclass(frozen=True)
class ManufacturerSpec:
    name: str
    slug: str  # URL slug, unique within MANUFACTURERS; group registry prefixes with "mfr-"
    wikidata_qid: str | None = None
    constellations: tuple[str, ...] = ()  # constellation slugs this prime builds for


MANUFACTURERS: tuple[ManufacturerSpec, ...] = (
    # ----- Operator-and-manufacturer duals (slugs match operators.py) -----
    ManufacturerSpec(
        "SpaceX",
        "spacex",
        "Q193701",
        constellations=("starlink", "crew-dragon", "falcon", "dragon"),
    ),
    ManufacturerSpec(
        "Boeing",
        "boeing",
        "Q66",
        constellations=("ius",),  # Boeing builds many GEO sats for others —
        # those aren't claimed here, only the IUS upper stage they both build and operate.
    ),
    ManufacturerSpec(
        "Northrop Grumman",
        "northrop-grumman",
        "Q86894155",
        constellations=("cygnus", "minotaur", "antares"),
    ),
    ManufacturerSpec(
        "Rocket Lab",
        "rocket-lab",
        "Q116319",
        constellations=("electron",),
    ),
    ManufacturerSpec("ICEYE", "iceye", "Q31086161", constellations=("iceye",)),
    ManufacturerSpec(
        "IAI - Israel Aerospace Industries",
        "iai",
        "Q876017",
        constellations=("shavit",),
    ),
    ManufacturerSpec(
        "China Aerospace Science and Technology Corporation / CASC",
        "casc",
        "Q2777589",
        constellations=(
            "long-march",
            "yuanzheng",
            "jielong",
        ),
    ),
    ManufacturerSpec(
        "China Aerospace Science and Industry Corporation / CASIC",
        "casic",
        "Q10874081",
        constellations=("kuaizhou", "tianmu", "guowang"),
    ),
    ManufacturerSpec(
        "Planet Labs",
        "planet-labs",
        "Q17085620",
        constellations=("planet-flock", "planet-skysat", "planet-pelican"),
    ),
    ManufacturerSpec("Spire Global", "spire", "Q19877982", constellations=("spire",)),
    ManufacturerSpec(
        "Capella Space", "capella-space", "Q43401532", constellations=("capella",)
    ),
    ManufacturerSpec(
        "AST SpaceMobile",
        "ast-spacemobile",
        "Q112659289",
        constellations=("ast-spacemobile",),
    ),
    ManufacturerSpec(
        "Lynk Global", "lynk-global", "Q107675681", constellations=("lynk",)
    ),
    ManufacturerSpec(
        "HawkEye 360", "hawkeye-360", "Q104845338", constellations=("hawkeye360",)
    ),
    ManufacturerSpec(
        "Swarm Technologies", "swarm", "Q103484515", constellations=("spacebee",)
    ),
    ManufacturerSpec(
        "D-Orbit",
        "d-orbit",
        wikidata_qid="Q116214401",
        constellations=("d-orbit-ion",),
    ),
    ManufacturerSpec(
        "Firefly Aerospace",
        "firefly-aerospace",
        "Q17492679",
        constellations=("firefly",),
    ),
    ManufacturerSpec("Geespace", "geespace", "Q125167295", constellations=("geesat",)),
    ManufacturerSpec(
        "Chang Guang Satellite Technology",
        "chang-guang",
        "Q30259654",
        constellations=("jilin", "yunyao"),
    ),
    ManufacturerSpec(
        "ArianeGroup",
        "arianegroup",
        "Q19951610",
        constellations=("ariane", "vega"),
    ),
    ManufacturerSpec(
        "Indian Space Research Organisation",
        "isro",
        "Q229058",
        constellations=("pslv", "gslv"),
    ),
    ManufacturerSpec(
        "SpaceQuest", "spacequest", "Q7572201", constellations=("aprizesat",)
    ),
    ManufacturerSpec(
        "The Aerospace Corporation",
        "aerospace-corporation",
        "Q7712741",
        constellations=("aerocube",),
    ),
    ManufacturerSpec(
        "Shanghai Spacecom Satellite Technology",
        "shanghai-spacecom",
        "Q128693569",
        constellations=("qianfan",),
    ),
    ManufacturerSpec(
        "Vantor", "vantor", "Q136461484", constellations=("worldView-legion",)
    ),
    # ----- Manufacturer-only (no matching operator entry) -----
    ManufacturerSpec(
        "Lockheed Martin",
        "lockheed-martin",
        "Q7240",
        constellations=("aehf", "sbirs", "muos", "gps"),
    ),
    ManufacturerSpec(
        "Airbus Defence and Space",
        "airbus-ds",
        "Q15529123",
        constellations=("oneweb",),
    ),
    ManufacturerSpec(
        "Thales Alenia Space",
        "thales-alenia-space",
        "Q128356",
        constellations=("globalstar", "iridium"),
    ),
    ManufacturerSpec("OHB System", "ohb", "Q131651897", constellations=("galileo",)),
    ManufacturerSpec(
        "China Academy of Space Technology / CAST",
        "cast",
        "Q5099557",
        constellations=(
            "beidou",
            "gaofen",
            "fengyun",
            "tianlian",
            "chinasat",
            "zhongxing",
            "tiantong",
            "chinese-space-station",
        ),
    ),
    ManufacturerSpec(
        "ISS Reshetnev", "iss-reshetnev", "Q2371486", constellations=("glonass",)
    ),
    ManufacturerSpec(
        "Khrunichev State Research and Production Space Center",
        "khrunichev",
        "Q1197016",
        constellations=("proton", "proton-m"),
    ),
    ManufacturerSpec(
        "S.P. Korolev Rocket and Space Corporation Energia",
        "energia",
        "Q763402",
        constellations=(
            "molniya",
            "soyuz",
            "soyuz-rocket",
            "progress",
            "mir",
            "salyut",
        ),
    ),
    ManufacturerSpec(
        "NPO Lavochkin",
        "npo-lavochkin",
        "Q949211",
        constellations=("venera", "elektron"),
    ),
)


MANUFACTURER_BY_QID: dict[str, ManufacturerSpec] = {
    m.wikidata_qid: m for m in MANUFACTURERS if m.wikidata_qid is not None
}

MANUFACTURER_BY_SLUG: dict[str, ManufacturerSpec] = {m.slug: m for m in MANUFACTURERS}

assert len(MANUFACTURER_BY_SLUG) == len(MANUFACTURERS), "Duplicate manufacturer slug"

_by_constellation: dict[str, list[ManufacturerSpec]] = defaultdict(list)
for _mfr in MANUFACTURERS:
    for _slug in _mfr.constellations:
        _by_constellation[_slug].append(_mfr)
MANUFACTURER_BY_CONSTELLATION: dict[str, list[ManufacturerSpec]] = dict(
    _by_constellation
)
