"""One radius for each solar-system body, from the best source that has one.

The sources, best first:

1. A SPICE PCK ellipsoid, or an ellipsoid that a named work fitted.
2. The SBDB diameter.
3. The AsterSat radius of a satellite.
4. The Johnston's Archive diameter of a satellite or of a primary.
5. The AsterSat radius of a primary. AsterSat fits the satellite orbit and
   quotes the primary, so Johnston's compilation goes first for a primary.
6. The Wikidata radius (P2120), else half the Wikidata diameter (P2386).

The object bundles, the lineups, the group cards and the scene radius all take
a body's size from here, so they agree.
"""

from collections.abc import Callable, Mapping
from functools import cache
from typing import NamedTuple

from sqlalchemy.orm import Session

from space_map_data.constants.measured_shapes import measured_shape_references
from space_map_data.constants.orientation import ORIENTATION_SOURCE_PCK
from space_map_data.export.names import resolve_wikidata_qid
from space_map_data.export.objects.wikidata_claims import (
    diameter_km_from_claims,
    radius_km_from_claims,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.astersat_moon import AsterSatMoon
from space_map_data.models.object.johnston import JohnstonMoon, JohnstonSystem
from space_map_data.models.object.sbdb import SBDB

RADIUS_SOURCE_SBDB = "sbdb"
RADIUS_SOURCE_ASTERSAT = "astersat"
RADIUS_SOURCE_JOHNSTON = "johnston"
RADIUS_SOURCE_WIKIDATA = "wikidata"

_NOT_BODIES = frozenset(
    (ObjectType.spacecraft, ObjectType.debris, ObjectType.undocumented)
)


class BodyRadius(NamedTuple):
    """A body's semi-axes (km, body-fixed X, Y, Z) and the source of them."""

    a: float
    b: float
    c: float
    source: str
    # The work that fitted a measured ellipsoid.
    reference: dict | None = None

    @property
    def mean_km(self) -> float:
        return (self.a + self.b + self.c) / 3

    @property
    def diameter_km(self) -> float:
        """The one diameter that a card, a lineup or a minimap shows."""
        return 2 * self.mean_km

    @property
    def equatorial_km(self) -> float:
        return max(self.a, self.b, self.c)

    def axes(self) -> dict[str, float]:
        return {"a": self.a, "b": self.b, "c": self.c}


def _sphere(radius_km: float, source: str) -> BodyRadius:
    return BodyRadius(radius_km, radius_km, radius_km, source)


class BodyRadii:
    """The radius of each body, by the source order of this module."""

    def __init__(
        self,
        shapes: Mapping[int, BodyRadius] | None = None,
        sizes: Mapping[str, BodyRadius] | None = None,
        wikidata_km: Callable[[str], float | None] | None = None,
    ) -> None:
        self._shapes = shapes or {}
        self._sizes = sizes or {}
        self._wikidata_km = wikidata_km

    def pick(
        self,
        object_id: str,
        naif_id: int | None,
        qid: str | None,
        object_type: ObjectType,
    ) -> BodyRadius | None:
        # A craft has no body radius. Its Wikidata size is its span.
        if object_type in _NOT_BODIES:
            return None
        if naif_id is not None and (shape := self._shapes.get(naif_id)) is not None:
            return shape
        if (size := self._sizes.get(object_id)) is not None:
            return size
        if qid and self._wikidata_km and (radius_km := self._wikidata_km(qid)):
            return _sphere(radius_km, RADIUS_SOURCE_WIKIDATA)
        return None

    def of(self, obj: Object) -> BodyRadius | None:
        return self.pick(
            obj.id, obj.naif_id, resolve_wikidata_qid(obj), obj.object_type
        )


def kernel_shapes(radii: Mapping[int, dict]) -> dict[int, BodyRadius]:
    """The ellipsoids of ``load_radii`` by NAIF id, each with its source."""
    references = measured_shape_references()
    out: dict[int, BodyRadius] = {}
    for naif_id, axes in radii.items():
        measured = references.get(naif_id)
        source, reference = (
            (measured[0], dict(measured[1]._asdict()))
            if measured is not None
            else (ORIENTATION_SOURCE_PCK, None)
        )
        out[naif_id] = BodyRadius(axes["a"], axes["b"], axes["c"], source, reference)
    return out


def catalogue_sizes(session: Session) -> dict[str, BodyRadius]:
    """The SBDB, AsterSat and Johnston sizes by Object.id, best source per body."""
    out: dict[str, BodyRadius] = {}
    sources = (
        (RADIUS_SOURCE_SBDB, SBDB.object_id, SBDB.diameter, 0.5),
        (
            RADIUS_SOURCE_ASTERSAT,
            AsterSatMoon.object_id,
            AsterSatMoon.satellite_radius_km,
            1.0,
        ),
        (RADIUS_SOURCE_JOHNSTON, JohnstonMoon.object_id, JohnstonMoon.diameter_km, 0.5),
        (
            RADIUS_SOURCE_JOHNSTON,
            JohnstonSystem.object_id,
            JohnstonSystem.primary_diameter_km,
            0.5,
        ),
        (
            RADIUS_SOURCE_ASTERSAT,
            AsterSatMoon.parent_object_id,
            AsterSatMoon.primary_radius_km,
            1.0,
        ),
    )
    for source, object_id, size, to_radius in sources:
        rows = (
            session.query(object_id, size)
            .filter(object_id.is_not(None), size.is_not(None))
            .order_by(object_id, size)
        )
        for body_id, value in rows:
            out.setdefault(body_id, _sphere(value * to_radius, source))
    return out


def load_body_radii(
    session: Session,
    radii: Mapping[int, dict],
    entities: WikidataEntityCache,
    units: UnitConverter,
) -> BodyRadii:
    """The radii of every body for one export."""

    # Each QID is read once, so a claim warning is logged once.
    @cache
    def wikidata_km(qid: str) -> float | None:
        entity = entities.get_entity(qid)
        if entity is None:
            return None
        claims = entity["claims"]
        if (radius := radius_km_from_claims(claims, units, qid)) is not None:
            return radius
        diameter = diameter_km_from_claims(claims, units, qid)
        return diameter / 2 if diameter is not None else None

    return BodyRadii(kernel_shapes(radii), catalogue_sizes(session), wikidata_km)


def bundle_fields(size: BodyRadius | None) -> dict:
    """The object bundle's ``radii`` block. An SBDB size is in ``sbdb`` already."""
    if size is None or size.source == RADIUS_SOURCE_SBDB:
        return {}
    out: dict = {"radii": size.axes(), "radii_source": size.source}
    if size.reference is not None:
        out["radii_reference"] = size.reference
    return out


def lineup_radii(size: BodyRadius | None) -> dict | None:
    """A lineup record's ``radii``. A PCK shape has no ``source``."""
    if size is None or size.source == RADIUS_SOURCE_SBDB:
        return None
    if size.source == ORIENTATION_SOURCE_PCK:
        return size.axes()
    out: dict = {**size.axes(), "source": size.source}
    if size.reference is not None:
        out["reference"] = size.reference
    return out
