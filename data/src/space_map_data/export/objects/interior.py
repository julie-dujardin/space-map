"""Per-object interior stat block, denormalized onto a body's global bundle.

Three sources feed one shape: a mission-constrained body has a layer model in
`constants/interior/bodies.py`; a spectrum-only asteroid gets its meteorite
analogue's bulk chemistry from `constants/interior/taxonomy.py`, flagged as an
estimate; a hand-authored overlay body brings its own layer model as data
(`interior_from_mapping`, for objects with no DB row at all).

Two shapes ship: a whole-body composition roll-up (all the estimate route can
offer) and, for the ~30 bodies with a layer model, the layer stack the
Structure tab draws. The roll-up is a mass balance over layers, not an
elemental one — water bound in a phyllosilicate counts as water, not as oxygen
shared among the rocks.

Boundary temperatures ride on the layer stack, on boundaries rather than
shells, wherever one has been published.
"""

import logging
import math

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import (
    INTERIOR_SOURCES,
    InteriorReference,
)
from space_map_data.constants.interior.schema import (
    DETAIL_UNITS,
    LAYER_ROLES,
    MATERIALS,
    NOTES,
    PHASES,
    ROCKS,
    STATES,
    STRUCTURES,
    BodyInterior,
    Component,
    Detail,
    Layer,
)
from space_map_data.constants.interior.taxonomy import (
    MAHLKE_SCHEME,
    TAXONOMY_COMPOSITION,
    resolve_class,
)
from space_map_data.export.objects.sources import source_row
from space_map_data.models.object.ssodnet import SsODNet

logger = logging.getLogger(__name__)

# Below this a share is a rounding artefact of the layer arithmetic rather
# than a component anyone measured, and it draws as an invisible sliver with
# a legend entry. Tethys's 0.1% of rock is the case in point.
_MIN_SHARE = 0.005


def load_taxonomy(
    session,
) -> dict[str, tuple[str | None, str | None, str | None, float | None]]:
    """Taxonomic class per object, for the estimate route.

    Read once into a plain dict rather than through `Object.ssodnet`: the
    bundle build runs in threads, and a relationship access there would be a
    lazy load per asteroid.
    """
    rows = (
        session.query(
            SsODNet.object_id,
            SsODNet.taxonomy_class,
            SsODNet.taxonomy_complex,
            SsODNet.taxonomy_scheme,
            SsODNet.albedo,
        )
        .filter(SsODNet.taxonomy_class.isnot(None))
        .all()
    )
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


def interior_block(object_id: str, taxonomy: dict) -> dict | None:
    """Build the `interior` block for `object_id`, or None if nothing answers
    for it.

    A per-body layer model always wins over the spectral estimate — Vesta has
    both, and Dawn's gravity beats "V-types look like HEDs".
    """
    facts = INTERIOR_FACTS.get(object_id)
    if facts is not None:
        return _from_layers(object_id, facts)
    entry = taxonomy.get(object_id)
    if entry is not None:
        return _from_taxonomy(object_id, *entry)
    return None


def interior_from_mapping(object_id: str, mapping: dict) -> dict | None:
    """Build the block for a body whose layer model arrives as data, not as a
    constant — the hand-authored overlay in the download dir.

    Takes the same roll-up/validation route as a constants-backed body, but
    carries its own `sources` table since it has no entry in `references.py`.
    A malformed mapping costs only that body's panel: the overlay is
    hand-edited and outside the repo, so a typo must not take the export down.
    """
    try:
        refs = INTERIOR_SOURCES | _references(mapping.get("sources") or {})
        layers = tuple(_parse_layer(layer) for layer in mapping.get("layers") or ())
        body = _named(
            BodyInterior, {k: v for k, v in mapping.items() if k not in _BODY_OWN}
        )
        return _from_layers(object_id, BodyInterior(layers=layers, **body), refs)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning(
            "%s: unusable hand-authored interior (%s); shipping without one",
            object_id,
            exc,
        )
        return None


# Handled before the generic pass: one is parsed into its own tuples, the other
# is a table `BodyInterior` has no field for.
_BODY_OWN = frozenset({"layers", "sources"})


