# Stellar and sky-culture QID lookups

Researched on 2026-10-25 against [Wikidata](https://www.wikidata.org/), using
its [entity search API](https://www.wikidata.org/w/api.php?action=help&modules=wbsearchentities)
and [query service](https://query.wikidata.org/). Labels, descriptions and
Wikipedia sitelinks were checked to distinguish astronomical subjects from
namesakes, languages, countries and disambiguation pages.

These are standalone QID constants following the existing tuple-valued topic
format. Constellations use `culture -> constellation -> tuple[QID, ...]`; the
other tables use `slug -> tuple[QID, ...]`. The tables are not registered in
`TOPIC_PAGE_TABLES`. The family slugs are the star families of the extrasolar
export ([extrasolar.md](export-format/extrasolar.md), "Families"), and each
has a `/g/star-<family>` page ([groups.md](export-format/groups.md)) on the
first QID of its tuple; the other slugs name research subjects and are not
dataset IDs.

| File under `data/src/space_map_data/constants/stars/` | Contents |
| --- | --- |
| `constellations.py` | 88 IAU, five historical Western, 32 Chinese and 27 Indian constellation topics |
| `families.py` | 48 star families: their QIDs and the rules that tag a star |
| `cultures.py` | 14 sky-tradition topics and 75 cultural-group QIDs |

The modern constellation set follows the [IAU list](https://www.iau.org/IAU/Astronomy-FAQs/Constellations.aspx).
Historical Western entries are Argo Navis, Antinous, Cerberus, Musca Borealis
and Quadrans Muralis.

The Chinese table contains all 28 lunar mansions and the four directional
figures. Wikidata has 343 items classed as Chinese constellations, but most have
no English label and its inventory extends well beyond the coherent mansion
system represented here. The Indian table contains all 27 canonical nakshatras.

The stellar entries overlap: luminosity classes, spectral types, evolution,
variability and remnants are useful topics, not a proposed family hierarchy.
`dwarf` is [dwarf star](https://www.wikidata.org/wiki/Q244393);
`main-sequence` is the [evolutionary sequence](https://www.wikidata.org/wiki/Q3450).
Yellow and orange dwarfs use the G-type and K-type main-sequence entries.
Brown dwarfs are included as substellar relatives.

Sky-culture research used the downloaded Stellarium and Bucur inventories to
identify subjects. `SKY_TRADITION_PAGES` contains astronomy traditions and related
topics; `SKY_CULTURE_PEOPLE_PAGES` contains the people themselves. A people entry
does not establish a QID for its astronomy or any particular star-chart edition.
The [IAU entry](https://www.wikidata.org/wiki/Q9241) is the constellation list,
and [Polynesian navigation](https://www.wikidata.org/wiki/Q826781) is a broader
navigation topic.

Some names need further research before dataset matching:

- Anutan: the identified Anuta item is an island, not a verified sky-tradition item.
- Boorong: the English article points to a person, so it is excluded. Wergaia is
  recorded independently, without asserting that it identifies the Boorong clan.
- Ava Guaraní: the English sitelink is a disambiguation page. The broad Guaraní
  entry does not resolve this subgroup.
- Lower Tanana and Tutchone: broader Tanana Athabaskans and separate Northern and
  Southern Tutchone peoples are recorded without assigning them to dataset rows.
- Netwar: the identified Lenakel item is a language, so it is excluded.
- Northern Andes and Armintxe Cave: no exact sky-tradition QID was verified.
- Korean, Japanese, Māori, Norse, Sámi, Mongolian, Balinese and Aztec astronomy:
  cultural-group entries were verified, but dedicated astronomy items were not.
- Individual Babylonian, Egyptian, Inuit and other Indigenous constellation
  figures do not have a complete verified set of Wikidata items.
- Al-Sufi, MUL.APIN, Dendera, Almagest, Farnese, Leiden Aratea, Chinese chart
  editions, Ruanui, Dien, Ruelle and modern chart variants remain distinct source
  editions; no equivalence to a broad culture or tradition is asserted here.

Absence means no exact item was verified in this search, not that Wikidata has
no such item. To inspect any stored QID, open `https://www.wikidata.org/wiki/<QID>`.
