"""Telling a craft body apart from the booms and antennas it deploys."""

import pytest

from space_map_data.ingest.providers.models import geometry


def _box(cx, cy, cz, sx, sy, sz, step=0.25):
    """Triangles tiling a box's surface, as (min corner, max corner, area).

    Areas cap what the split reads, so a slab has to be built from real facets
    rather than declared — a boom has to *earn* its narrowness.
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
                    lo = [0.0, 0.0, 0.0]
                    lo[axis] = centre[axis] + face * size[axis]
                    lo[u] = centre[u] - size[u] / 2 + i * du
                    lo[v] = centre[v] - size[v] / 2 + j * dv
                    hi = list(lo)
                    hi[u] += du
                    hi[v] += dv
                    tris.append((tuple(lo), tuple(hi), du * dv))
    return tris


def _split(tris):
    lo = [min(t[0][k] for t in tris) for k in range(3)]
    hi = [max(t[1][k] for t in tris) for k in range(3)]
    outer = max(hi[k] - lo[k] for k in range(3))
    bounds = [geometry._body_range(tris, lo, hi, k) for k in range(3)]
    unit = outer / 2
    return (
        max(b - a for a, b in bounds) / outer,
        [((b + a) / 2 - (hi[k] + lo[k]) / 2) / unit for k, (a, b) in enumerate(bounds)],
    )


class TestBodyRange:
    """A slice's cross-section width is what separates craft from appendage."""

    def test_bare_bus_is_all_body(self):
        ratio, anchor = _split(_box(0, 0, 0, 2, 2, 2))
        assert ratio == pytest.approx(1.0, abs=0.05)
        assert anchor == pytest.approx([0, 0, 0], abs=0.05)

    def test_solar_wings_count_as_body(self):
        # A wing is thin but wide, so it stays in the craft's league — the span
        # a lineup places the craft on runs wingtip to wingtip.
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

    def test_tall_quads_fill_their_slices(self):
        # A low-poly rocket draws each stage as a few wall quads the full
        # stage height. Their area belongs to every slice they cross, not to
        # the one slice at their centroid, or the thinner top stage reads as
        # an appendage and the body gets seated too far down.
        first_stage = _box(0, 0, 0, 2, 2, 20, step=20)
        upper_stage = _box(0, 0, 15, 1, 1, 10, step=10)
        ratio, anchor = _split(first_stage + upper_stage)
        assert ratio == pytest.approx(1.0, abs=0.05)
        assert anchor == pytest.approx([0, 0, 0], abs=0.05)

    def test_narrow_panel_is_body_and_boom_of_its_width_is_not(self):
        # Four panels in a cross: the slice through the bus already holds a
        # whole pair, so a lone panel is under a tenth of it. Its shape saves
        # it — thin but wide is a plate. A square boom the same width is not.
        bus = _box(0, 0, 0, 2, 2, 2)
        pair = _box(0, 0, 0, 30, 0.05, 1.5)
        panel = _box(0, 0, 8, 1.5, 0.05, 14)
        boom = _box(0, 0, 8, 1.5, 1.5, 14)
        _ratio, anchor = _split(bus + pair + panel)
        assert anchor[2] == pytest.approx(0, abs=0.05)
        _ratio, anchor = _split(bus + pair + boom)
        assert anchor[2] == pytest.approx(-0.4, abs=0.1)
