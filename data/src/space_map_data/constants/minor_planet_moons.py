"""Curated Wikidata QIDs for minor-planet moons (satellites of asteroids/TNOs).

These bodies have a Wikidata entity (instance-of P31 = Q657829 "minor planet
moon") and often a Wikipedia article, but no external-ID property our SPARQL
resolver can join on: their SPK-IDs are synthetic (see
``ingest/providers/objects/sbdb_moons.py``), so P716/P2956 never match. We
therefore hardcode the QID here and attach it at ingest by ``provisional_
designation`` — that key is unique, non-null, and stable, whereas a Wikidata
label routinely disagrees with ours on discovery year (WD ``S/2006 (7088) 1``
vs our ``S/2005 (7088) 1``), on numbered-vs-provisional parent token, and on
spelling (WD ``Ilmarë`` vs our ``Ilmare``).

Maintained by hand. The wikidata downloader's ``warn_minor_planet_moon_drift``
re-runs the P31 query and warns when Wikidata and this table diverge in either
direction, but these values stay authoritative — a live label match is too
flaky to link on.

Source query (https://query.wikidata.org):
    SELECT ?item WHERE { ?item wdt:P31 wd:Q657829 }
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MinorPlanetMoon:
    qid: str
    name: str  # common/IAU name, or provisional designation when unnamed
    designation: str  # our Object.provisional_designation — the join key
    parent: str  # parent minor planet, for drift diagnostics


# P31=Q657829 entities we deliberately don't link because there's no object to
# attach them to. Listed so the drift check doesn't re-flag them every run.
UNLINKED_MINOR_PLANET_MOON_QIDS: frozenset[str] = frozenset(
    {
        "Q97216632",  # S/2020 (2020 BX12) 1 — SBDB ships no satellite for 2020 BX12
    }
)

MINOR_PLANET_MOONS: tuple[MinorPlanetMoon, ...] = (
    MinorPlanetMoon("Q1401722", "Linus", "S/2001 (22) 1", "22 Kalliope"),
    MinorPlanetMoon("Q18483350", "Peneius", "S/2008 (41) 1", "41 Daphne"),
    MinorPlanetMoon("Q1377961", "Petit-Prince", "S/1998 (45) 1", "45 Eugenia"),
    MinorPlanetMoon("Q1385800", "Romulus", "S/2001 (87) 1", "87 Sylvia"),
    MinorPlanetMoon("Q1792859", "Remus", "S/2004 (87) 1", "87 Sylvia"),
    MinorPlanetMoon("Q18483196", "S/2000 (90) 1", "S/2000 (90) 1", "90 Antiope"),
    MinorPlanetMoon("Q15856551", "Aegis", "S/2009 (93) 1", "93 Minerva"),
    MinorPlanetMoon("Q15857826", "Gorgoneion", "S/2009 (93) 2", "93 Minerva"),
    MinorPlanetMoon("Q20160765", "S/2001 (107) 1", "S/2001 (107) 1", "107 Camilla"),
    MinorPlanetMoon("Q31822101", "S/2016 (107) 1", "S/2016 (107) 1", "107 Camilla"),
    MinorPlanetMoon("Q9325977", "S/2002 (121) 1", "S/2002 (121) 1", "121 Hermione"),
    MinorPlanetMoon("Q18483223", "S/2003 (130) 1", "S/2003 (130) 1", "130 Elektra"),
    MinorPlanetMoon("Q20160674", "S/2014 (130) 1", "S/2014 (130) 1", "130 Elektra"),
    MinorPlanetMoon("Q510728", "Dactyl", "S/1993 (243) 1", "243 Ida"),
    MinorPlanetMoon("Q20160764", "S/2003 (283) 1", "S/2003 (283) 1", "283 Emma"),
    MinorPlanetMoon("Q20160736", "S/2009 (317) 1", "S/2009 (317) 1", "317 Roxane"),
    MinorPlanetMoon("Q20160763", "S/2003 (379) 1", "S/2003 (379) 1", "379 Huenna"),
    MinorPlanetMoon("Q1536477", "Menoetius", "S/2001 (617) 1", "617 Patroclus"),
    MinorPlanetMoon("Q20160758", "Skamandrios", "S/2006 (624) 1", "624 Hektor"),
    MinorPlanetMoon("Q15221239", "Pichi üñëm", "S/2007 (702) 1", "702 Alauda"),
    MinorPlanetMoon("Q20160766", "S/2000 (762) 1", "S/2000 (762) 1", "762 Pulcova"),
    MinorPlanetMoon("Q20160759", "S/2005 (809) 1", "S/2005 (809) 1", "809 Lundia"),
    MinorPlanetMoon("Q20160760", "S/2004 (854) 1", "S/2004 (854) 1", "854 Frostia"),
    MinorPlanetMoon("Q20160754", "S/2007 (939) 1", "S/2006 (939) 1", "939 Isberga"),
    MinorPlanetMoon("Q20160688", "S/2013 (1052) 1", "S/2012 (1052) 1", "1052 Belgica"),
    MinorPlanetMoon("Q16674569", "S/2003 (1089) 1", "S/2003 (1089) 1", "1089 Tama"),
    MinorPlanetMoon("Q3943365", "S/2005 (1862) 1", "S/2005 (1862) 1", "1862 Apollo"),
    MinorPlanetMoon("Q16674565", "S/2001 (35107) 1", "S/1997 (35107) 1", "1991 VH"),
    MinorPlanetMoon("Q16327049", "S/2002 (48639) 1", "S/2002 (48639) 1", "1995 TL8"),
    MinorPlanetMoon("Q16674563", "S/2001 (31345) 1", "S/1998 (31345) 1", "1998 PG"),
    MinorPlanetMoon("Q14084502", "S/2001 (66063) 1", "S/2002 (66063) 1", "1998 RO1"),
    MinorPlanetMoon(
        "Q292049", "S/2000 (1998 WW31) 1", "S/2000 (1998 WW31) 1", "1998 WW31"
    ),
    MinorPlanetMoon("Q16327053", "S/2005 (82075) 1", "S/2002 (82075) 1", "2000 YW134"),
    MinorPlanetMoon(
        "Q11242316", "S/2001 (2001 QW322) 1", "S/2001 (2001 QW322) 1", "2001 QW322"
    ),
    MinorPlanetMoon(
        "Q18483378", "S/2008 (2001 XP254) 1", "S/2008 (469420) 1", "2001 XP254"
    ),
    MinorPlanetMoon("Q18483269", "S/2007 (119979) 1", "S/2006 (119979) 1", "2002 WC19"),
    MinorPlanetMoon(
        "Q18483368", "S/2008 (2002 XH91) 1", "S/2008 (524531) 1", "2002 XH91"
    ),
    MinorPlanetMoon(
        "Q18483233", "S/2003 (612687) 1", "S/2003 (612687) 1", "2003 UN284"
    ),
    MinorPlanetMoon("Q20160650", "S/2015 (357439) 1", "S/2015 (357439) 1", "2004 BL86"),
    MinorPlanetMoon(
        "Q65244607", "S/2012 (523624) 1", "S/2012 (523624) 1", "2008 CT190"
    ),
    MinorPlanetMoon("Q65561245", "S/2012 (2577) 1", "S/2012 (2577) 1", "2577 Litva"),
    MinorPlanetMoon(
        "Q114445216", "S/2018 (3548) 1", "S/2018 (3548) 1", "3548 Eurybates"
    ),
    MinorPlanetMoon("Q16674561", "S/1997 (3671) 1", "S/1997 (3671) 1", "3671 Dionysus"),
    MinorPlanetMoon("Q20160633", "S/2015 (4541) 1", "S/2015 (4541) 1", "4541 Mizuno"),
    MinorPlanetMoon("Q16674571", "S/2003 (5381) 1", "S/2003 (5381) 1", "5381 Sekhmet"),
    MinorPlanetMoon("Q16674579", "S/2006 (7088) 1", "S/2005 (7088) 1", "7088 Ishtar"),
    MinorPlanetMoon(
        "Q16327065", "S/2004 (17246) 1", "S/2004 (17246) 1", "17246 Christophedumas"
    ),
    MinorPlanetMoon("Q18483408", "S/2012 (38628) 1", "S/2012 (38628) 1", "38628 Huya"),
    MinorPlanetMoon("Q1280329", "Echidna", "S/2006 (42355) 1", "42355 Typhon"),
    MinorPlanetMoon("Q16327043", "Paha", "S/2001 (47171) 1", "47171 Lempo"),
    MinorPlanetMoon("Q83894", "Weywot", "S/2006 (50000) 1", "50000 Quaoar"),
    MinorPlanetMoon("Q218183", "Zoe", "S/2001 (58534) 1", "58534 Logos"),
    MinorPlanetMoon("Q776626", "Phorcys", "S/2006 (65489) 1", "65489 Ceto"),
    MinorPlanetMoon("Q25387442", "Dimorphos", "S/2003 (65803) 1", "65803 Didymos"),
    MinorPlanetMoon("Q3459099", "Squannit", "S/2001 (66391) 1", "66391 Moshup"),
    MinorPlanetMoon("Q847110", "Pabu", "S/2003 (66652) 1", "66652 Borasisi"),
    MinorPlanetMoon(
        "Q16674573", "S/2003 (69230) 1", "S/2003 (69230) 1", "69230 Hermes"
    ),
    MinorPlanetMoon("Q12871989", "Nunam", "S/2002 (79360) 1", "79360 Sila-Nunam"),
    MinorPlanetMoon(
        "Q2228372", "Sawiskera", "S/2001 (88611) 1", "88611 Teharonhiawako"
    ),
    MinorPlanetMoon("Q603083", "Vanth", "S/2005 (90482) 1", "90482 Orcus"),
    MinorPlanetMoon("Q343201", "Actaea", "S/2006 (120347) 1", "120347 Salacia"),
    MinorPlanetMoon("Q102656", "Dysnomia", "S/2005 (136199) 1", "136199 Eris"),
    MinorPlanetMoon("Q133295036", "Selam", "S/2025 (152830) 1", "152830 Dinkinesh"),
    MinorPlanetMoon("Q15859020", "Ilmarë", "S/2009 (174567) 1", "174567 Varda"),
    MinorPlanetMoon(
        "Q16327061", "S/2005 (208996) 1", "S/2005 (208996) 1", "208996 Achlys"
    ),
    MinorPlanetMoon("Q27496473", "Xiangliu", "S/2010 (225088) 1", "225088 Gonggong"),
    MinorPlanetMoon(
        "Q18483399", "Gǃòʼé ǃHú", "S/2008 (229762) 1", "229762 Gǃkúnǁʼhòmdímà"
    ),
    MinorPlanetMoon("Q16389421", "Thorondor", "S/2006 (385446) 1", "385446 Manwë"),
    MinorPlanetMoon(
        "Q18483387", "S/2009 (469705) 1", "S/2009 (469705) 1", "469705 ǂKá̦gára"
    ),
)


def minor_planet_moon_qids() -> set[str]:
    """Every hardcoded minor-planet-moon QID (for entity download seeding)."""
    return {m.qid for m in MINOR_PLANET_MOONS}


# provisional_designation → QID, the map the ingest joins on.
MINOR_PLANET_MOON_QID_BY_DESIGNATION: dict[str, str] = {
    m.designation: m.qid for m in MINOR_PLANET_MOONS
}
