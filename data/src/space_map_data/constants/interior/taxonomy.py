"""What a taxonomic class implies about what an asteroid is made of.

A spectrum names a meteorite analogue; the analogue's measured bulk chemistry
gives the composition. Both steps are inference, so every asteroid served from
this table ships flagged as an estimate from its spectrum — the panel says
"estimated from its S-type spectrum", never "is".

Splits are mass fractions rounded to whole percent. Rounding is the point: the
class-to-analogue step is worth about that much, and a table of four-digit
fractions would claim a precision the mapping does not have. Metal and
sulphide come from the modal abundances in Krot et al. 2014 recomputed by
mass, cross-checked against the bulk analyses in Jarosewich 1990; volatile
contents are the carbonaceous-chondrite water and carbon of Wasson &
Kallemeyn 1988.

Classes whose analogue is genuinely disputed are absent rather than guessed —
X is the clearest case, where the same spectrum fits an iron, an enstatite
chondrite and a hydrated primitive body, and only albedo separates them.
"""

from space_map_data.constants.interior.schema import (
    ClassComposition,
    Component,
    METAL,
    ORGANIC,
    SILICATE,
    SULFIDE,
    WATER,
)

# Keyed by taxonomic class exactly as SsODNet reports it. Compound classes
# (Sq, Cgh, ...) resolve through their complex when absent here, so this table
# only needs the roots plus any compound whose analogue genuinely differs.
TAXONOMY_COMPOSITION: dict[str, ClassComposition] = {
    # Ordinary chondrites, the most abundant meteorite type on Earth and the
    # best-established asteroid-meteorite link there is. Metal content spans
    # H→LL (18%→3%); S-types match the L/LL end, so the middle is the honest
    # single number.
    "S": ClassComposition(
        analogue="ordinary_chondrite",
        composition=(
            Component(SILICATE, 0.85, "krot_2014"),
            Component(METAL, 0.09, "jarosewich_1990"),
            Component(SULFIDE, 0.06, "jarosewich_1990"),
        ),
        source="demeo_2009",
    ),
    # Unweathered ordinary-chondrite surfaces — same rock, fresher face.
    "Q": ClassComposition(
        analogue="ordinary_chondrite",
        composition=(
            Component(SILICATE, 0.85, "krot_2014"),
            Component(METAL, 0.09, "jarosewich_1990"),
            Component(SULFIDE, 0.06, "jarosewich_1990"),
        ),
        source="demeo_2009",
    ),
    # Basaltic achondrites — the HED suite, chipped off Vesta. Differentiated,
    # so the metal went to a core and the crust is nearly pure silicate.
    "V": ClassComposition(
        analogue="hed_achondrite",
        composition=(
            Component(SILICATE, 0.98, "krot_2014"),
            Component(METAL, 0.01, "jarosewich_1990"),
            Component(SULFIDE, 0.01, "jarosewich_1990"),
        ),
        source="demeo_2009",
    ),
    # Carbonaceous chondrites. The water is real but bound in phyllosilicates
    # rather than sitting around as ice — see the note key.
    "C": ClassComposition(
        analogue="carbonaceous_chondrite",
        composition=(
            Component(SILICATE, 0.78, "krot_2014"),
            Component(WATER, 0.13, "wasson_1988"),
            Component(SULFIDE, 0.06, "krot_2014"),
            Component(ORGANIC, 0.03, "wasson_1988"),
        ),
        source="demeo_2009",
        note="hydrated_rock",
    ),
    # The 0.7 µm and 3 µm bands make the hydration explicit for Ch/Cgh, which
    # is why they get the CI-like end of the water range rather than the CM one.
    "Ch": ClassComposition(
        analogue="hydrated_carbonaceous_chondrite",
        composition=(
            Component(SILICATE, 0.70, "krot_2014"),
            Component(WATER, 0.20, "wasson_1988"),
            Component(SULFIDE, 0.06, "krot_2014"),
            Component(ORGANIC, 0.04, "wasson_1988"),
        ),
        source="demeo_2009",
        note="hydrated_rock",
    ),
    "B": ClassComposition(
        analogue="carbonaceous_chondrite",
        composition=(
            Component(SILICATE, 0.80, "krot_2014"),
            Component(WATER, 0.11, "wasson_1988"),
            Component(SULFIDE, 0.06, "krot_2014"),
            Component(ORGANIC, 0.03, "wasson_1988"),
        ),
        source="demeo_2009",
        note="hydrated_rock",
    ),
    # CV/CO chondrites — anhydrous carbonaceous, refractory-inclusion rich.
    "K": ClassComposition(
        analogue="cv_co_chondrite",
        composition=(
            Component(SILICATE, 0.85, "krot_2014"),
            Component(METAL, 0.05, "krot_2014"),
            Component(SULFIDE, 0.05, "krot_2014"),
            Component(ORGANIC, 0.05, "wasson_1988"),
        ),
        source="demeo_2009",
    ),
    # Olivine-dominated: pallasite mantles and brachinites, an interior laid
    # bare rather than a surface.
    "A": ClassComposition(
        analogue="olivine_achondrite",
        composition=(
            Component(SILICATE, 0.95, "krot_2014"),
            Component(METAL, 0.04, "krot_2014"),
            Component(SULFIDE, 0.01, "krot_2014"),
        ),
        source="demeo_2009",
    ),
}

# Where a compound class has no entry of its own, its complex stands in — an
# "Sq" is an S. Kept explicit rather than string-prefix matching, because
# prefixes lie: a "Cgh" is a C, but an "L" is not an "LS".
COMPLEX_FALLBACK = frozenset({"S", "C", "V", "B", "K", "A", "Q"})
