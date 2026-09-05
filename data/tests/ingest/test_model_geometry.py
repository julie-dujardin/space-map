"""Telling a craft body apart from the booms and antennas it deploys."""

import pytest

from space_map_data.ingest.providers.models import geometry


def _box(cx, cy, cz, sx, sy, sz, step=0.25):
    """Triangles tiling a box's surface, as (centroid, area) pairs.

    Areas are what the split reads, so a slab has to be built from real facets
    rather than declared — a boom has to *earn* its small perimeter.
    """
    tris = []
    for axis in range(3):
        u, v = [k for k in range(3) if k != axis]
        size = (sx, sy, sz)
        centre = (cx, cy, cz)
        nu = max(1, int(size[u] / step))
        nv = max(1, int(size[v] / step))
        du, dv = size[u] / nu, size[v] / nv
        for face in (-0.5, 0.5):
            for i in range(nu):
                for j in range(nv):
                    p = [0.0, 0.0, 0.0]
                    p[axis] = centre[axis] + face * size[axis]
                    p[u] = centre[u] - size[u] / 2 + (i + 0.5) * du
                    p[v] = centre[v] - size[v] / 2 + (j + 0.5) * dv
                    tris.append((tuple(p), du * dv))
    return tris


def _split(tris):
    lo = [min(c[k] for c, _a in tris) for k in range(3)]
    hi = [max(c[k] for c, _a in tris) for k in range(3)]
    outer = max(hi[k] - lo[k] for k in range(3))
    bounds = [geometry._body_range(tris, lo, hi, k) for k in range(3)]
    unit = outer / 2
    return (
        max(b - a for a, b in bounds) / outer,
        [((b + a) / 2 - (hi[k] + lo[k]) / 2) / unit for k, (a, b) in enumerate(bounds)],
    )


class TestBodyRange:
    """A slice's perimeter is what separates craft from appendage."""

    def test_bare_bus_is_all_body(self):
        ratio, anchor = _split(_box(0, 0, 0, 2, 2, 2))
        assert ratio == pytest.approx(1.0, abs=0.05)
        assert anchor == pytest.approx([0, 0, 0], abs=0.05)

    def test_solar_wings_count_as_body(self):
        # A wing is thin but wide, so its perimeter stays in the craft's league
        # — the span a lineup places the craft on runs wingtip to wingtip.
        craft = (
            _box(0, 0, 0, 2, 2, 2)
            + _box(0, 0, 5, 3, 0.05, 8)
            + _box(0, 0, -5, 3, 0.05, 8)
        )
        ratio, _anchor = _split(craft)
        assert ratio == pytest.approx(1.0, abs=0.05)

    def test_boom_is_not_body(self):
        # Ulysses' shape: a small bus with a wire antenna many times its length.
        craft = _box(0, 0, 0, 2, 2, 2) + _box(0, 0, 15, 0.04, 0.04, 30)
        ratio, anchor = _split(craft)
        assert ratio < 0.15
        # The bus sits at one end of a mesh that is almost all boom, so it is
        # nearly a full half-span off the box centre the mesh would seat on.
        assert anchor[2] == pytest.approx(-0.93, abs=0.05)
