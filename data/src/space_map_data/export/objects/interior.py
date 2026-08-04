"""Per-object interior stat block, denormalized onto a body's global bundle.

Two sources feed one shape. A body a mission actually constrained has a layer
model in `constants/interior/bodies.py`; an asteroid that only has a spectrum
gets its meteorite analogue's bulk chemistry from `constants/interior/
taxonomy.py`, and ships flagged as an estimate so the panel can say "estimated
from its S-type spectrum" rather than "is".

Two shapes ship. The whole-body roll-up — one share per material, summed over
the layers — is what the Overview's single composition chart draws, and it is
all the estimate route can offer. The layer stack underneath it is what the
Structure tab's cross-section draws, and only the ~30 bodies with a layer model
carry it; the 150,000 asteroids on the estimate route have no layers to spend
bytes on.

The roll-up is a mass balance over layers, not an elemental one: water bound
in a phyllosilicate counts as water, not as oxygen shared out among the rocks.
"""

import logging

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.schema import (
    DETAIL_UNITS,
    LAYER_ROLES,
    MATERIALS,
    NOTES,
    STATES,
    STRUCTURES,
    BodyInterior,
    Layer,
)
from space_map_data.constants.interior.taxonomy import (
    MAHLKE_SCHEME,
    TAXONOMY_COMPOSITION,
    resolve_class,
)
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

    Read once into a plain dict rather than reached through
    `Object.ssodnet`: the bundle build runs in threads, and a relationship
    access there would be a lazy load per asteroid.
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


def _from_layers(object_id: str, facts: BodyInterior) -> dict:
    """Roll a per-body layer model up into one composition."""
    _validate(object_id, facts)

    block: dict = {"structure": facts.structure}
    if facts.note is not None:
        block["note"] = facts.note
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
    block["sources"] = _sources(_layer_source_keys(facts, composition, layers))
    return block


def _layer(object_id: str, layer: Layer) -> dict:
    """One layer of the cross-section.

    Radii are the source's own R, not the body's exported mean radius — the
    two disagree by a few km on Europa depending on the paper. The frontend
    normalizes the disc to the outermost layer rather than to the body, so
    the stack closes at the surface instead of leaving a gap.
    """
    out: dict = {"role": layer.role}
    if layer.outer_radius_km is not None:
        out["outer_radius_km"] = layer.outer_radius_km
    if layer.mass_fraction is not None:
        out["mass_fraction"] = _sig(layer.mass_fraction)
    if layer.mass_fraction_range is not None:
        out["mass_fraction_range"] = [_sig(v) for v in layer.mass_fraction_range]
    if layer.state is not None:
        out["state"] = layer.state
    if layer.note is not None:
        out["note"] = layer.note
    if layer.derived:
        out["derived"] = True
    if layer.diffuse:
        out["diffuse"] = True

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

    The structure line, then every layer — the cross-section draws each one's
    radius whatever its chemistry — then the chemistry of the materials that
    survived a sliver cut *somewhere*. A material can miss the whole-body bar
    and still fill its own layer, which is the case a sulphur-bearing core a
    percent of the body makes: 20% of the core, 0.2% of the planet.
    """
    keys: list[str] = []
    if facts.structure_source is not None:
        keys.append(facts.structure_source)
    shown = {c["material"] for c in composition}
    for layer, drawn in zip(facts.layers, layers):
        keys.append(layer.source)
        if layer.state_source is not None:
            keys.append(layer.state_source)
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
        [entry.source, *(c.source for c in entry.composition if c.material in shown)]
    )
    return block


def _class_credits(scheme: str | None, from_albedo_split: bool) -> list[str]:
    """Who to credit for the spectral class, as ids rather than citations.

    171,000 asteroids take this route, so a title and a url each would be
    megabytes of bundle for two names the frontend can hold itself. `sources`
    above stays full citations: it varies per body, these two do not.
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


def _validate(object_id: str, facts: BodyInterior) -> None:
    """Enum and citation check — a typo here would ship a body with an
    unlabelled tag or an uncredited number."""
    if facts.structure not in STRUCTURES:
        raise ValueError(f"{object_id}: unknown structure {facts.structure}")
    if facts.note is not None and facts.note not in NOTES:
        raise ValueError(f"{object_id}: unknown note {facts.note}")
    for layer in facts.layers:
        if layer.role not in LAYER_ROLES:
            raise ValueError(f"{object_id}: unknown layer role {layer.role}")
        if layer.note is not None and layer.note not in NOTES:
            raise ValueError(f"{object_id}: unknown note {layer.note}")
        if layer.state is not None and layer.state not in STATES:
            raise ValueError(f"{object_id}: unknown state {layer.state}")
        if layer.detail is not None and layer.detail.unit not in DETAIL_UNITS:
            raise ValueError(f"{object_id}: unknown detail unit {layer.detail.unit}")
        for component in layer.composition:
            if component.material not in MATERIALS:
                raise ValueError(f"{object_id}: unknown material {component.material}")


def _sources(keys: list[str]) -> list[dict]:
    """Dedupe, first occurrence wins — the work behind the structure leads."""
    out = []
    for key in dict.fromkeys(keys):
        ref = INTERIOR_SOURCES.get(key)
        if ref is None:
            raise ValueError(f"no such interior source {key}")
        out.append({"title": ref.title, "url": ref.url})
    return out


def _sig(value: float, digits: int = 4) -> float:
    return float(f"{value:.{digits}g}")
