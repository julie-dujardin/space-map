"""The family masks of the Metadata tiles, from the Point source rows.

Bit n of a mask is family n of `constants.stars.families.FAMILIES`.
`families` holds the published families of a star, `families_estimated` the
families that need a Gaia estimate and are not published. The rules are in
that constants module.
"""

import re
from collections.abc import Iterable

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.stars import families as rules

FIELDS = (
    pa.field("families", pa.uint64()),
    pa.field("families_estimated", pa.uint64()),
)
# The spectral types in source order.
SPECTRAL_TYPES = ("simbad_sp_type", "sp_type", "host_spectral_type")
FLAME_RUNS = ("_spec", "")
COLUMNS = (
    "id",
    *SPECTRAL_TYPES,
    "simbad_otype",
    "spectraltype_esphs",
    "flags_esphs",
    "in_oba_golden_sample",
    "classlabel_espels",
    "classprob_dsc_combmod_whitedwarf",
    "teff_gspphot",
    *(
        f"{name}_flame{run}"
        for run in FLAME_RUNS
        for name in ("evolstage", "mass", "flags")
    ),
)

assert len(rules.FAMILIES) <= 64, "a family mask has 64 bits"
BIT = {family: np.uint64(1 << n) for n, family in enumerate(rules.FAMILIES)}
NONE = np.uint64(0)


def mask_of(families: Iterable[str]) -> np.uint64:
    mask = NONE
    for family in families:
        mask |= BIT[family]
    return mask


def _mask_of_states(state: int) -> np.uint64:
    return mask_of(f for f, states in rules.STATES.items() if states & state)


LETTER_MASK = _mask_of_states(rules.LETTER)
STAGE_MASK = _mask_of_states(rules.STAGE)


def _closed(family: str) -> np.uint64:
    mask = BIT[family]
    for parent in rules.PARENTS.get(family, ()):
        mask |= _closed(parent)
    return mask


# The families with parents, each with all of its parents.
CLOSED = tuple(
    (BIT[family], _closed(family))
    for family in rules.FAMILIES
    if family in rules.PARENTS
)


def closure(masks: np.ndarray) -> np.ndarray:
    """Each mask with the parents of its families."""
    out = masks.copy()
    for bit, closed in CLOSED:
        out[(masks & bit) != 0] |= closed
    return out


def counts(masks: np.ndarray) -> np.ndarray:
    """The number of masks with each family."""
    bits = np.unpackbits(
        masks.astype("<u8").view(np.uint8).reshape(-1, 8), axis=1, bitorder="little"
    )
    return bits[:, : len(rules.FAMILIES)].sum(axis=0, dtype=np.int64)


def states_of(masks: np.ndarray) -> np.ndarray:
    """What the families of each mask state, as LETTER and STAGE bits."""
    return np.where(masks & LETTER_MASK, rules.LETTER, 0) | np.where(
        masks & STAGE_MASK, rules.STAGE, 0
    )


# Codes 1 and up of the letters and stages; 0 is none.
LETTERS = tuple(
    sorted(
        {letter for letter, _ in rules.LETTER_STAGE_FAMILIES}
        | set(rules.LETTER_FAMILIES)
        | {letter for letter, _ in rules.ESP_LETTERS.values()}
    )
)
STAGES = tuple(
    sorted(
        {stage for _, stage in rules.LETTER_STAGE_FAMILIES}
        | set(rules.LUMINOSITY_CLASSES.values())
        | set(rules.PREFIX_STAGES.values())
        | {stage for _, stage in rules.FLAME_STAGES}
    )
)
LETTER_CODE = {letter: code for code, letter in enumerate(LETTERS, 1)}
STAGE_CODE = {stage: code for code, stage in enumerate(STAGES, 1)}
# The FLAME temperature floor of each letter code; 0 is none.
MIN_TEFF = np.array([rules.FLAME_MIN_TEFF.get(letter, 0) for letter in ("", *LETTERS)])


def _table() -> np.ndarray:
    """The families of each letter code with each stage code."""
    table = np.zeros((len(LETTERS) + 1, len(STAGES) + 1), np.uint64)
    for li, letter in enumerate((None, *LETTERS)):
        for si, stage in enumerate((None, *STAGES)):
            families = list(rules.LETTER_STAGE_FAMILIES.get((letter, stage), ()))
            if letter is not None:
                families += rules.LETTER_FAMILIES.get(letter, ())
            if stage is not None:
                families.append(stage)
            table[li, si] = mask_of(families)
    return table


