"""Geometry of the IAU planetary quadrangle grids.

Each mapped body divides its surface into a fixed set of numbered chart areas —
Mercury's 15 ``H-`` quadrangles, Mars' 30 ``mc``, Venus' 62 ``v``, the Moon's
144 ``LAC`` charts. The grids are regular: latitude rows of equal-width
longitude cells, so a compact row spec reproduces every box exactly.

The specs below were reconstructed from the gazetteer itself — every one of the
13,668 features carrying a ``quad_code`` falls inside the box derived here for
that code, bar ten Mars albedo features whose centre lands exactly on a cell
edge. Longitudes are east-positive 0–360, matching ``Feature.center_lon``.

Note the numbering directions differ: Mercury's rows run west (H-2 is the
0–90°W cell), Mars' start at the 180° antimeridian, Venus' at the prime
meridian, and the Moon's begin near the western limb on a grid whose cell edges
are offset 10° east of the prime meridian.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class QuadRow:
    """One latitude band of a body's grid, split into ``count`` equal cells."""

    lat_min: float
    lat_max: float
    #: Number of the row's first quadrangle (codes are consecutive from here).
    first: int
    count: int
    #: East longitude at which the first quadrangle begins.
    lon_start: float
    #: Whether consecutive numbers step east; False steps west.
    eastward: bool = True


@dataclass(frozen=True)
class Quadrangle:
    """A single chart area. ``lon_min`` is east-positive; a cell that straddles
    the prime meridian has ``lon_min + lon_span > 360``."""

    code: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_span: float


# (code format, rows) per body. Polar caps are single full-longitude cells.
_GRIDS: dict[str, tuple[str, tuple[QuadRow, ...]]] = {
    "naif-199": (  # Mercury — 15 quadrangles, rows numbered westward
        "H-%02d",
        (
            QuadRow(65, 90, 1, 1, 0),
            QuadRow(22, 65, 2, 4, 270, eastward=False),
            QuadRow(-22, 22, 6, 5, 288, eastward=False),
            QuadRow(-65, -22, 11, 4, 270, eastward=False),
            QuadRow(-90, -65, 15, 1, 0),
        ),
    ),
    "naif-299": (  # Venus — 62 quadrangles from the prime meridian
        "v%02d",
        (
            QuadRow(75, 90, 1, 1, 0),
            QuadRow(50, 75, 2, 6, 0),
            QuadRow(25, 50, 8, 12, 0),
            QuadRow(0, 25, 20, 12, 0),
            QuadRow(-25, 0, 32, 12, 0),
            QuadRow(-50, -25, 44, 12, 0),
            QuadRow(-75, -50, 56, 6, 0),
            QuadRow(-90, -75, 62, 1, 0),
        ),
    ),
    "naif-499": (  # Mars — 30 MC quadrangles from the antimeridian
        "mc%02d",
        (
            QuadRow(65, 90, 1, 1, 0),
            QuadRow(30, 65, 2, 6, 180),
            QuadRow(0, 30, 8, 8, 180),
            QuadRow(-30, 0, 16, 8, 180),
            QuadRow(-65, -30, 24, 6, 180),
            QuadRow(-90, -65, 30, 1, 0),
        ),
    ),
    "naif-301": (  # Moon — 144 LAC charts on a grid offset 10°E
        "LAC-%d",
        (
            QuadRow(80, 90, 1, 1, 0),
            QuadRow(64, 80, 2, 8, 280),
            QuadRow(48, 64, 10, 12, 280),
            QuadRow(32, 48, 22, 15, 274),
            QuadRow(16, 32, 37, 18, 270),
            QuadRow(0, 16, 55, 18, 270),
            QuadRow(-16, 0, 73, 18, 270),
            QuadRow(-32, -16, 91, 18, 270),
            QuadRow(-48, -32, 109, 15, 274),
            QuadRow(-64, -48, 124, 12, 280),
            QuadRow(-80, -64, 136, 8, 280),
            QuadRow(-90, -80, 144, 1, 0),
        ),
    ),
}


def _build(fmt: str, rows: tuple[QuadRow, ...]) -> list[Quadrangle]:
    out: list[Quadrangle] = []
    for row in rows:
        span = 360.0 / row.count
        for k in range(row.count):
            offset = k * span if row.eastward else -k * span
            out.append(
                Quadrangle(
                    code=fmt % (row.first + k),
                    lat_min=row.lat_min,
                    lat_max=row.lat_max,
                    lon_min=(row.lon_start + offset) % 360,
                    lon_span=span,
                )
            )
    return out


#: Body id → its quadrangles, in code order.
QUADRANGLES: dict[str, list[Quadrangle]] = {
    body: _build(fmt, rows) for body, (fmt, rows) in _GRIDS.items()
}

_BY_CODE: dict[str, dict[str, Quadrangle]] = {
    body: {q.code: q for q in quads} for body, quads in QUADRANGLES.items()
}


def quadrangle(body_id: str, code: str) -> Quadrangle | None:
    """The named quadrangle's box, or None for an unmapped body/code."""
    return _BY_CODE.get(body_id, {}).get(code)


def quadrangle_for(body_id: str, lat: float, lon: float) -> str | None:
    """The quadrangle code containing a point, or None off the mapped bodies.

    Cells are half-open in longitude, so a feature centred exactly on a cell
    edge lands in the eastern neighbour — which is how the ten Mars albedo
    features noted in the module docstring drift from the IAU's own assignment.
    """
    quads = QUADRANGLES.get(body_id)
    if quads is None:
        return None
    east = lon % 360
    for q in quads:
        if q.lat_min <= lat <= q.lat_max and (east - q.lon_min) % 360 < q.lon_span:
            return q.code
    return None


def _validate() -> None:
    """Grid invariants — rows must tile the sphere without gaps or overlaps."""
    for body, (fmt, rows) in _GRIDS.items():
        ordered = sorted(rows, key=lambda r: r.lat_min)
        assert ordered[0].lat_min == -90 and ordered[-1].lat_max == 90, body
        for lower, upper in zip(ordered, ordered[1:]):
            assert lower.lat_max == upper.lat_min, (body, lower, upper)
        codes = [q.code for q in QUADRANGLES[body]]
        assert len(codes) == len(set(codes)), body
        expected = [fmt % n for n in range(1, len(codes) + 1)]
        assert sorted(codes) == sorted(expected), body


_validate()
