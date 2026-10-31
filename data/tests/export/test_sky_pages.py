"""Tests for the members of the constellation pages and the culture pages."""

import json
from unittest.mock import MagicMock

from space_map_data.constants.stars.cultures import (
    SKY_CULTURE_ARTICLES,
    SKY_CULTURE_REGIONS,
    SKY_TRADITION_PAGES,
)
from space_map_data.export.groups.bundles import _child_group_refs
from space_map_data.export.groups.registry import GROUP_BY_SLUG, GROUPS, GroupType
from space_map_data.export.groups.sky_pages import (
    MAX_TEXT,
    _culture_pages,
    _page_name,
    _page_stars,
    culture_text,
    served_sky_pages_stamp,
)
from space_map_data.export.names import Names
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.skycultures.translations import Catalogues

LONG = "The sky of this people tells of the sea and of the seasons. " * 3


def _record(description: str, licence: str = "CC BY-SA 4.0", flags=(), tier="open"):
    return {
        "dataset": "stellarium",
        "key": "anutan",
        "name": "Anutan",
        "description": f"# Anutan\n\n## Introduction\n\n{description}\n\n## References\n",
        "authors": None,
        "source": {"commit": "abc", "path": "skycultures/anutan"},
        "licence": {
            "parts": [{"applies_to": "all", "licence": licence}],
            "distribution": tier,
            "flags": list(flags),
        },
    }


def test_a_constellation_lists_the_stars_of_its_figure_once():
    file = {
        "key": "modern_iau",
        "members": [{"id": 1}, {"id": 2}, {"ref": "M 42", "reason": "deep-sky"}],
        "figures": [
            {
                "id": "CON modern_iau Ori",
                "kind": "constellation",
                "names": [{"native": "Orion"}],
                "lines": [[0, 1], [1, 2, 0]],
                "page": "sky-orion",
                "slug": "Ori",
            },
            {
                "id": "AST x",
                "kind": "asterism",
                "names": [{"native": "Belt"}],
                "lines": [[0, 1]],
            },
        ],
    }
    assert _page_stars(file) == {"sky-orion": [1, 2]}


def test_a_page_reads_its_figure_in_its_own_culture():
    figure = {"lines": [[0]], "page": "sky-horn", "slug": "042"}
    file = {"members": [{"id": 1}], "figures": [figure]}
    assert _page_stars({**file, "key": "chinese"}) == {"sky-horn": [1]}
    assert _page_stars({**file, "key": "korean"}) == {}


def test_each_culture_of_the_picker_has_a_page():
    keys = {key for cultures in SKY_CULTURE_REGIONS.values() for key in cultures}
    pages = {g.slug for g in GROUPS if g.type is GroupType.SKY_CULTURE}
    assert pages == {f"culture-{key}" for key in keys}


def test_a_culture_page_reads_no_article_of_a_people():
    assert set(SKY_CULTURE_ARTICLES.values()) <= set(SKY_TRADITION_PAGES)
    assert GROUP_BY_SLUG["culture-modern_iau"].wikidata_qid == "Q9241"
    assert GROUP_BY_SLUG["culture-aztec"].wikidata_qid is None


def test_the_text_keeps_its_words_and_loses_its_markup():
    text = culture_text(
        _record(
            '<p><img src="a.png" />Anuta is a *tiny* [island](http://x.org) &amp; '
            f"home of navigators.[#1] {LONG}</p>"
        )
    )
    assert text is not None
    assert text["text"].startswith("Anuta is a tiny island & home of navigators. The")
    assert text["distribution"] == "open"
    assert text["credit"]["license"] == "CC BY-SA 4.0"


def test_a_text_is_cut_at_a_sentence():
    text = culture_text(_record(LONG * 10))
    assert text is not None
    assert len(text["text"]) <= MAX_TEXT
    assert text["text"].endswith(".")


def test_a_no_derivatives_text_ends_before_a_reference_mark():
    record = _record(
        f"{LONG}Stars guide them.[#1] The rest.",
        licence="CC BY-ND 4.0",
        flags=("no-derivatives",),
    )
    text = culture_text(record)
    assert text is not None
    assert "guide" not in text["text"]


def test_a_text_with_no_licence_or_with_labels_is_left_out():
    assert culture_text(_record(LONG, flags=("no-licence",))) is None
    assert culture_text(_record(LONG, flags=("tk-labels",))) is None
    assert culture_text(_record(LONG, tier="undecided")) is None


def test_a_sentence_about_the_people_is_no_text():
    assert (
        culture_text(_record("Inuit are the native population of the Arctic.")) is None
    )


def test_a_non_commercial_text_keeps_its_tier():
    text = culture_text(
        _record(LONG, "CC BY-NC-SA 4.0", ("non-commercial",), "non-commercial")
    )
    assert text is not None
    assert text["distribution"] == "non-commercial"


