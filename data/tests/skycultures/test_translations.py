"""Tests for Stellarium's translation catalogues."""

from space_map_data.skycultures.translations import (
    FIGURES,
    Catalogues,
    clean,
    load,
    parse,
)

CATALOGUE = r"""
msgid ""
msgstr ""
"Language: fr\n"

#. Chinese constellation, native: 毕宿
#. Egyptian constellation
msgid "Net"
msgstr "Filet"

#. Western zodiac
msgctxt "western zodiac sign"
msgid "Net"
msgstr ""

msgctxt "IAU constellation name"
msgid "Bull"
msgstr "Le Taureau"

#. Split over lines
msgid ""
"Long "
"name"
msgstr ""
"Nom "
"\"long\""

msgid "Untranslated"
msgstr ""
"""


def test_a_fuzzy_entry_is_not_translated():
    fuzzy = '#: a.json\n#, fuzzy, python-format\nmsgid "Crab"\nmsgstr "Crabe"\n'
    plain = '#. about fuzzy logic\nmsgid "Bull"\nmsgstr "Taureau"\n'
    assert parse(f"{fuzzy}\n{plain}") == {(None, "Bull"): "Taureau"}


def test_entries_are_found_by_context_and_id():
    entries = parse(CATALOGUE)
    assert entries == {
        (None, "Net"): "Filet",
        ("IAU constellation name", "Bull"): "Le Taureau",
        (None, "Long name"): 'Nom "long"',
    }


def test_an_entry_of_a_context_stays_apart_from_the_plain_one():
    catalogues = Catalogues({"fr": parse(CATALOGUE)})
    assert catalogues.labels("Net") == {"fr": "Filet"}
    assert catalogues.labels("Net", "western zodiac sign") == {}
    assert catalogues.labels("Bull") == {}


def test_a_value_equal_to_the_msgid_adds_nothing():
    assert Catalogues({"fr": {(None, "Lokono"): "Lokono"}}).labels("Lokono") == {}


def test_a_wrong_sense_goes_for_that_language_only():
    entries = {(None, "Dipper"): "Cincle plongeur"}
    catalogues = Catalogues({"fr": entries, "de": entries})
    assert catalogues.labels("Dipper") == {"de": "Cincle plongeur"}


def test_marks_and_spaces_go():
    assert clean(" \u200e\u200eقيطس\u200e ") == "قيطس"


def test_the_site_reads_the_simplified_and_the_european_files(tmp_path):
    for name in ("zh_CN", "zh_TW", "pt", "pt_BR"):
        path = tmp_path / FIGURES / f"{name}.po"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f'msgid "Lake"\nmsgstr "{name}"\n')
    catalogues = load(FIGURES, tmp_path)
    assert catalogues.labels("Lake") == {"zh": "zh_CN", "pt": "pt"}