def _references(table: dict) -> dict[str, InteriorReference]:
    """The mapping's own citations. No `contribution`: that's the /credits
    page's column, which reads the constants rather than this."""
    return {
        key: InteriorReference(
            ref["title"],
            ref["url"],
            ref.get("contribution", ""),
            ref.get("note", ""),
        )
        for key, ref in table.items()
    }


def _parse_layer(mapping: dict) -> Layer:
    composition = tuple(
        Component(**_named(Component, c)) for c in mapping.get("composition") or ()
    )
    detail = mapping.get("detail")
    return Layer(
        composition=composition,
        detail=_parse_detail(detail) if detail else None,
        **_named(Layer, {k: v for k, v in mapping.items() if k not in _LAYER_OWN}),
    )


_LAYER_OWN = frozenset({"composition", "detail"})


def _parse_detail(mapping: dict) -> Detail:
    """A `[species, fraction]` pair per entry, drawn in order — JSON's list
    stands in for the constants' tuple."""
    fields = _named(Detail, mapping)
    return Detail(**fields | {"entries": tuple(tuple(e) for e in fields["entries"])})


def _named(cls, mapping: dict) -> dict:
    """Keyword arguments for a schema NamedTuple, from its JSON spelling.

    Read off `_fields` rather than listed here, so a new schema field reaches
    this route automatically. An unknown key is a typo and stops the parse
    rather than being dropped silently.
    """
    unknown = set(mapping) - set(cls._fields)
    if unknown:
        raise ValueError(f"unknown {cls.__name__} field(s) {sorted(unknown)}")
    return {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in mapping.items()
    }


def _from_layers(
    object_id: str,
    facts: BodyInterior,
    refs: dict[str, InteriorReference] = INTERIOR_SOURCES,
) -> dict:
    """Roll a per-body layer model up into one composition."""
    _validate(object_id, facts, refs)

    block: dict = {"structure": facts.structure}
    if facts.note is not None:
        block["note"] = facts.note
    if facts.centre_temperature_k is not None:
        block["centre_temperature_k"] = _sig(facts.centre_temperature_k)
    if facts.centre_temperature_range_k is not None:
        block["centre_temperature_range_k"] = [
            _sig(v) for v in facts.centre_temperature_range_k
        ]
    composition: list[dict] = []

    # A body whose source gives geometry but no masses — the Sun — has nothing
    # to roll up. It still ships: the structure and the works behind it are
    # worth a panel even with no bar.
    if all(layer.mass_fraction is None for layer in facts.layers):
        logger.info(
            "%s: layer masses are unknown; shipping structure without a "
            "composition bar",
            object_id,
        )
    else:
        shares: dict[str, float] = {}
        for layer in facts.layers:
            mass = layer.mass_fraction
            if mass is None:
                # The constants forbid a half-massed body, so this is only
                # reachable if that invariant breaks — say so rather than
                # silently under-counting the bar.
                logger.warning(
                    "%s: %s layer has no mass among layers that do; the "
                    "composition below is missing it",
                    object_id,
                    layer.role,
                )
                continue
            for component in layer.composition:
                shares[component.material] = shares.get(component.material, 0.0) + (
                    mass * component.fraction
                )
        composition = _shares(object_id, shares)
        block["composition"] = composition

    layers = [_layer(object_id, layer) for layer in facts.layers]
    block["layers"] = layers
    block["sources"] = _sources(_layer_source_keys(facts, composition, layers), refs)
    return block


# `sea` is deliberately excluded: Titan's methane seas and water ocean are
# different substances, and summing them would be a category error. The
# Oceans page names them in prose instead.
OCEAN_ROLE = "ocean"


