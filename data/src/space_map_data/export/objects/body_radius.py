"""One radius for each solar-system body, from the best source that has one.

The sources, best first:

1. A size from a paper (`constants.body_literature`).
2. A SPICE PCK ellipsoid, or an ellipsoid that a named work fitted.
3. The SsODNet diameter, the best estimate of a compilation of papers.
4. The SBDB diameter.
5. The AsterSat radius of a satellite.
6. The Johnston's Archive diameter of a satellite or of a primary.
7. The AsterSat radius of a primary. AsterSat fits the satellite orbit and
   quotes the primary, so Johnston's compilation goes first for a primary.
8. The Wikidata radius (P2120), else half the Wikidata diameter (P2386).
9. A Johnston's Archive diameter that the archive estimated. Nominal.
10. A radius from a kernel of PLACEHOLDER_KERNELS. Nominal.

The object bundles, the lineups, the group cards, the scene radius of the
position chunks and the systems map's `radii`, which scale a body's mesh, all
take a body's size from here, so they agree.
"""

from collections.abc import Callable, Mapping
from fnmatch import fnmatch
from typing import NamedTuple

from sqlalchemy import false
from sqlalchemy.orm import Session

from space_map_data.constants.body_literature import (
    RADII,
    REFERENCES,
    VOLUMES,
    Volume,
)
from space_map_data.constants.measured_shapes import measured_shape_references
from space_map_data.constants.orientation import ORIENTATION_SOURCE_PCK
from space_map_data.export.names import resolve_wikidata_qid
from space_map_data.export.objects.wikidata_claims import (
    claim_reader,
    diameter_km_from_claims,
    radius_km_from_claims,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.astersat_moon import AsterSatMoon
from space_map_data.models.object.johnston import JohnstonMoon, JohnstonSystem
from space_map_data.models.object.sbdb import SBDB
from space_map_data.models.object.ssodnet import SsODNet

RADIUS_SOURCE_LITERATURE = "literature"
RADIUS_SOURCE_SSODNET = "ssodnet"
RADIUS_SOURCE_SBDB = "sbdb"
RADIUS_SOURCE_ASTERSAT = "astersat"
RADIUS_SOURCE_JOHNSTON = "johnston"
RADIUS_SOURCE_WIKIDATA = "wikidata"

# Kernels whose own comments call their radii placeholders. JUICE
# `juice_jup*.tpc`: "Placeholder radii". Cassini `cpck_rock_*.tpc`:
# "'placeholder' values". New Horizons `nh_stars_kbo_centaur_v*.tpc`:
# "synthetic body-fixed frames and radii", "default values".
PLACEHOLDER_KERNELS = (
    "juice_jup*.tpc",
    "cpck_rock_*.tpc",
    "nh_stars_kbo_centaur_v*.tpc",
)

NOT_BODIES = frozenset(
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
    # A placeholder or an estimate, not a measurement.
    nominal: bool = False
    # The volume of a paper's shape model (km³) and the paper ({title, url}).
    volume_km3: float | None = None
    volume_reference: dict | None = None

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


def _sphere(radius_km: float, source: str, nominal: bool = False) -> BodyRadius:
    return BodyRadius(radius_km, radius_km, radius_km, source, nominal=nominal)


def is_placeholder_kernel(kernel: str | None) -> bool:
    return bool(kernel) and any(
        fnmatch(kernel, pattern) for pattern in PLACEHOLDER_KERNELS
    )


class BodyRadii:
    """The radius of each body, by the source order of this module.

    ``shapes``, ``placeholders`` and ``volumes`` are keyed by NAIF id,
    ``sizes`` and ``nominal_sizes`` by Object.id.
    """

    def __init__(
        self,
        shapes: Mapping[int, BodyRadius] | None = None,
        sizes: Mapping[str, BodyRadius] | None = None,
        wikidata_km: Callable[[str], float | None] | None = None,
        nominal_sizes: Mapping[str, BodyRadius] | None = None,
        placeholders: Mapping[int, BodyRadius] | None = None,
        volumes: Mapping[int, Volume] | None = None,
    ) -> None:
        self._shapes = shapes or {}
        self._sizes = sizes or {}
        self._wikidata_km = wikidata_km
        self._nominal_sizes = nominal_sizes or {}
        self._placeholders = placeholders or {}
        self._volumes = volumes or {}

    def pick(
        self,
        object_id: str,
        naif_id: int | None,
        qid: str | None,
        object_type: ObjectType,
    ) -> BodyRadius | None:
        """The size of a body, with the volume of its shape model where a
        paper gives one."""
        size = self._size(object_id, naif_id, qid, object_type)
        volume = self._volumes.get(naif_id) if naif_id is not None else None
        if size is None or volume is None:
            return size
        return size._replace(
            volume_km3=volume.km3,
            volume_reference=REFERENCES[volume.reference]._asdict(),
        )

    def _size(
        self,
        object_id: str,
        naif_id: int | None,
        qid: str | None,
        object_type: ObjectType,
    ) -> BodyRadius | None:
        # A craft has no body radius. Its Wikidata size is its span.
        if object_type in NOT_BODIES:
            return None
        if naif_id is not None and (shape := self._shapes.get(naif_id)) is not None:
            return shape
        if (size := self._sizes.get(object_id)) is not None:
            return size
        if qid and self._wikidata_km and (radius_km := self._wikidata_km(qid)):
            return _sphere(radius_km, RADIUS_SOURCE_WIKIDATA)
        if (size := self._nominal_sizes.get(object_id)) is not None:
            return size
        if naif_id is not None:
            return self._placeholders.get(naif_id)
        return None

    def of(self, obj: Object) -> BodyRadius | None:
        return self.pick(
            obj.id, obj.naif_id, resolve_wikidata_qid(obj), obj.object_type
        )


def kernel_shapes(
    radii: Mapping[int, dict],
    kernels: Mapping[int, str] | None = None,
) -> dict[int, BodyRadius]:
    """The ellipsoids of ``load_radii`` by NAIF id, each with its source.

    ``kernels`` names the kernel of each PCK radius. The radii of
    PLACEHOLDER_KERNELS are left out: see `placeholder_shapes`.
    """
    kernels = kernels or {}
    references = measured_shape_references()
    out: dict[int, BodyRadius] = {}
    for naif_id, axes in radii.items():
        measured = references.get(naif_id)
        if measured is not None:
            out[naif_id] = BodyRadius(
                axes["a"], axes["b"], axes["c"], measured[0], measured[1]._asdict()
            )
        elif not is_placeholder_kernel(kernels.get(naif_id)):
            out[naif_id] = BodyRadius(
                axes["a"], axes["b"], axes["c"], ORIENTATION_SOURCE_PCK
            )
    return out


def placeholder_shapes(
    radii: Mapping[int, dict], kernels: Mapping[int, str]
) -> dict[int, BodyRadius]:
    """The radii of ``load_radii`` from PLACEHOLDER_KERNELS by NAIF id, nominal."""
    references = measured_shape_references()
    return {
        naif_id: BodyRadius(
            axes["a"], axes["b"], axes["c"], ORIENTATION_SOURCE_PCK, nominal=True
        )
        for naif_id, axes in radii.items()
        if naif_id not in references and is_placeholder_kernel(kernels.get(naif_id))
    }


def literature_shapes() -> dict[int, BodyRadius]:
    """The sizes of `constants.body_literature` by NAIF id."""
    return {
        naif_id: BodyRadius(
            *radii.semi_axes_km,
            RADIUS_SOURCE_LITERATURE,
            REFERENCES[radii.reference]._asdict(),
        )
        for naif_id, radii in RADII.items()
    }


def catalogue_sizes(
    session: Session,
) -> tuple[dict[str, BodyRadius], dict[str, BodyRadius]]:
    """The catalogue sizes by Object.id, best source per body.

    Returns the measured ones and the nominal ones apart.
    """
    sizes: dict[str, BodyRadius] = {}
    nominal_sizes: dict[str, BodyRadius] = {}
    sources = (
        (RADIUS_SOURCE_SSODNET, SsODNet.object_id, SsODNet.diameter_km, 0.5, None),
        (RADIUS_SOURCE_SBDB, SBDB.object_id, SBDB.diameter, 0.5, None),
        (
            RADIUS_SOURCE_ASTERSAT,
            AsterSatMoon.object_id,
            AsterSatMoon.satellite_radius_km,
            1.0,
            None,
        ),
        (
            RADIUS_SOURCE_JOHNSTON,
            JohnstonMoon.object_id,
            JohnstonMoon.diameter_km,
            0.5,
            JohnstonMoon.diameter_km_nominal,
        ),
        (
            RADIUS_SOURCE_JOHNSTON,
            JohnstonSystem.object_id,
            JohnstonSystem.primary_diameter_km,
            0.5,
            JohnstonSystem.primary_diameter_km_nominal,
        ),
        (
            RADIUS_SOURCE_ASTERSAT,
            AsterSatMoon.parent_object_id,
            AsterSatMoon.primary_radius_km,
            1.0,
            None,
        ),
    )
    for source, object_id, size, to_radius, nominal in sources:
        flag = nominal if nominal is not None else false()
        rows = (
            session.query(object_id, size, flag)
            .filter(object_id.is_not(None), size.is_not(None))
            .order_by(object_id, size)
        )
        for body_id, value, is_nominal in rows:
            out = nominal_sizes if is_nominal else sizes
            out.setdefault(body_id, _sphere(value * to_radius, source, is_nominal))
    return sizes, nominal_sizes


def _wikidata_radius_km(claims: dict, units: UnitConverter, qid: str) -> float | None:
    """The Wikidata radius, else half the Wikidata diameter."""
    if (radius := radius_km_from_claims(claims, units, qid)) is not None:
        return radius
    diameter = diameter_km_from_claims(claims, units, qid)
    return diameter / 2 if diameter is not None else None


def load_body_radii(
    session: Session,
    radii: Mapping[int, dict],
    kernels: Mapping[int, str],
    entities: WikidataEntityCache,
    units: UnitConverter,
) -> BodyRadii:
    """The radii of every body for one export. ``kernels`` names the kernel of
    each PCK radius (`RadiusTable.kernels` of `load_radii`)."""
    sizes, nominal_sizes = catalogue_sizes(session)
    return BodyRadii(
        {**kernel_shapes(radii, kernels), **literature_shapes()},
        sizes,
        claim_reader(entities, units, _wikidata_radius_km),
        nominal_sizes,
        placeholder_shapes(radii, kernels),
        VOLUMES,
    )


def bundle_fields(size: BodyRadius | None) -> dict:
    """The object bundle's ``radii`` block. An SBDB size is in ``sbdb`` already."""
    if size is None or size.source == RADIUS_SOURCE_SBDB:
        return {}
    out: dict = {"radii": size.axes(), "radii_source": size.source}
    if size.reference is not None:
        out["radii_reference"] = size.reference
    if size.nominal:
        out["radii_nominal"] = True
    return out


def lineup_radii(size: BodyRadius | None) -> dict | None:
    """A lineup record's ``radii``. A measured PCK shape has no ``source``."""
    if size is None or size.source == RADIUS_SOURCE_SBDB:
        return None
    if size.source == ORIENTATION_SOURCE_PCK and not size.nominal:
        return size.axes()
    out: dict = {**size.axes(), "source": size.source}
    if size.reference is not None:
        out["reference"] = size.reference
    if size.nominal:
        out["nominal"] = True
    return out
