"""Tests for the IAU quadrangle grid and its export tier."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.nomenclature.quadrangle_grid import (
    QUADRANGLES,
    quadrangle,
    quadrangle_for,
)
from space_map_data.export.nomenclature.quadrangles import (
    build_quadrangles,
    load_quadrangles,
    write_quadrangles,
)
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _feature(fid: int, body: str, lat: float, lon: float, **kwargs) -> Feature:
    return Feature(
        feature_id=fid,
        object_id=body,
        name=kwargs.pop("name", f"F{fid}"),
        target=kwargs.pop("target", "MARS"),
        center_lat=lat,
        center_lon=lon,
        feature_type_code=kwargs.pop("feature_type_code", "AA"),
        **kwargs,
    )


class TestGrid:
    """The reconstructed row specs, checked as a tiling of each sphere."""

    def test_expected_counts(self):
        assert {body: len(q) for body, q in QUADRANGLES.items()} == {
            "naif-199": 15,
            "naif-299": 62,
            "naif-499": 30,
            "naif-301": 144,
        }

    def test_rows_tile_longitude(self):
        for body, quads in QUADRANGLES.items():
            by_row: dict[tuple[float, float], list] = {}
            for q in quads:
                by_row.setdefault((q.lat_min, q.lat_max), []).append(q)
            for row, cells in by_row.items():
                total = sum(c.lon_span for c in cells)
                assert total == pytest.approx(360), (body, row)
                starts = sorted(c.lon_min for c in cells)
                assert len(set(starts)) == len(starts), (body, row)

    def test_every_point_lands_in_exactly_one_cell(self):
        for body in QUADRANGLES:
            for lat in (-89.0, -45.0, -0.5, 0.5, 45.0, 89.0):
                for lon in (0.0, 42.5, 179.9, 180.1, 271.0, 359.9):
                    hits = [
                        q.code
                        for q in QUADRANGLES[body]
                        if q.lat_min <= lat <= q.lat_max
                        and (lon - q.lon_min) % 360 < q.lon_span
                    ]
                    assert len(hits) == 1, (body, lat, lon, hits)

    def test_known_features(self):
        # Olympus Mons, Copernicus, Beethoven basin, Alpha Regio.
        assert quadrangle_for("naif-499", 18.65, 226.2) == "mc09"
        assert quadrangle_for("naif-301", 9.62, 339.9) == "LAC-58"
        assert quadrangle_for("naif-199", -20.8, 236.4) == "H-07"
        assert quadrangle_for("naif-299", -22.0, 5.0) == "v32"

    def test_unmapped_body(self):
        assert quadrangle_for("naif-599", 0.0, 0.0) is None
        assert quadrangle("naif-499", "mc99") is None

    def test_negative_longitude_normalizes(self):
        assert quadrangle_for("naif-499", 10.0, -20.0) == quadrangle_for(
            "naif-499", 10.0, 340.0
        )


class TestBuildQuadrangles:
    """The exported per-body payload: names, counts and edge-case overrides."""

    def test_names_and_counts_from_the_gazetteer(self, session: Session):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add_all(
            [
                _feature(
                    1, "naif-499", 18.65, 226.2, quad_code="mc09", quad_name="Tharsis"
                ),
                _feature(
                    2, "naif-499", 20.0, 230.0, quad_code="mc09", quad_name="Tharsis"
                ),
                _feature(
                    3, "naif-499", 80.0, 10.0, quad_code="mc01", quad_name="Mare Boreum"
                ),
            ]
        )
        session.commit()

        out = build_quadrangles(session)
        quads = {q["code"]: q for q in out["naif-499"]["quads"]}
        assert len(quads) == 30
        assert quads["mc09"]["name"] == "Tharsis"
        assert quads["mc09"]["n"] == 2
        assert quads["mc01"]["n"] == 1
        # Types with no features still ship — the hero draws the whole grid.
        assert quads["mc30"]["n"] == 0
        assert quads["mc30"]["name"] == "mc30"
        assert out["naif-499"]["overrides"] == {}

    def test_edge_feature_keeps_the_gazetteer_cell(self, session: Session):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        # Centred exactly on the mc04/mc05 edge; the grid would say mc05.
        session.add(
            _feature(
                9, "naif-499", 39.7, 360.0, quad_code="mc04", quad_name="Mare Acidalium"
            )
        )
        session.commit()

        out = build_quadrangles(session)
        assert out["naif-499"]["overrides"] == {"9": "mc04"}
        quads = {q["code"]: q for q in out["naif-499"]["quads"]}
        assert quads["mc04"]["n"] == 1
        assert quads["mc05"]["n"] == 0

    def test_body_without_features_is_dropped(self, session: Session):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add(
            _feature(1, "naif-499", 0.0, 0.0, quad_code="mc12", quad_name="Arabia")
        )
        session.commit()

        assert set(build_quadrangles(session)) == {"naif-499"}

    def test_unrenderable_features_excluded(self, session: Session):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add_all(
            [
                _feature(1, "naif-499", 0.0, 0.0, quad_code="mc12", quad_name="Arabia"),
                # No type code — never reaches the map, so never the hero's count.
                _feature(
                    2,
                    "naif-499",
                    1.0,
                    1.0,
                    quad_code="mc12",
                    quad_name="Arabia",
                    feature_type_code=None,
                ),
            ]
        )
        session.commit()

        quads = {q["code"]: q for q in build_quadrangles(session)["naif-499"]["quads"]}
        assert quads["mc12"]["n"] == 1

    def test_missing_quad_code_falls_back_to_geometry(self, session: Session):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add(_feature(1, "naif-499", 18.65, 226.2))
        session.commit()

        quads = {q["code"]: q for q in build_quadrangles(session)["naif-499"]["quads"]}
        assert quads["mc09"]["n"] == 1


class TestWriteQuadrangles:
    """File layout: geometry global, Wikipedia intros split per language."""

    def test_round_trips_and_splits_languages(self, session: Session, tmp_path):
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add(
            _feature(1, "naif-499", 0.0, 0.0, quad_code="mc12", quad_name="Arabia")
        )
        session.commit()
        payload = build_quadrangles(session)
        texts = {
            "en": {"naif-499:mc12": {"extract": "The Arabia quadrangle…"}},
            "fr": {"naif-499:mc12": {"extract": "Le quadrangle d'Arabia…"}},
        }

        write_quadrangles(tmp_path / "v1", payload, texts)

        quads = tmp_path / "v1" / "nomenclature" / "quadrangles"
        assert {p.name for p in quads.iterdir()} == {
            "__global__.json.gz",
            "en.json.gz",
            "fr.json.gz",
        }
        assert load_quadrangles(tmp_path)["naif-499"]["quads"][11]["code"] == "mc12"

    def test_no_payload_writes_nothing(self, tmp_path):
        write_quadrangles(tmp_path / "v1", {}, {})
        assert not (tmp_path / "v1").exists()
