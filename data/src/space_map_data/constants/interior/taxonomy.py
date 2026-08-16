"""What a taxonomic class implies about what an asteroid is made of.

A spectrum names a meteorite analogue; the analogue's measured bulk chemistry
gives the composition. Both steps are inference, so every asteroid served
here ships flagged as an estimate from its spectrum — the panel says
"estimated from its S-type spectrum", never "is".

Splits are mass fractions rounded to whole percent: the class-to-analogue
step is worth about that much, and four-digit fractions would claim a
precision the mapping doesn't have. Metal and sulphide come from Krot et al.
2014's modal abundances recomputed by mass, except the ordinary chondrites,
where Jarosewich 1990's bulk analyses give the H→LL metal span directly;
volatile contents are Wasson & Kallemeyn 1988's carbonaceous-chondrite water
and carbon.

Classes whose analogue is genuinely disputed are absent rather than
guessed — X is the clearest case, where the same spectrum fits an iron, an
enstatite chondrite and a hydrated primitive body, and only albedo separates
them.
"""

from typing import NamedTuple

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
    # so the metal went to a core and the crust is nearly pure silicate. Same
    # trace split as the aubrites below, off the same modal abundances.
    "V": ClassComposition(
        analogue="hed_achondrite",
        composition=(
            Component(SILICATE, 0.98, "krot_2014"),
            Component(METAL, 0.01, "krot_2014"),
            Component(SULFIDE, 0.01, "krot_2014"),
        ),
        source="demeo_2009",
    ),
    # Carbonaceous chondrites. The water is real but bound in phyllosilicates
    # rather than sitting around as ice.
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
    # Metal-rich, but not the iron bar people picture. The best spectral match
    # across the M-type population is Landes — an iron shot through with
    # silicate inclusions, 81% NiFe and 16% silicate — rather than a clean iron
    # like Odessa. Renormalised to 100%.
    "M": ClassComposition(
        analogue="iron_with_silicate",
        composition=(
            Component(METAL, 0.83, "neeley_2014"),
            Component(SILICATE, 0.17, "neeley_2014"),
        ),
        source="neeley_2014",
    ),
    # Aubrites: enstatite achondrites, near-FeO-free pyroxene. The high albedo
    # that separates them from M is the same thing as their iron-poor silicate.
    "E": ClassComposition(
        analogue="aubrite",
        composition=(
            Component(SILICATE, 0.98, "krot_2014"),
            Component(METAL, 0.01, "krot_2014"),
            Component(SULFIDE, 0.01, "krot_2014"),
        ),
        source="demeo_2009",
    ),
    # CAI-rich: L-types carry up to 30% refractory inclusions, but the bulk is
    # still CV/CO chondrite, so the composition is K's.
    "L": ClassComposition(
        analogue="cv_co_chondrite",
        composition=(
            Component(SILICATE, 0.85, "krot_2014"),
            Component(METAL, 0.05, "krot_2014"),
            Component(SULFIDE, 0.05, "krot_2014"),
            Component(ORGANIC, 0.05, "wasson_1988"),
        ),
        source="sunshine_2008",
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

# The X complex is three different rocks sharing one featureless spectrum,
# split only by albedo: dark P, moderate M, bright E. Tholen's original
# split, reinstated by Mahlke et al. 2022 feeding albedo back into the
# classification — applying it here reproduces their method for objects
# classified under schemes that left it out.
#
# P is absent on purpose: its analogue is genuinely unsettled (the Tagish
# Lake link that once carried it is no longer thought representative), so
# dark X-types get no composition rather than a guess.
X_ALBEDO_METAL = 0.10  # below this is P, above is M
X_ALBEDO_ENSTATITE = 0.30  # above this is E

# SsODNet's name for Mahlke's scheme. Where a class is reported under it the
# letter is Mahlke's call rather than Bus-DeMeo's, which is what makes the
# scheme worth crediting per object.
MAHLKE_SCHEME = "Mahlke"


class Resolution(NamedTuple):
    """A reported class reduced to one the table answers for.

    `from_albedo_split` marks the X cases, where the class we serve is our own
    reading of the albedo rather than anything the classifier reported — the
    one place the method itself needs crediting.
    """

    key: str
    from_albedo_split: bool = False


def resolve_class(
    taxonomy_class: str, complex_: str | None, albedo: float | None
) -> Resolution | None:
    """Reduce a reported class to one this table can answer for.

    Returns None when nothing here applies — an unsplittable X, a class whose
    analogue is disputed, or an intermediate like "LS" that is genuinely two
    rocks at once.
    """
    if taxonomy_class in TAXONOMY_COMPOSITION:
        return Resolution(taxonomy_class)

    # X splits on albedo, and only if we have one.
    if taxonomy_class == "X" or complex_ == "X":
        if albedo is None or albedo < X_ALBEDO_METAL:
            return None
        return Resolution("E" if albedo > X_ALBEDO_ENSTATITE else "M", True)

    # A lowercase suffix qualifies the leading class rather than replacing it
    # ("Ds" is a D with s-like features), so the first letter carries the
    # composition. Two capitals mean an object sitting between two classes —
    # "LS", "CX" — and those we decline.
    head = taxonomy_class[:1]
    if (
        len(taxonomy_class) > 1
        and taxonomy_class[1:].islower()
        and head in TAXONOMY_COMPOSITION
    ):
        return Resolution(head)

    if complex_ in COMPLEX_FALLBACK and complex_ in TAXONOMY_COMPOSITION:
        return Resolution(complex_)
    return None