def ocean_block(object_id: str) -> dict | None:
    """The body's ocean as one row of the Oceans collection chart, or None.

    Volume is computed from the layer's own radii rather than published, since
    no single work quotes all nine bodies. Done here so the chart and the
    body's own cross-section read the same radii and the same base-radius rule.
    """
    facts = INTERIOR_FACTS.get(object_id)
    if facts is None:
        return None
    layers = list(facts.layers)
    for i, layer in enumerate(layers):
        if layer.role != OCEAN_ROLE or layer.outer_radius_km is None:
            continue
        # Same rule the cross-section draws by: a shell ends where the next
        # layer begins, a patch carries its own floor.
        base = layer.base_radius_km
        if base is None:
            base = layers[i + 1].outer_radius_km if i + 1 < len(layers) else 0.0
        if base is None or base >= layer.outer_radius_km:
            logger.warning(
                "%s: ocean has no floor under %.1f km; no row on the collection "
                "chart for it",
                object_id,
                layer.outer_radius_km,
            )
            return None
        share = layer.area_fraction if layer.area_fraction is not None else 1.0
        volume = (4 / 3) * math.pi * (layer.outer_radius_km**3 - base**3) * share
        out: dict = {
            "volume_km3": _sig(volume),
            "thickness_km": _sig(layer.outer_radius_km - base),
            # Under something, i.e. not Earth's. The whole reason the page
            # exists is that eight of the nine are.
            "subsurface": i > 0,
        }
        if layer.mass_fraction is not None:
            out["mass_fraction"] = _sig(layer.mass_fraction)
        return out
    return None


# What the frontend's cutaway needs to draw a shell and colour it. `composition`
# is truncated to its first entry since `dominant()` (layer-appearance.ts)
# colours by the dominant material alone.
_CUTAWAY_KEYS = (
    "role",
    "outer_radius_km",
    "base_radius_km",
    "area_fraction",
    "state",
    "phase",
    "diffuse",
)


def cutaway_layers(object_id: str) -> list[dict] | None:
    """The layer stack, trimmed to what a thumbnail-sized cutaway draws:
    geometry, phase and one material per layer. A 60 px cutaway has no room
    for labels; a reader who wants them is one click from the Structure tab.
    """
    facts = INTERIOR_FACTS.get(object_id)
    if facts is None or not facts.layers:
        return None
    out = []
    for layer in facts.layers:
        # Falsy, not just None: `diffuse` is a bool, and the object-side layer
        # omits it when False rather than shipping it on all 89 layers.
        entry = {k: v for k in _CUTAWAY_KEYS if (v := getattr(layer, k))}
        if layer.composition:
            first = max(layer.composition, key=lambda c: c.fraction)
            entry["composition"] = [
                {"material": first.material, "share": _sig(first.fraction)}
            ]
        out.append(entry)
    return out


def _layer(object_id: str, layer: Layer) -> dict:
    """One layer of the cross-section.

    Radii are the source's own R, not the body's exported mean radius — the
    two can disagree by a few km. The frontend normalizes to the outermost
    layer, not the body, so the stack closes at the surface.
    """
    out: dict = {"role": layer.role}
    if layer.outer_radius_km is not None:
        out["outer_radius_km"] = layer.outer_radius_km
    if layer.base_radius_km is not None:
        out["base_radius_km"] = layer.base_radius_km
    if layer.area_fraction is not None:
        out["area_fraction"] = layer.area_fraction
    if layer.mass_fraction is not None:
        out["mass_fraction"] = _sig(layer.mass_fraction)
    if layer.mass_fraction_range is not None:
        out["mass_fraction_range"] = [_sig(v) for v in layer.mass_fraction_range]
    if layer.state is not None:
        out["state"] = layer.state
    if layer.phase is not None:
        out["phase"] = layer.phase
    if layer.rock is not None:
        out["rock"] = layer.rock
    if layer.note is not None:
        out["note"] = layer.note
    if layer.derived:
        out["derived"] = True
    if layer.diffuse:
        out["diffuse"] = True
    if layer.outer_temperature_k is not None:
        out["outer_temperature_k"] = _sig(layer.outer_temperature_k)
    if layer.outer_temperature_range_k is not None:
        out["outer_temperature_range_k"] = [
            _sig(v) for v in layer.outer_temperature_range_k
        ]

    composition = _shares(
        object_id,
        {c.material: c.fraction for c in layer.composition},
        of=f"its {layer.role}",
    )
    # The published width rides alongside the value it brackets, so a modelled
    # split never draws as sharply as a measured one.
    ranges = {
        c.material: c.fraction_range
        for c in layer.composition
        if c.fraction_range is not None
    }
    for entry in composition:
        width = ranges.get(entry["material"])
        if width is not None:
            entry["share_range"] = [_sig(v) for v in width]
    out["composition"] = composition

    if layer.detail is not None:
        out["detail"] = {
            "unit": layer.detail.unit,
            "entries": [
                {"species": species, "fraction": _sig(fraction)}
                for species, fraction in layer.detail.entries
            ],
        }
    return out


