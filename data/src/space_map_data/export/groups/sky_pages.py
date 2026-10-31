"""The stars of the constellation pages (``sky-``), and the sky culture pages
(``culture-``).

Both read the served extrasolar export, so a page tells what the map draws: a
constellation lists the stars of its figure in its culture (`IAU_SKY_CULTURE`
for the IAU's 88, `SKY_PAGE_CULTURES` for the others), and the cultures of the
picker get a page each. The text of a culture page comes from
the matched cultures, with Stellarium's translations of it. Its licence travels
with it.
"""

import gzip
import html
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from space_map_data.constants.categories import CONSTELLATIONS_SLUG
from space_map_data.constants.stars.constellations import (
    SKY_PAGE_CULTURES,
    UNPAGED_CULTURE_PARENTS,
    sky_page_culture,
)
from space_map_data.constants.stars.cultures import (
    IAU_SKY_CULTURE,
    SKY_CULTURE_SLUG_PREFIX,
    SKY_CULTURE_TEXTS_LEFT_OUT,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.skycultures import (
    CULTURES_DIR,
    STELLARIUM,
    UNTRANSLATED_FLAGS,
    culture_credit,
    figure_star_ids,
)
from space_map_data.export.groups.family_pages import served_metadata, sitelink_rank
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.names import Names, ObjectNames
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX, StarObject
from space_map_data.extrasolar.tables import METADATA
from space_map_data.skycultures import translations
from space_map_data.skycultures.build import INDEX_FILE
from space_map_data.skycultures.licences import (
    NO_DERIVATIVES,
    NO_LICENCE,
    NON_COMMERCIAL,
    OPEN,
    TK_LABELS,
    UNKNOWN_LICENCE,
)
from space_map_data.skycultures.translations import Catalogues
from space_map_data.utils.content_stamp import content_stamp
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# A shorter introduction says what the people are, not what their sky is.
MIN_TEXT = 100
MAX_TEXT = 900
_INTRODUCTION = re.compile(
    r"^## (?:Introduction|Description)[ \t]*\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
# A mark of Stellarium's reference list, or a BibTeX key of Bucur's.
_KEY = r"[A-Za-z]+\d{4}[a-z]*"
_MARK = rf"\[(?:#\d+|{_KEY}(?:,\s*{_KEY})*)\]"
_REFERENCE = re.compile(rf"\s*{_MARK}(?:,\s*{_MARK})*")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(?<![\w*])\*{1,2}([^*\n]+?)\*{1,2}(?![\w*])")
_UNDERLINE = re.compile(r"(?<![\w_])_([^_\n]+?)_(?![\w_])")
_TAG = re.compile(r"<[^>]+>")
_SENTENCE_END = re.compile(r"(?<!Dr\.)(?<=[.!?])\s+(?=[A-Z\"“])")
MAX_TRANSLATED_LENGTH = 1.5
TEXT_TRANSLATORS = {
    "name": "Stellarium sky culture descriptions",
    "organisation": "Stellarium translators",
    "source": "https://github.com/Stellarium/stellarium/tree/master/po/stellarium-skycultures-descriptions",
    "license": "GPL-2.0",
}


@dataclass
class SkyPages:
    """Everything the group tier needs for the constellation and culture pages."""

    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    names: dict[str, Names] = field(default_factory=dict)
    # The labels of the figure of each page of another culture.
    page_labels: dict[str, dict[str, str]] = field(default_factory=dict)


def served_sky_pages_stamp(
    extrasolar_dir: Path = EXTRASOLAR_DIR,
    cultures_dir: Path = CULTURES_DIR,
    po_dir: Path = translations.PO_DIR,
) -> dict | None:
    """The token of the served cultures, their metadata entries, and stamps of
    the matched ones and of the descriptions catalogue, None with no export
    served. The token covers the culture files only; the page names, regions
    and figure counts come from the entries."""
    with served(extrasolar_dir):
        metadata = served_metadata(extrasolar_dir)
    table = (metadata or {}).get("skycultures")
    if table is None:
        return None
    index = cultures_dir / INDEX_FILE
    return {
        "token": table["token"],
        "cultures": table["cultures"],
        "matched": content_stamp(index) if index.exists() else None,
        "descriptions": {
            lang: content_stamp(path)
            for lang, path in translations.catalogue_paths(
                translations.CULTURES, po_dir
            ).items()
        },
    }


def _plain(markdown: str) -> str:
    """The words of a piece of a description, with no markup."""
    text = _TAG.sub("", markdown.replace("<br />", "\n"))
    text = _LINK.sub(r"\1", text)
    text = _EMPHASIS.sub(r"\1", text)
    return html.unescape(_UNDERLINE.sub(r"\1", text))


def _paragraphs(introduction: str) -> list[str]:
    """The paragraphs of an introduction. An image's caption is no paragraph."""
    out = []
    for block in re.split(r"\n\s*\n", introduction):
        plain = re.sub(r"\s*\n\s*", " ", _plain(block)).strip()
        if plain and not ("<img" in block and len(plain) < MIN_TEXT):
            out.append(plain)
    return out


def _excerpt(paragraphs: list[str], keep_marks: bool) -> str | None:
    """The whole sentences from the start of `paragraphs`, up to MAX_TEXT.

    It ends at a sentence that sends the reader elsewhere. The page has no
    reference list, so a reference mark goes. With `keep_marks` the text ends
    before the mark instead: the licence forbids a change, or the sentence
    needs its citation.
    """
    kept: list[str] = []
    length = 0
    for paragraph in paragraphs:
        sentences: list[str] = []
        for sentence in _SENTENCE_END.split(paragraph):
            if keep_marks and _REFERENCE.search(sentence):
                break
            sentence = _REFERENCE.sub("", sentence)
            if "://" in sentence or sentence.endswith(":"):
                break
            if length + len(sentence) > MAX_TEXT:
                break
            sentences.append(sentence)
            length += len(sentence)
        else:
            kept.append(" ".join(sentences))
            continue
        if sentences:
            kept.append(" ".join(sentences))
        break
    return "\n".join(kept) if length >= MIN_TEXT else None


def _introduction(record: dict) -> str | None:
    found = _INTRODUCTION.search(record.get("description") or "")
    return None if found is None or found[1].lstrip().startswith("#") else found[1]


def _own_text(record: dict) -> str | None:
    """The text of a matched culture, unchanged but for its markup."""
    if record["dataset"] != STELLARIUM:
        return _excerpt(_paragraphs(record["culture"].get("description") or ""), True)
    introduction = _introduction(record)
    if introduction is None:
        return None
    no_derivatives = NO_DERIVATIVES in record["licence"]["flags"]
    return _excerpt(_paragraphs(introduction), no_derivatives)


def _unmarked(paragraph: str) -> str:
    # `_EMPHASIS` needs a word break, which Chinese and Japanese do not have.
    return " ".join(_REFERENCE.sub("", paragraph).replace("**", "").split())


def _same_text(translated: list[str], english: list[str]) -> bool:
    """Whether an entry translates this English. Stellarium keeps an entry when
    the English is rewritten, and it then has other paragraphs or another
    length; no site language runs this much longer."""
    return (
        len(translated) == len(english)
        and not set(translated) & set(english)
        and sum(map(len, translated)) <= MAX_TRANSLATED_LENGTH * sum(map(len, english))
    )


def _text_translations(
    record: dict, text: str, catalogues: Catalogues
) -> dict[str, str]:
    """`text` by language, where the licence allows a translation and the
    entry holds the same words. An entry translates the whole introduction, so
    an excerpt that cuts a paragraph has none. An entry can be older than the
    English, or the English again: see `_same_text`."""
    introduction = _introduction(record)
    if (
        record["dataset"] != STELLARIUM
        or introduction is None
        or UNTRANSLATED_FLAGS & set(record["licence"]["flags"])
    ):
        return {}
    english = [_unmarked(paragraph) for paragraph in _paragraphs(introduction)]
    kept = [" ".join(paragraph.split()) for paragraph in text.split("\n")]
    if kept != english[: len(kept)]:
        return {}
    out = {}
    for lang, value in catalogues.labels(introduction.strip()).items():
        paragraphs = [_unmarked(paragraph) for paragraph in _paragraphs(value)]
        if _same_text(paragraphs, english):
            out[lang] = "\n".join(paragraphs[: len(kept)])
    return out


def culture_text(record: dict, catalogues: Catalogues | None = None) -> dict | None:
    """The text of a culture page with its licence, or None when the licence
    or the text does not allow one. It is a part of the source, so the credit
    says where the whole is."""
    licence = record["licence"]
    if (
        record["key"] in SKY_CULTURE_TEXTS_LEFT_OUT
        or licence["distribution"] not in (OPEN, NON_COMMERCIAL)
        or {NO_LICENCE, UNKNOWN_LICENCE, TK_LABELS} & set(licence["flags"])
    ):
        return None
    text = _own_text(record)
    if text is None:
        return None
    translated = _text_translations(record, text, catalogues or Catalogues())
    out = {
        "text": text,
        "distribution": licence["distribution"],
        "credit": culture_credit(record),
    }
    if translated:
        out |= {"translations": translated, "translation_credit": TEXT_TRANSLATORS}
    return out


def _culture_records(cultures_dir: Path) -> dict[str, dict]:
    """The matched cultures that the export serves, by key: Stellarium wins a
    key that Bucur also uses, as in `skycultures.select`."""
    index = cultures_dir / INDEX_FILE
    if not index.exists():
        logger.warning("Sky culture pages without text: no index at %s", index)
        return {}
    records: dict[str, dict] = {}
    for entry in sorted(
        json.loads(index.read_text())["cultures"],
        key=lambda entry: entry["dataset"] == STELLARIUM,
    ):
        records[entry["key"]] = json.loads((cultures_dir / entry["file"]).read_text())
    return records


def _figures_of(file: dict) -> list[dict]:
    """The figures of a culture file that its pages read."""
    return [
        figure
        for figure in file["figures"]
        if "page" in figure
        and (sky_page_culture(figure["page"]) or IAU_SKY_CULTURE) == file["key"]
    ]


def _page_stars(file: dict) -> dict[str, list[int]]:
    """The extrasolar IDs of the stars of each constellation, by page, in order
    of first use."""
    return {
        figure["page"]: list(dict.fromkeys(figure_star_ids(file["members"], figure)))
        for figure in _figures_of(file)
    }


def _child_pages(
    cultures: list[dict], figures: dict[str, list[int]]
) -> dict[str, list[str]]:
    """The child pages of the Constellations page, IAU first, and of each
    culture page."""
    children: dict[str, list[str]] = {}
    for slug in figures:
        key = sky_page_culture(slug) or IAU_SKY_CULTURE
        if key not in UNPAGED_CULTURE_PARENTS:
            children.setdefault(f"{SKY_CULTURE_SLUG_PREFIX}{key}", []).append(slug)
    for slugs in children.values():
        slugs.sort()
    children[CONSTELLATIONS_SLUG] = sorted(
        (f"{SKY_CULTURE_SLUG_PREFIX}{entry['key']}" for entry in cultures),
        key=lambda slug: (
            slug != f"{SKY_CULTURE_SLUG_PREFIX}{IAU_SKY_CULTURE}",
            slug,
        ),
    )
    return children


def _stars(
    reader: ExportReader,
    figures: dict[str, list[int]],
    star_objects: list[StarObject],
    names: ObjectNames,
) -> dict[str, list[NotableObject]]:
    """The members of each page: the stars with the most sitelinks first. A
    star with no entry takes the name of its Metadata row, as its page does."""
    entries = {star.id: star for star in star_objects}
    ids = sorted({id_ for stars in figures.values() for id_ in stars})
    rows = reader.rows(METADATA.slug, ids, ["name"])
    rank: Callable = partial(sitelink_rank, names.entities)
    qids = [entries[id_].qid if id_ in entries else None for id_ in ids]
    with ThreadPoolExecutor(8) as pool:
        sitelinks = dict(zip(ids, (found[0] for found in pool.map(rank, qids))))

    def member(id_: int) -> NotableObject:
        star = entries.get(id_)
        name = (rows.get(id_) or {}).get("name") or str(id_)
        return NotableObject(
            object_id=f"{PREFIX}{id_}",
            wikidata_qid=star.qid if star else None,
            names=names.star(star) if star else Names(name),
            diameter_km=None,
            first_obs=None,
            extrasolar=True,
            sitelinks_count=sitelinks[id_],
        )

    return {
        slug: [member(id_) for id_ in sorted(stars, key=lambda i: (-sitelinks[i], i))]
        for slug, stars in figures.items()
    }


def build_sky_pages(
    star_objects: list[StarObject],
    names: ObjectNames,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
    cultures_dir: Path = CULTURES_DIR,
) -> SkyPages:
    """Counts, members, names, text and child pages of the two page types.

    With no extrasolar export served, the pages have their article only.
    """
    out = SkyPages()
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        metadata = served_metadata(extrasolar_dir)
        table = (metadata or {}).get("skycultures")
        if table is None:
            logger.warning("Sky pages without stars: no cultures at %s", root)
            return out
        reader = ExportReader(root)
        figures: dict[str, list[int]] = {}
        for key in sorted({IAU_SKY_CULTURE, *SKY_PAGE_CULTURES.values()}):
            path = root / table["file"].format(key=key)
            file = json.loads(gzip.decompress(path.read_bytes()))
            figures |= _page_stars(file)
            for figure in _figures_of(file):
                if key != IAU_SKY_CULTURE:
                    out.page_labels[figure["page"]] = figure.get("labels", {})
        out.notable_members = _stars(reader, figures, star_objects, names)
    out.member_counts = {slug: len(stars) for slug, stars in figures.items()}

    records = _culture_records(cultures_dir)
    catalogues = translations.load(translations.CULTURES)
    cultures = [entry for entry in table["cultures"] if entry["group"]]
    for entry in cultures:
        slug = f"{SKY_CULTURE_SLUG_PREFIX}{entry['key']}"
        out.names[slug] = Names(entry["name"], entry["labels"])
        out.member_counts[slug] = entry["figures"]
        record = records.get(entry["key"])
        text = culture_text(record, catalogues) if record else None
        if text:
            out.extra_stats[slug] = GroupExtraStats(culture_text=text)
    out.member_counts[CONSTELLATIONS_SLUG] = len(cultures)
    out.children = _child_pages(cultures, figures)
    logger.info(
        "Sky pages: %d constellations with %d stars, %d cultures, %d with a text",
        len(figures),
        sum(len(stars) for stars in figures.values()),
        len(cultures),
        len(out.extra_stats),
    )
    return out