TABLE = _table()

# Am stars: the K line, hydrogen and metal types. The hydrogen type stands
# for the star.
_AM = re.compile(
    r"(?:k[A-Z][\d.]*\s*)?h(?P<hydrogen>[OBAFGKM][\d.]*)\s*(?:m[A-Z][\d.]*)?"
)
_CLASS = re.compile(
    r"\s*(?P<prefix>esd|usd|sd|d|g|c)?"
    r"(?P<letter>MS|SC|OB|D[ABCOQZXP]*(?![a-z])|W[NCOR]|C(?=[-\d,(:\s]|$)"
    r"|S(?=[\d/:,\se]|$)|[RN](?=[\d\s:e.,]|$)|[LTY](?=\d)|[OBAFGKM](?!-rich))"
    r"[\d.]*(?:[-/][OBAFGKM]?[\d.]+)?"
    r"[\s:()\-]*"
    r"(?P<luminosity>0-Ia|Ia\+|Ia0|Iab|Ia|Ib|III|II|IV|VII|VI|V|I|0)?"
)
_BARIUM = re.compile(r"Ba(?![a-z])")


def parse_spectral_type(text: str) -> tuple[str | None, str | None, np.uint64]:
    """The letter and stage of an MK spectral type, and its other families.

    A composite type gives its first star. A letter is a key of LETTER_CODE,
    a stage a key of STAGE_CODE.
    """
    for word, word_families in rules.SPECTRAL_TYPE_WORDS.items():
        if text.startswith(word):
            return None, None, mask_of(word_families)
    am = _AM.match(text)
    if am is not None:
        text = am["hydrogen"] + text[am.end() :]
    found = _CLASS.match(text)
    if found is None:
        return None, None, NONE
    letter = found["letter"]
    if letter == "OB":
        letter = "B"
    elif letter[0] in "DW":
        letter = letter[0]
    prefix, luminosity = found["prefix"], found["luminosity"]
    stage = None
    if prefix in rules.SUBDWARF_PREFIXES or (prefix and luminosity is None):
        stage = rules.PREFIX_STAGES[prefix]
    elif luminosity is not None:
        stage = rules.LUMINOSITY_CLASSES["0" if luminosity == "0-Ia" else luminosity]
    # A white dwarf has no luminosity class: its V marks a pulsating star (DAV).
    if letter == "D":
        stage = None
    barium = (
        am is None
        and letter in rules.BARIUM_LETTERS
        and _BARIUM.search(text, found.end()) is not None
    )
    return letter, stage, BIT["barium-star"] if barium else NONE


def _spectral_codes(text: str) -> tuple[int, int, np.uint64]:
    letter, stage, extra = parse_spectral_type(text)
    return (
        0 if letter is None else LETTER_CODE[letter],
        0 if stage is None else STAGE_CODE[stage],
        extra,
    )


def _by_value(array: pa.Array | pa.ChunkedArray, map_one, null: tuple) -> np.ndarray:
    """`map_one` of each distinct value, one row per row of `array`, with
    `null` for a null value. Each result is a tuple of `len(null)` integers."""
    if isinstance(array, pa.ChunkedArray):
        array = array.combine_chunks()
    encoded = pc.dictionary_encode(array)
    values = [map_one(value) for value in encoded.dictionary.to_pylist()]
    table = np.array([*values, null], np.uint64).reshape(-1, len(null))
    return table[encoded.indices.fill_null(len(values)).to_numpy()]


STAGE_BITS = np.array([BIT[stage] for stage in STAGES], np.uint64)


def _published_stage(published: np.ndarray) -> np.ndarray:
    """The stage code of each mask with exactly one stage family, else 0."""
    found = (published[:, None] & STAGE_BITS) != 0
    return np.where(found.sum(axis=1) == 1, found.argmax(axis=1) + 1, 0)


def _masks(array, table: dict[str, tuple[str, ...]]) -> np.ndarray:
    return _by_value(array, lambda value: (mask_of(table.get(value, ())),), (0,))[:, 0]


def _numbers(rows: pa.Table, name: str) -> np.ndarray:
    return rows[name].cast(pa.float64()).fill_null(np.nan).to_numpy()


