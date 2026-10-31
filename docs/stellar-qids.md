# Stellar and sky-culture QID lookups

Researched on 2026-10-25 against [Wikidata](https://www.wikidata.org/), using
its [entity search API](https://www.wikidata.org/w/api.php?action=help&modules=wbsearchentities)
and [query service](https://query.wikidata.org/). Labels, descriptions and
Wikipedia sitelinks were checked to distinguish astronomical subjects from
namesakes, languages, countries and disambiguation pages.

These are standalone QID constants following the existing tuple-valued topic
format. Constellations use `culture -> constellation -> tuple[QID, ...]`; the
other tables use `slug -> tuple[QID, ...]`. The tables are not registered in
`TOPIC_PAGE_TABLES`. Each constellation of `MODERN_IAU_CONSTELLATIONS`, and each
row of the other three tables that has a figure in a culture, has a
`/g/sky-<slug>` page ([groups.md](export-format/groups.md)), so the group
registry fetches its article and pictures. Each culture of the picker has a
`/g/culture-<key>` page; `SKY_CULTURE_ARTICLES` names the few that read an article
of `SKY_TRADITION_PAGES`, and the others read their own text. A page never reads
an article of `SKY_CULTURE_PEOPLE_PAGES`. The
family slugs are the star families of the extrasolar
export ([extrasolar.md](export-format/extrasolar.md), "Families"), and each
has a `/g/star-<family>` page ([groups.md](export-format/groups.md)) on the
first QID of its tuple; the other slugs name research subjects and are not
dataset IDs.

| File under `data/src/space_map_data/constants/stars/` | Contents |
| --- | --- |
| `constellations.py` | 88 IAU, five historical Western, 32 Chinese and 27 Indian constellation topics, and the figures each matches |
| `families.py` | 49 star families, with the root `classification`: their QIDs and the rules that tag a star |
| `cultures.py` | 15 sky-tradition topics and 75 cultural-group QIDs; the region groups of the culture picker |

The modern constellation set follows the [IAU list](https://www.iau.org/IAU/Astronomy-FAQs/Constellations.aspx).
Historical Western entries are Argo Navis, Antinous, Cerberus, Musca Borealis
and Quadrans Muralis.

The Chinese table contains all 28 lunar mansions and the four directional
figures. Wikidata has 343 items classed as Chinese constellations, but most have
no English label and its inventory extends well beyond the coherent mansion
system represented here. The Indian table contains all 27 canonical nakshatras.

A QID is matched to figures in `constellations.py`, and never through Wikidata.
A mansion is the figure with its number in nine cultures: `chinese`,
`chinese_manchu`, `modern_chinese` and, by their chart numbers, `chinese_chenzhuo`,
`chinese_song_dynasty`, `chinese_xianglin`, `chinese_yuan_dynasty`, `japanese` and
`korean`. An edition can name a mansion its own way (Southern Dipper for Dipper,
Leading Ox for Ox). Its page sits under `chinese`. A nakshatra is a figure of
`indian` and of `indian_nakshatras`, and its page sits under `indian_nakshatras`.
The historical Western constellations are figures of `greek_almagest`,
`greek_farnese`, `greek_leidenAratea`, `arabic_al-sufi`, `dien`, `ruelle` and
`modern`. Argo Navis sits under `greek_almagest`, Quadrans Muralis under `modern`,
and the others under `ruelle`.

The four directional figures have no figure in any culture, so they have no page.
The 27 lunar mansions of `tibetan` are not matched: their stars differ from the
nakshatras' and nothing in the culture gives the correspondence. `greek_almagest`'s
Eagle with Antinoos is Aquila and Antinous as one figure, so it links to neither.

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

`SKY_CULTURE_REGIONS` in `cultures.py` uses these slugs only as the name of a
culture in the picker where Stellarium has no translation, with a people's label
where no tradition item fits. That use asserts no equivalence either, and the
names above that do not resolve keep their English name. `journey-to-the-west` is
the novel ([Q70784](https://www.wikidata.org/wiki/Q70784)): it names
`modern_journey_to_the_west` in the languages Stellarium leaves out.

Absence means no exact item was verified in this search, not that Wikidata has
no such item. To inspect any stored QID, open `https://www.wikidata.org/wiki/<QID>`.