def _layer_source_keys(
    facts: BodyInterior, composition: list[dict], layers: list[dict]
) -> list[str]:
    """The works behind what the panel actually shows.

    Structure, then every layer's geometry, then the chemistry of materials
    that survived the sliver cut in *any* layer — a material can miss the
    whole-body bar yet still fill its own layer (e.g. a small sulphur core).
    Temperature sources ride along per boundary, usually a different paper.
    """
    keys: list[str] = []
    if facts.structure_source is not None:
        keys.append(facts.structure_source)
    keys.extend(facts.centre_temperature_sources)
    shown = {c["material"] for c in composition}
    for layer, drawn in zip(facts.layers, layers):
        keys.append(layer.source)
        if layer.density_source is not None:
            keys.append(layer.density_source)
        if layer.state_source is not None:
            keys.append(layer.state_source)
        if layer.phase_source is not None:
            keys.append(layer.phase_source)
        if layer.rock_source is not None:
            keys.append(layer.rock_source)
        keys.extend(layer.temperature_sources)
        in_layer = shown | {c["material"] for c in drawn["composition"]}
        keys.extend(c.source for c in layer.composition if c.material in in_layer)
        if layer.detail is not None:
            keys.append(layer.detail.source)
    return keys


def _from_taxonomy(
    object_id: str,
    taxonomy_class: str | None,
    complex_: str | None,
    scheme: str | None,
    albedo: float | None,
) -> dict | None:
    """Turn a reported spectral class into its analogue's bulk chemistry."""
    if taxonomy_class is None:
        return None
    resolved = resolve_class(taxonomy_class, complex_, albedo)
    if resolved is None:
        return None
    entry = TAXONOMY_COMPOSITION[resolved.key]
    composition = _shares(
        object_id, {c.material: c.fraction for c in entry.composition}
    )
    shown = {c["material"] for c in composition}

    block: dict = {
        # Never "differentiated": a spectrum is a statement about the surface,
        # and the analogue is a rock, not a structure.
        "estimated": True,
        "analogue": entry.analogue,
        "taxonomy_class": taxonomy_class,
        "composition": composition,
    }
    # A class letter means different things under Tholen, Bus and Bus-DeMeo,
    # so the scheme travels with it to the panel.
    if scheme is not None:
        block["taxonomy_scheme"] = scheme
    block["taxonomy_sources"] = _class_credits(scheme, resolved.from_albedo_split)
    if entry.note is not None:
        block["note"] = entry.note
    block["sources"] = _sources(
        [entry.source, *(c.source for c in entry.composition if c.material in shown)],
        INTERIOR_SOURCES,
    )
    return block


def _class_credits(scheme: str | None, from_albedo_split: bool) -> list[str]:
    """Who to credit for the spectral class, as ids rather than citations.

    Bare ids since ~171,000 asteroids take this route — full citations here
    would be megabytes for two names the frontend can hold itself.
    """
    credits = ["ssodnet"]
    # Mahlke both defines the scheme many of these classes are reported under
    # and is the albedo cut that splits an X into E or M. Either way the
    # letter we serve is theirs.
    if scheme == MAHLKE_SCHEME or from_albedo_split:
        credits.append("mahlke")
    return credits


