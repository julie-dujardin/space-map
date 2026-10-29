# Planet family QIDs

Researched on 2026-10-29 against [Wikidata](https://www.wikidata.org/) and the
[List of planet types](https://en.wikipedia.org/wiki/List_of_planet_types)
(all five tables). Each link of the list was resolved through the English
Wikipedia API, with redirects followed. When a link went to a redirect, a
section or a broader article, Wikidata was searched for an item for the type
itself. Labels, descriptions and the P31 and P279 claims were checked for each
item.

`data/src/space_map_data/constants/planets/families.py` holds 23 planet
families, with the root `classification`, and their tree. Each family has a
`/g/planet-<family>` group ([groups.md](export-format/groups.md)) on the first
QID of its tuple.

## Root

Wikidata has no item for a planet classification, as
[stellar classification](https://www.wikidata.org/wiki/Q25377588) is for stars.
The root takes [exoplanet](https://www.wikidata.org/wiki/Q44559), because
[planet](https://www.wikidata.org/wiki/Q634) is the QID of the Planets category
already. List of planet types (Q6633999) and Planetary classification
(Q111527403) are Wikimedia lists.
[Sudarsky extrasolar planet classification](https://www.wikidata.org/wiki/Q778138)
covers the cloud classes of gas giants only.

## Ice giant

[Ice giant](https://www.wikidata.org/wiki/Q1319599) ("giant planet primarily
composed of elements heavier than hydrogen and helium", subclass of giant
planet Q21857994) is the family `ice-giant`, below `giant-planet`. Its rule
reads the heavy-element fraction of the interior models, so only the planets
of the Solar System can be in it: Uranus and Neptune. No exoplanet catalogue
gives a composition, so an exoplanet is never in it, not even as an estimate.

## Thresholds and their sources

The thresholds are in `constants/planets/families.py`. These are the ones
that decide where the Solar System planets go:

- Super-Earth: 1.9–10 M⊕, from
  [Charbonneau et al. 2009](https://arxiv.org/abs/0912.3229) ("planets with
  minimum masses of 1.9-10 times the Earth's mass"), and 1.25–2 R⊕, the
  super-Earth size class of
  [Borucki et al. 2011](https://arxiv.org/abs/1102.0541). Earth is not one.
- Super-Jupiter: more than 2 MJ, from
  [Kanodia 2024](https://arxiv.org/abs/2412.03416) ("super-Jupiters (≳ 2
  MJ)"). Jupiter is not one.
- Ice giant: a giant planet whose rock and ice, everything but hydrogen and
  helium, are more than 50 % and at most 99 % of its mass: the Rock-Ice
  Giant class of [Russell 2021](https://arxiv.org/abs/2108.03343), Table 1.

## Mini-Neptune

`mini-neptune` is the size class above the radius valley, below Neptune. Two
items name it: [mini-Neptune](https://www.wikidata.org/wiki/Q691537) and
[sub-Neptune](https://www.wikidata.org/wiki/Q97359320). The English article
Mini-Neptune redirects to Sub-Neptune. The page is on mini-Neptune, which has
27 Wikipedia articles; sub-Neptune has 10.

## Types without a family

Two types of the list have no item: soot planet (a red link) and silicate
planet (a section of Terrestrial planet).

The other 27 types of the list have an item, but our data cannot put a planet
in them:

- composition or interior: carbon, coreless, helium, iron and chthonian
  planet, gas dwarf;
- water, atmosphere, surface or climate: hycean, ocean, ice, desert, eyeball
  and lava planet, steam world;
- not in the export: extragalactic, rogue, trojan and hypothetical planet;
- Solar System terms: inferior, superior, inner, outer and classical planets;
- other: double planet (a system), circumtriple planet (the data does not say
  how many stars an orbit encloses), catastrophically evaporating planet (it
  needs a dust tail), Earth analog (habitability), protoplanet (a formation
  stage).

Ultra-short-period planet (Q1079825) is not on the list, but it is a family.
Ultra-hot Jupiter (Q16647617) is not a family: it needs the dayside
temperature, which the export does not have.

Absence means no exact item was verified in this search, not that Wikidata has
no such item. To inspect any stored QID, open `https://www.wikidata.org/wiki/<QID>`.
