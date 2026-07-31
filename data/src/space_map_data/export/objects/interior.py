"""Per-object interior stat block, denormalized onto a body's global bundle.

Two sources feed one shape. A body a mission actually constrained has a layer
model in `constants/interior/bodies.py`; an asteroid that only has a spectrum
gets its meteorite analogue's bulk chemistry from `constants/interior/
taxonomy.py`, and ships flagged as an estimate so the panel can say "estimated
from its S-type spectrum" rather than "is".

What ships is the whole-body roll-up — one share per material, summed over the
layers — because that is what the single composition chart draws. The layers
themselves stay in the constants until the per-layer view exists; putting them
on every bundle now would cost bytes on 150,000 asteroids to draw nothing.

The roll-up is a mass balance over layers, not an elemental one: water bound
in a phyllosilicate counts as water, not as oxygen shared out among the rocks.
"""

import logging

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.schema import (
    LAYER_ROLES,
    MATERIALS,
    NOTES,
    STRUCTURES,
    BodyInterior,
)
from space_map_data.constants.interior.taxonomy import (
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
    sources: list[str] = []
    if facts.structure_source is not None:
        sources.append(facts.structure_source)

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
        block["composition"] = _shares(object_id, shares)

    for layer in facts.layers:
        sources.append(layer.source)
        sources.extend(c.source for c in layer.composition)

    block["sources"] = _sources(sources)
    return block


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
    entry = TAXONOMY_COMPOSITION[resolved]

    block: dict = {
        # Never "differentiated": a spectrum is a statement about the surface,
        # and the analogue is a rock, not a structure.
        "estimated": True,
        "analogue": entry.analogue,
        "taxonomy_class": taxonomy_class,
        "composition": _shares(
            object_id, {c.material: c.fraction for c in entry.composition}
        ),
    }
    # A class letter means different things under Tholen, Bus and Bus-DeMeo,
    # so the scheme travels with it to the panel.
    if scheme is not None:
        block["taxonomy_scheme"] = scheme
    if entry.note is not None:
        block["note"] = entry.note
    block["sources"] = _sources([entry.source, *(c.source for c in entry.composition)])
    return block


def _shares(object_id: str, shares: dict[str, float]) -> list[dict]:
    """Largest first, slivers dropped, renormalized over what is left."""
    kept = {m: v for m, v in shares.items() if v >= _MIN_SHARE}
    dropped = sorted(set(shares) - set(kept))
    if dropped:
        logger.info(
            "%s: dropping %s below %.1f%% of the body",
            object_id,
            ", ".join(dropped),
            _MIN_SHARE * 100,
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