def _shares(
    object_id: str, shares: dict[str, float], of: str = "the body"
) -> list[dict]:
    """Largest first, slivers dropped, renormalized over what is left."""
    kept = {m: v for m, v in shares.items() if v >= _MIN_SHARE}
    dropped = sorted(set(shares) - set(kept))
    if dropped:
        logger.info(
            "%s: dropping %s below %.1f%% of %s",
            object_id,
            ", ".join(dropped),
            _MIN_SHARE * 100,
            of,
        )
    total = sum(kept.values())
    return [
        {"material": material, "share": _sig(value / total)}
        for material, value in sorted(kept.items(), key=lambda kv: -kv[1])
    ]


def _validate(
    object_id: str, facts: BodyInterior, refs: dict[str, InteriorReference]
) -> None:
    """Enum and citation check — a typo here would ship a body with an
    unlabelled tag or an uncredited number."""
    if facts.structure not in STRUCTURES:
        raise ValueError(f"{object_id}: unknown structure {facts.structure}")
    if facts.note is not None and facts.note not in NOTES:
        raise ValueError(f"{object_id}: unknown note {facts.note}")
    _validate_temperature(
        object_id,
        "centre",
        facts.centre_temperature_k,
        facts.centre_temperature_range_k,
        facts.centre_temperature_sources,
        refs,
    )
    for layer in facts.layers:
        if layer.role not in LAYER_ROLES:
            raise ValueError(f"{object_id}: unknown layer role {layer.role}")
        if layer.note is not None and layer.note not in NOTES:
            raise ValueError(f"{object_id}: unknown note {layer.note}")
        if layer.state is not None and layer.state not in STATES:
            raise ValueError(f"{object_id}: unknown state {layer.state}")
        if layer.phase is not None and layer.phase not in PHASES:
            raise ValueError(f"{object_id}: unknown phase {layer.phase}")
        if layer.phase_source is not None and layer.phase is None:
            raise ValueError(f"{object_id}: {layer.role} cites a phase it has not got")
        if layer.rock is not None and layer.rock not in ROCKS:
            raise ValueError(f"{object_id}: unknown rock {layer.rock}")
        if layer.rock_source is not None and layer.rock is None:
            raise ValueError(f"{object_id}: {layer.role} cites a rock it has not got")
        if layer.detail is not None and layer.detail.unit not in DETAIL_UNITS:
            raise ValueError(f"{object_id}: unknown detail unit {layer.detail.unit}")
        for component in layer.composition:
            if component.material not in MATERIALS:
                raise ValueError(f"{object_id}: unknown material {component.material}")
        _validate_temperature(
            object_id,
            layer.role,
            layer.outer_temperature_k,
            layer.outer_temperature_range_k,
            layer.temperature_sources,
            refs,
        )


def _validate_temperature(
    object_id: str,
    where: str,
    value: float | None,
    width: tuple[float, float] | None,
    sources: tuple[str, ...],
    refs: dict[str, InteriorReference],
) -> None:
    """A boundary temperature has to be cited and has to be a temperature.

    Uncited is the one that matters: a number with no work behind it would draw
    exactly like the rest and credit nobody.
    """
    if value is None and width is None:
        if sources:
            raise ValueError(f"{object_id}: {where} cites a temperature it has not got")
        return
    if not sources:
        raise ValueError(f"{object_id}: {where} temperature has no source")
    for key in sources:
        if key not in refs:
            raise ValueError(f"{object_id}: no such interior source {key}")
    if width is not None and not width[0] < width[1]:
        raise ValueError(f"{object_id}: {where} temperature range is not ascending")
    if value is not None and width is not None and not width[0] <= value <= width[1]:
        raise ValueError(f"{object_id}: {where} temperature sits outside its range")
    for kelvin in (value, *(width or ())):
        if kelvin is not None and kelvin <= 0.0:
            raise ValueError(f"{object_id}: {where} temperature is not above zero")


def _sources(keys: list[str], refs: dict[str, InteriorReference]) -> list[dict]:
    """Dedupe, first occurrence wins — the work behind the structure leads."""
    out = []
    for key in dict.fromkeys(keys):
        ref = refs.get(key)
        if ref is None:
            raise ValueError(f"no such interior source {key}")
        out.append(source_row(ref))
    return out


def _sig(value: float, digits: int = 4) -> float:
    return float(f"{value:.{digits}g}")
