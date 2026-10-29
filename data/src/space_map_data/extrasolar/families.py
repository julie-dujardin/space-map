"""The family masks and the spectral type of a star, from its Point source
rows. The extrasolar export writes them to the Metadata tiles, and the star
systems of the ingest read the spectral type.

Bit n of a mask is family n of `constants.stars.families.FAMILIES`.
`families` holds the published families of a star, `families_estimated` the
families that need an estimate, from Gaia or a candidate type or list, and
are not published. The rules are in that constants module. `spectral_type`
is the MK type that the families read, so a client shows the type that gives
them.
"""

import re
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.stars import families as rules
from space_map_data.extrasolar.placement import MIN_PARALLAX_SNR

FIELDS = (
    pa.field("families", pa.uint64()),
    pa.field("families_estimated", pa.uint64()),
    pa.field("spectral_type", pa.string()),
)
# The spectral types in source order. The type of a SIMBAD system comes
# before Hipparcos, which often has an older type ("V* VY CMa").
SPECTRAL_TYPES = (
    "simbad_sp_type",
    "simbad_system_sp_type",
    "sp_type",
    "host_spectral_type",
)
OTYPES = ("simbad_otype", "simbad_system_otype", "host_simbad_otype")
CANDIDATE_OTYPES = ("simbad_otype", "host_simbad_otype")
# The columns that `spectral_type` reads.
SPECTRAL_COLUMNS = (
    *SPECTRAL_TYPES,
    "simbad_system_otype",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "classprob_dsc_combmod_whitedwarf",
)
FLAME_RUNS = ("_spec", "")
COLUMNS = (
    "id",
    *dict.fromkeys((*SPECTRAL_COLUMNS, *OTYPES, *CANDIDATE_OTYPES)),
    "parallax",
    "parallax_error",
    "distance",
    "host_distance",
    "phot_g_mean_mag",
    "spectraltype_esphs",
    "flags_esphs",
    "in_oba_golden_sample",
    "classlabel_espels",
    "teff_esphs",
    "logg_esphs",
    *(
        f"{name}_flame{run}"
        for run in FLAME_RUNS
        for name in ("evolstage", "mass", "flags")
    ),
    "vartype_gcvs",
    "class_spicy",
    "type_atnf",
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
# The letter codes whose stage comes from ESP-HS, with their temperature range.
ESPHS_LETTER = np.array([letter in rules.ESPHS_LETTERS for letter in ("", *LETTERS)])
ESPHS_TEFF = np.array(
    [rules.ESPHS_TEFF.get(letter, (np.nan, np.nan)) for letter in ("", *LETTERS)]
)


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

# Am stars: the K line, hydrogen and metal types (kA2hA5mA7V). The hydrogen
# type stands for the star, or the one type before the metal type (A0mA1Va).
_AM = re.compile(
    r"(?:(?:k[A-Z][\d.]*\s*)?h|(?=[AF][\d.]*m[OBAFGKM]))"
    r"(?P<hydrogen>[OBAFGKM][\d.]*)\s*(?:m[A-Z][\d.]*)?"
)
# The subtype can be in brackets (F(6)V) or have a "+" (K5+III). An O or B star
# can have N or C (ON8.5V). SIMBAD writes class 0 as "_0" (G2_0).
_CLASS = re.compile(
    r"\s*(?P<prefix>esd|usd|sd|d|g|c)?"
    r"(?P<letter>MS|SC|OB|D[ABCOQZXP]*(?![a-z])|W[NCOR]|C(?=[-\d,(:\s]|$)"
    r"|S(?=[\d/:,\se]|$)|[RN](?=[\d\s:e.,]|$)|[LTY](?=\d)|[OBAFGKM](?!-rich))"
    r"(?:(?<=[OB])[NC](?=\d))?"
    r"\(?(?P<subtype>[\d.]*)\)?(?:[-/][OBAFGKM]?[\d.]+)?"
    r"[\s:()\-_+]*"
    r"(?P<luminosity>0-Ia|Ia\+|Ia0|Iab|Ia|Ib|III|II|IV|VII|VI|V|I|0)?"
)
_BARIUM = re.compile(r"Ba(?![a-z])")
# Emission lines after the class: an "e" alone or with n, p, q, k or v (B2Ve,
# B(0/3)ne, B1IV-Ve, B[e]). He, Fe, pec and weak are other marks.
_EMISSION = re.compile(r"(?<![A-Za-z])[knpqv]*e[kpqv]*(?![a-z])")
_ROMAN = re.compile(r"[IV]+[ab]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def parse_spectral_type(text: str) -> tuple[str | None, str | None, np.uint64]:
    """The letter and stage of an MK spectral type, and its other families.

    A composite type gives its first star. A letter is a key of LETTER_CODE,
    a stage a key of STAGE_CODE.
    """
    return _parse(text)[:3]


def _parse(text: str) -> tuple[str | None, str | None, np.uint64, float | None]:
    """`parse_spectral_type` and the subtype of the letter."""
    for word, word_families in rules.SPECTRAL_TYPE_WORDS.items():
        if text.startswith(word):
            return None, None, mask_of(word_families), None
    am = _AM.match(text)
    if am is not None:
        text = am["hydrogen"] + text[am.end() :]
    found = _CLASS.match(text)
    if found is None:
        return None, None, NONE, None
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
    number = _NUMBER.match(found["subtype"])
    subtype = None if number is None else float(number[0])
    return letter, stage, BIT["barium-star"] if barium else NONE, subtype


def _first_star(text: str) -> str:
    second = rules.COMPOSITE_SPECTRAL_TYPE.search(text)
    return text if second is None else text[: second.start()]


def _emission_lines(text: str) -> tuple[int]:
    """1 when the first star of an MK spectral type has emission lines, else 0."""
    first = _first_star(text)
    found = _CLASS.match(first)
    if found is None:
        return (0,)
    tail = _ROMAN.sub(" ", first[found.end() :])
    return (int(_EMISSION.search(tail) is not None),)


# The codes of `_spectral_codes` for a null type.
NO_CODES = (0, 0, 0, 0, 0)


def _spectral_codes(text: str) -> tuple[int, int, np.uint64, int, int]:
    """The letter and stage codes, the other families, the subtype in tenths
    and 1 when the first star has a WN class too (O2If*/WN5)."""
    letter, stage, extra, subtype = _parse(text)
    return (
        0 if letter is None else LETTER_CODE[letter],
        0 if stage is None else STAGE_CODE[stage],
        extra,
        0 if subtype is None else round(subtype * 10),
        int("WN" in _first_star(text)),
    )


def of_spectral_type(text: str) -> list[str]:
    """The published families of a star of this MK spectral type, in bit order."""
    letter, stage, extra, *_ = _spectral_codes(text)
    mask = closure(np.array([extra | TABLE[letter, stage]], np.uint64))[0]
    return [family for family in rules.FAMILIES if mask & BIT[family]]


def most_specific(
    families: Iterable[str],
    order: Sequence[str],
    parents: Mapping[str, Sequence[str]],
) -> list[str]:
    """The families that contain none of the others, in `order`. `parents`
    gives the parent families of each family of the tree."""
    given = set(families)
    contained = {parent for family in given for parent in parents.get(family, ())}
    return [f for f in order if f in given and f not in contained]


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


# A GCVS subtype in brackets: "UVN(YY)", "RR(B)".
_GCVS_SUBTYPE = re.compile(r"(?P<type>[^(]+)\([^)]*\)")


def _gcvs_mask(vartype: str) -> tuple[np.uint64]:
    types = [
        found["type"] if (found := _GCVS_SUBTYPE.fullmatch(part)) else part
        for part in vartype.split("+")
    ]
    return (mask_of(f for part in types for f in rules.GCVS_FAMILIES.get(part, ())),)


def _gcvs(rows: pa.Table) -> np.ndarray:
    """The families of the GCVS type of each row."""
    return _by_value(rows["vartype_gcvs"], _gcvs_mask, (0,))[:, 0]


# The reference of an ATNF type code: "AXP[esy+20]".
_ATNF_REFERENCE = re.compile(r"\[[^\]]*\]")


def _atnf_mask(text: str) -> tuple[np.uint64]:
    codes = _ATNF_REFERENCE.sub("", text).split(",")
    return (
        mask_of(f for code in codes for f in rules.ATNF_FAMILIES.get(code.strip(), ())),
    )


def _atnf(rows: pa.Table) -> np.ndarray:
    """The families of the ATNF type of each row."""
    return _by_value(rows["type_atnf"], _atnf_mask, (0,))[:, 0]


def _numbers(rows: pa.Table, name: str) -> np.ndarray:
    return rows[name].cast(pa.float64()).fill_null(np.nan).to_numpy()


def _flame_stage(rows: pa.Table) -> np.ndarray:
    """The FLAME stage code of each row, from the first run whose fit holds."""
    bounds = np.array([bound for bound, _ in rules.FLAME_STAGES])
    codes = np.array([STAGE_CODE[stage] for _, stage in rules.FLAME_STAGES])
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
        at = np.minimum(np.searchsorted(bounds, stage, side="right"), bounds.size - 1)
        out = np.where(holds, codes[at], out)
    return out


def _isin(column: pa.ChunkedArray, values: frozenset[str]) -> np.ndarray:
    found = pc.is_in(column, pa.array(sorted(values), pa.string()))
    return found.fill_null(False).to_numpy(zero_copy_only=False)


def _red(rows: pa.Table) -> np.ndarray:
    """The rows that Gaia finds red and not a white dwarf."""
    colour = _numbers(rows, "phot_bp_mean_mag") - _numbers(rows, "phot_rp_mean_mag")
    found = _numbers(rows, "classprob_dsc_combmod_whitedwarf")
    red = colour > rules.SYSTEM_WHITE_DWARF_MAX_BP_RP
    return red & ~(found > rules.MIN_WHITE_DWARF_PROBABILITY)


def _system_types(rows: pa.Table) -> dict[str, pa.ChunkedArray]:
    """The columns of the types of its SIMBAD system, null in each row that
    they do not hold for. A white-dwarf type does not hold for a `_red` row;
    the system's other column still can."""
    sp_type, otype = rows["simbad_system_sp_type"], rows["simbad_system_otype"]
    parsed = _by_value(sp_type, _spectral_codes, NO_CODES)
    letter, stage = parsed[:, 0].astype(np.int64), parsed[:, 1].astype(np.int64)
    red = _red(rows)
    none = pa.scalar(None, pa.string())

    def holding(column: pa.ChunkedArray, given: np.ndarray) -> pa.ChunkedArray:
        white_dwarf = (closure(given) & BIT["white-dwarf"]) != 0
        return pc.if_else(pa.array(~(white_dwarf & red)), column, none)

    return {
        "simbad_system_sp_type": holding(sp_type, parsed[:, 2] | TABLE[letter, stage]),
        "simbad_system_otype": holding(otype, _masks(otype, rules.OTYPE_FAMILIES)),
    }


def spectral_type(rows: pa.Table) -> pa.ChunkedArray:
    """The MK spectral type of each row: the first one in SPECTRAL_TYPES that
    holds. `rows` has SPECTRAL_COLUMNS."""
    return _first_type(rows, _system_types(rows))


def _first_type(rows: pa.Table, system: dict[str, pa.ChunkedArray]) -> pa.ChunkedArray:
    return pc.coalesce(*(system.get(name, rows[name]) for name in SPECTRAL_TYPES))


def _esphs_stage(
    rows: pa.Table, letter: np.ndarray, excluded: np.ndarray
) -> np.ndarray:
    """The ESP-HS stage code of each row with the `letter` code: main sequence
    or giant by log g. `excluded` marks an emission-line star by its MK type
    or object type."""
    teff, logg = _numbers(rows, "teff_esphs"), _numbers(rows, "logg_esphs")
    low, high = ESPHS_TEFF[letter].T
    excluded = excluded | _isin(rows["classlabel_espels"], rules.ESPHS_EXCLUDED_ELS)
    holds = (teff >= low) & (teff <= high) & (logg <= rules.ESPHS_MAX_LOGG)
    holds &= ~excluded
    main = logg >= rules.ESPHS_MIN_MAIN_SEQUENCE_LOGG
    stage = np.where(main, STAGE_CODE["main-sequence"], STAGE_CODE["giant"])
    return np.where(holds, stage, 0)


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


# A bit for each object type of a conflict rule.
CONFLICT_BIT = {
    code: np.uint64(1 << n)
    for n, code in enumerate(
        sorted(
            {code for code, _, _ in (*rules.OTYPE_OVER_MK, *rules.MK_OVER_OTYPE)}
            | {rules.WN_STAR_OTYPE}
        )
    )
}
_UNCOVERED = np.iinfo(np.int64).max


def _compiled(rule: rules.ConflictRule) -> tuple[np.uint64, np.ndarray, np.ndarray]:
    """The object type bit of a rule, the lowest subtype in tenths that it
    covers for each letter code, and the stage codes that it covers."""
    code, letters, stages = rule
    floor = np.full(len(LETTERS) + 1, _UNCOVERED if letters else 0, np.int64)
    for entry in letters or ():
        letter = entry.rstrip("0123456789.")
        floor[LETTER_CODE[letter]] = round(float(entry[len(letter) :] or 0) * 10)
    covered = np.zeros(len(STAGES) + 1, bool)
    covered[[STAGE_CODE[stage] for stage in stages]] = True
    return CONFLICT_BIT[code], floor, covered


OTYPE_OVER_MK = tuple(_compiled(rule) for rule in rules.OTYPE_OVER_MK)
MK_OVER_OTYPE = tuple(
    (*_compiled(rule), ~(STAGE_MASK & mask_of(rules.OTYPE_FAMILIES[rule[0]])))
    for rule in rules.MK_OVER_OTYPE
)
WN_LETTERS = [LETTER_CODE[letter] for letter in sorted(rules.WN_STAR_LETTERS)]


def _settle(
    otypes: np.ndarray, parsed: np.ndarray, families: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The MK letter and stage codes and the object type families of each
    row, without the losing side of a conflict between them.

    `otypes` holds the CONFLICT_BIT of each row, `parsed` its
    `_spectral_codes`.
    """
    letter, stage = parsed[:, 0].astype(np.int64), parsed[:, 1].astype(np.int64)
    subtype = parsed[:, 3].astype(np.int64)

    def covers(bit: np.uint64, floor: np.ndarray, at: np.ndarray) -> np.ndarray:
        return ((otypes & bit) != 0) & (subtype >= floor[letter]) & at[stage]

    lost = np.zeros(len(letter), bool)
    for bit, floor, at in OTYPE_OVER_MK:
        lost |= covers(bit, floor, at)
    for bit, floor, at, kept in MK_OVER_OTYPE:
        families = np.where(covers(bit, floor, at), families & kept, families)
    wn_star = (parsed[:, 4] != 0) & np.isin(letter, WN_LETTERS)
    wolf_rayet = wn_star & ((otypes & CONFLICT_BIT[rules.WN_STAR_OTYPE]) != 0)
    return (
        np.where(wolf_rayet, 0, letter),
        np.where(lost | wolf_rayet, 0, stage),
        families,
    )


def _otype_codes(value: str) -> tuple[np.uint64, np.uint64, np.uint64, int]:
    """The OTYPE_FAMILIES mask, the CONFLICT_BIT and the
    CANDIDATE_OTYPE_FAMILIES mask of an object type, and 1 when it stops the
    ESP-HS stage."""
    return (
        mask_of(rules.OTYPE_FAMILIES.get(value, ())),
        CONFLICT_BIT.get(value, NONE),
        mask_of(rules.CANDIDATE_OTYPE_FAMILIES.get(value, ())),
        int(value in rules.ESPHS_EXCLUDED_OTYPES),
    )


def _class_codes(value: str) -> tuple[np.uint64, np.uint64]:
    """The CLASS_FAMILIES mask of a Metadata class and the CONFLICT_BIT of the
    object type that gives it."""
    otype = rules.CLASS_OTYPES.get(value, "")
    return mask_of(rules.CLASS_FAMILIES.get(value, ())), CONFLICT_BIT.get(otype, NONE)


def _gaia_allows(rows: pa.Table, candidate: np.ndarray) -> np.ndarray:
    """The families of the `candidate` masks that Gaia does not rule out. A
    star brighter than BROWN_DWARF_MIN_ABSOLUTE_G is no brown dwarf. M_G comes
    from a 5σ parallax, else from the distance group, else from the exoplanet
    catalogue. A `_red` star is no white dwarf."""
    parallax, error = _numbers(rows, "parallax"), _numbers(rows, "parallax_error")
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = np.where(
            parallax / error > MIN_PARALLAX_SNR, 1000 / parallax, np.nan
        )
    for name in ("distance", "host_distance"):
        distance = np.where(np.isnan(distance), _numbers(rows, name), distance)
    absolute = _numbers(rows, "phot_g_mean_mag") - 5 * np.log10(distance / 10)
    bright = absolute < rules.BROWN_DWARF_MIN_ABSOLUTE_G
    candidate = np.where(bright, candidate & ~BIT["brown-dwarf"], candidate)
    return np.where(_red(rows), candidate & ~BIT["white-dwarf"], candidate)


def masks(
    rows: pa.Table, classes: pa.Array | pa.ChunkedArray
) -> tuple[np.ndarray, np.ndarray]:
    """The published and the estimated family masks of the Point source `rows`.

    `classes` is the Metadata class of each row.
    """
    n = rows.num_rows
    system = _system_types(rows)
    otype = {
        name: _by_value(system.get(name, rows[name]), _otype_codes, (0, 0, 0, 0))
        for name in dict.fromkeys((*OTYPES, *CANDIDATE_OTYPES))
    }
    parsed = _by_value(_first_type(rows, system), _spectral_codes, NO_CODES)
    given, conflicts = _by_value(classes, _class_codes, (0, 0)).T
    excluded = np.zeros(n, bool)
    for name in OTYPES:
        given |= otype[name][:, 0]
        conflicts |= otype[name][:, 1]
        excluded |= otype[name][:, 3] != 0
    candidate = np.zeros(n, np.uint64)
    for name in CANDIDATE_OTYPES:
        candidate |= otype[name][:, 2]
    candidate = _gaia_allows(rows, candidate)
    mk_letter, mk_stage, given = _settle(conflicts, parsed, given)
    published = (
        parsed[:, 2] | TABLE[mk_letter, mk_stage] | given | _gcvs(rows) | _atnf(rows)
    )
    # A stage that an object type gives joins the MK letter as an MK stage
    # does. A family that states a letter, such as red-giant, keeps its stage
    # to that letter.
    stage_given = _published_stage(closure(published & ~LETTER_MASK))
    published = closure(published)
    stage_known = np.where(mk_stage > 0, mk_stage, stage_given)
    published = closure(published | TABLE[mk_letter, stage_known])

    fixed = states_of(published)
    fixed |= np.where(mk_letter > 0, rules.LETTER, 0)
    fixed |= np.where(stage_known > 0, rules.STAGE, 0)
    els = _masks(rows["classlabel_espels"], rules.ELS_FAMILIES)
    white_dwarf = (
        _numbers(rows, "classprob_dsc_combmod_whitedwarf")
        > rules.MIN_WHITE_DWARF_PROBABILITY
    )
    spicy = _masks(rows["class_spicy"], rules.SPICY_FAMILIES)
    labels = np.zeros(n, np.uint64)
    # Of two labels that state the same, the first in this order counts.
    for label in (
        candidate,
        els,
        np.where(white_dwarf, BIT["white-dwarf"], NONE),
        spicy,
    ):
        kept = np.where(states_of(label) & fixed, NONE, label)
        labels |= kept
        fixed |= states_of(kept)

    # A tag that fails its quality check gives no letter, so FLAME gives the
    # stage. For such O and B tags, FLAME is right as often as ESP-HS.
    letter = np.where(fixed & rules.LETTER, mk_letter, _esp_letter(rows))
    for name in SPECTRAL_TYPES:
        emission = _by_value(system.get(name, rows[name]), _emission_lines, (0,))
        excluded |= emission[:, 0] != 0
    estimate = np.where(
        ESPHS_LETTER[letter], _esphs_stage(rows, letter, excluded), _flame_stage(rows)
    )
    stage = np.where(fixed & rules.STAGE, stage_known, estimate)
    every = closure(TABLE[letter, stage] | labels | published)
    return published, every & ~published