def _flame_stage(rows: pa.Table, letter: np.ndarray) -> np.ndarray:
    """The FLAME stage code of each row, from the first run whose fit holds
    for its `letter` code."""
    bounds = np.array([bound for bound, _ in rules.FLAME_STAGES])
    codes = np.array([STAGE_CODE[stage] for _, stage in rules.FLAME_STAGES])
    need = MIN_TEFF[letter]
    # Only the GSP-Phot temperature is stored. GSP-Spec fits no star that hot.
    teff = {"": _numbers(rows, "teff_gspphot"), "_spec": np.full(rows.num_rows, np.nan)}
    out = np.zeros(rows.num_rows, np.int64)
    for run in reversed(FLAME_RUNS):
        stage = _numbers(rows, f"evolstage_flame{run}")
        mass = _numbers(rows, f"mass_flame{run}")
        giant = pc.equal(
            pc.utf8_slice_codeunits(rows[f"flags_flame{run}"], 0, 1), "1"
        ).fill_null(False)
        giant = giant.to_numpy(zero_copy_only=False)
        low, high = rules.FLAME_GIANT_MASS
        holds = ~np.isnan(mass) & (~giant | ((mass >= low) & (mass <= high)))
        holds &= stage >= rules.FLAME_MIN_STAGE
        holds &= (need == 0) | (teff[run] >= need)
        at = np.minimum(np.searchsorted(bounds, stage, side="right"), bounds.size - 1)
        out = np.where(holds, codes[at], out)
    return out


def _esp_letter(rows: pa.Table) -> np.ndarray:
    """The letter code of each ESP-ELS tag whose quality holds."""
    quality = pc.utf8_slice_codeunits(rows["flags_esphs"], 1, 2).fill_null("")
    keys = pc.binary_join_element_wise(rows["spectraltype_esphs"], quality, "/")

    def code(key: str) -> tuple[int]:
        tag, digit = key.split("/")
        letter, holds = rules.ESP_LETTERS.get(tag, (None, frozenset()))
        return (LETTER_CODE[letter] if letter is not None and digit in holds else 0,)

    codes = _by_value(keys, code, (0,))[:, 0].astype(np.int64)
    golden = rows["in_oba_golden_sample"].fill_null(False)
    golden = golden.to_numpy(zero_copy_only=False)
    needs = np.isin(codes, [LETTER_CODE[letter] for letter in rules.GOLDEN_LETTERS])
    return np.where(needs & ~golden, 0, codes)


def masks(
    rows: pa.Table, classes: pa.Array | pa.ChunkedArray
) -> tuple[np.ndarray, np.ndarray]:
    """The published and the estimated family masks of the Point source `rows`.

    `classes` is the Metadata class of each row.
    """
    n = rows.num_rows
    spectral = pc.coalesce(*(rows[name] for name in SPECTRAL_TYPES))
    parsed = _by_value(spectral, _spectral_codes, (0, 0, 0))
    mk_letter, mk_stage = parsed[:, 0].astype(np.int64), parsed[:, 1].astype(np.int64)
    published = parsed[:, 2] | TABLE[mk_letter, mk_stage]
    published |= _masks(rows["simbad_otype"], rules.OTYPE_FAMILIES)
    published |= _masks(classes, rules.CLASS_FAMILIES)
    published = closure(published)
    # A stage that an object type gives joins the MK letter as an MK stage does.
    stage_known = np.where(mk_stage > 0, mk_stage, _published_stage(published))
    published = closure(published | TABLE[mk_letter, stage_known])

    fixed = states_of(published)
    fixed |= np.where(mk_letter > 0, rules.LETTER, 0)
    fixed |= np.where(stage_known > 0, rules.STAGE, 0)
    els = _masks(rows["classlabel_espels"], rules.ELS_FAMILIES)
    white_dwarf = (
        _numbers(rows, "classprob_dsc_combmod_whitedwarf")
        > rules.MIN_WHITE_DWARF_PROBABILITY
    )
    labels = np.zeros(n, np.uint64)
    for label in (els, np.where(white_dwarf, BIT["white-dwarf"], NONE)):
        kept = np.where(states_of(label) & fixed, NONE, label)
        labels |= kept
        fixed |= states_of(kept)

    letter = np.where(fixed & rules.LETTER, mk_letter, _esp_letter(rows))
    stage = np.where(fixed & rules.STAGE, stage_known, _flame_stage(rows, letter))
    every = closure(TABLE[letter, stage] | labels | published)
    return published, every & ~published