def test_a_bucur_text_comes_from_its_culture():
    record = _record("")
    record.update(dataset="bucur", culture={"description": LONG})
    record["source"]["path"] = "json/Anuta.json"
    text = culture_text(record)
    assert text is not None
    assert text["credit"]["organisation"] == "Doina Bucur"


def test_a_child_page_has_the_name_of_its_page():
    refs = _child_group_refs(
        ["culture-aztec"],
        "fr",
        MagicMock(spec=WikidataEntityCache),
        {"culture-aztec": 12},
        None,
        {"culture-aztec": Names("Aztec", {"fr": "Aztèques"})},
    )
    assert refs[0]["name"] == "Aztèques"
    assert refs[0]["n"] == 12


def _catalogues(msgid: str, **values: str) -> Catalogues:
    return Catalogues({lang: {(None, msgid): v} for lang, v in values.items()})


def test_a_text_reads_stellarium_s_translation_with_no_marks():
    source = f"{LONG}Stars guide them.[#1]"
    text = culture_text(_record(source), _catalogues(source, fr="Les étoiles.[#1]"))
    assert text is not None
    assert text["text"].endswith("guide them.")
    assert text["translations"] == {"fr": "Les étoiles."}
    assert text["translation_credit"]["license"] == "GPL-2.0"


def test_a_text_with_no_translation_keeps_english_alone():
    text = culture_text(_record(LONG), Catalogues({"fr": {}}))
    assert text is not None
    assert "translations" not in text
    assert "translation_credit" not in text


def test_a_no_derivatives_text_has_no_translation():
    record = _record(LONG, "CC BY-ND 4.0", ("no-derivatives",))
    text = culture_text(record, _catalogues(LONG.strip(), fr="Le ciel."))
    assert text is not None
    assert "translations" not in text


def test_a_text_cut_inside_a_paragraph_has_no_translation():
    source = LONG * 10
    text = culture_text(_record(source), _catalogues(source.strip(), fr="Le ciel."))
    assert text is not None
    assert "translations" not in text


def test_a_shorter_text_needs_the_same_paragraphs():
    source = f"{LONG}\n\nRead the list:"
    catalogues = Catalogues(
        {
            "fr": {(None, source.strip()): "Un.\n\nDeux."},
            "de": {(None, source.strip()): "Alles auf einmal."},
        }
    )
    text = culture_text(_record(source), catalogues)
    assert text is not None
    assert text["translations"] == {"fr": "Un."}


def test_an_entry_older_than_the_english_is_left_out():
    old = "Un autre texte. " * 20
    catalogues = Catalogues(
        {
            "fr": {(None, LONG.strip()): "Le ciel.\n\nLa mer."},
            "de": {(None, LONG.strip()): old},
            "ja": {(None, LONG.strip()): f"{LONG}\n"},
            "es": {(None, LONG.strip()): "El cielo."},
        }
    )
    text = culture_text(_record(LONG), catalogues)
    assert text is not None
    assert text["translations"] == {"es": "El cielo."}


def test_a_translation_loses_its_bold():
    text = culture_text(_record(LONG), _catalogues(LONG.strip(), zh="本**星空**文化。"))
    assert text is not None
    assert text["translations"] == {"zh": "本星空文化。"}


def test_a_bibtex_key_with_a_capital_goes_from_the_text():
    text = culture_text(_record(f"{LONG}[Ruelle1786] {LONG}"))
    assert text and "[" not in text["text"]


def test_the_iau_culture_comes_first_and_the_others_in_order():
    cultures = [{"key": key} for key in ("aztec", "modern_iau", "chinese")]
    assert _culture_pages(cultures) == [
        "culture-modern_iau",
        "culture-aztec",
        "culture-chinese",
    ]


def test_a_home_figure_goes_by_the_name_the_app_gives_it():
    labelled = {"names": [{"english": "Hunter"}], "labels": {"en": "Orion"}}
    assert _page_name(labelled) == "Orion"
    assert _page_name({"names": [{"native": "天", "english": "Sky"}]}) == "Sky"
    assert _page_name({"names": [{"native": "天"}]}) == "天"
    assert _page_name({"names": []}) is None


def test_the_stamp_follows_the_metadata_entries_and_the_descriptions(tmp_path):
    root = tmp_path / "x" / "v1" / "x"
    root.mkdir(parents=True)
    po = tmp_path / "po" / "stellarium-skycultures-descriptions"
    po.mkdir(parents=True)

    def stamp(group: str, text: str) -> dict | None:
        entry = {"key": "aztec", "labels": {}, "group": group, "figures": 3}
        table = {"token": "t", "cultures": [entry]}
        (root / "metadata.json").write_text(json.dumps({"skycultures": table}))
        (po / "fr.po").write_text(text)
        return served_sky_pages_stamp(tmp_path / "x", tmp_path, tmp_path / "po")

    first = stamp("americas", "a")
    assert stamp("americas", "a") == first
    assert stamp("oceania", "a") != first
    assert stamp("americas", "b") != first
