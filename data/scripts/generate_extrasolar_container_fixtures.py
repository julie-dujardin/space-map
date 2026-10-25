"""Write small extrasolar container files for the frontend parser test.

The production writer (`export/extrasolar/container.py`) encodes them, so the
frontend test ([frontend/src/lib/fetch/extrasolar/container.test.ts]) reads
the same bytes as a real export. `expected.json` holds the values the test
compares with. The fixtures are committed; regenerate them after a change of
the container format.

    cd data && uv run python scripts/generate_extrasolar_container_fixtures.py
"""

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.export.extrasolar import container, render
from space_map_data.export.extrasolar.container import Column
from space_map_data.extrasolar.tables import CROSS_ID

OUTPUT_DIR = REPO_ROOT / "frontend/src/lib/fetch/extrasolar/__fixtures__"
TOKEN = b"0123456789abcdef"

TILE_PIXEL = 335040
TILE_LEVEL = 8
TILE_TABLE = 1

NODE_CENTRE = (-8.0, 8.0, -8.0)
NODE_HALF = 8.0
NODE_CHILD_RANGE = (0.0, 12.5, 0.0, 0.0, 3.25, 0.0, 0.0, 0.0)
NODE_DEPTH = 14


def tile_columns() -> list[Column]:
    cross = pa.array(
        [
            [
                {"catalogue": "gaia", "release": "dr3", "catalogue_id": "123"},
                {"catalogue": "hip", "release": "2007", "catalogue_id": "32349"},
            ],
            None,
            [
                {"catalogue": "hip", "release": "2007", "catalogue_id": "7"},
                {"catalogue": "iau", "release": "wgsn", "catalogue_id": "Sîrius"},
                {"catalogue": "gaia", "release": "dr3", "catalogue_id": "9"},
            ],
        ],
        pa.list_(CROSS_ID),
    )
    return [
        Column("id", "id", pa.array([22137869, 2**53 - 1, 564339647], pa.int64())),
        Column("ra", "float64", pa.array([101.287, None, -3.25])),
        Column("mag", "float32", pa.array([-1.5, 2.25, None], pa.float32())),
        Column("flag", "bool", pa.array([True, None, False])),
        Column("i8", "int8", pa.array([-128, 0, 127], pa.int8())),
        Column("i16", "int16", pa.array([None, -5, 7], pa.int16())),
        Column("i32", "int32", pa.array([-2147483648, 1, 2147483647], pa.int32())),
        Column("u8", "uint8", pa.array([0, 200, 255], pa.uint8())),
        Column("u16", "uint16", pa.array([65535, 1, None], pa.uint16())),
        Column("mask", "uint32", pa.array([2, 0, 4294967295], pa.uint32())),
        Column("name", "string", pa.array(["α Cen", None, ""])),
        Column("source", "dict", pa.array(["gaia-dr3", "hipparcos-2007", None])),
        Column("cross_ids", "cross_ids", cross),
        Column("alias_target", "id", pa.array([None, None, 27468735], pa.int64())),
        Column("flags", "uint64", pa.array([2**57 + 64, None, 2**64 - 1], pa.uint64())),
        Column(
            "corr_vec",
            "float32_list",
            pa.array([[0.5, float("nan"), -0.25], None, []], pa.list_(pa.float32())),
        ),
    ]


def node_columns() -> list[Column]:
    f32 = pa.float32()
    return [
        Column("x", "float32", pa.array([0.5, -7.75, 1.0, 0.0, 3.0], f32)),
        Column("y", "float32", pa.array([-0.25, 6.5, 0.0, 2.0, -3.0], f32)),
        Column("z", "float32", pa.array([7.0, 0.125, -1.0, 0.0, 0.5], f32)),
        Column("range", "float32", pa.array([40.0, 30.0, 20.0, 15.0, 13.0], f32)),
        Column("mag", "float32", pa.array([1.42, 4.83, 13.41, 9.0, 10.5], f32)),
        Column("colour", "float32", pa.array([0.0, 0.82, 3.8, None, 1.5], f32)),
        Column("class", "uint8", pa.array([1, 1, 1, 1, 1], pa.uint8())),
    ]


def node_info() -> bytes:
    return render.NODE_INFO.pack(
        *NODE_CENTRE,
        NODE_HALF,
        13.0,
        40.0,
        *NODE_CHILD_RANGE,
        NODE_DEPTH,
        sum(1 << k for k, r in enumerate(NODE_CHILD_RANGE) if r > 0),
    )


def write(name: str, payload: bytes) -> None:
    (OUTPUT_DIR / name).write_bytes(container.gzip_payload(payload))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tile = tile_columns()
    tile_info = struct.pack("<IBB2x", TILE_PIXEL, TILE_LEVEL, TILE_TABLE)
    write(
        "tile.bin.gz",
        container.encode(container.KIND_TILE, 3, tile, tile_info, TOKEN),
    )
    node = node_columns()
    write(
        "node.bin.gz",
        container.encode(container.KIND_NODE, 5, node, node_info(), TOKEN),
    )
    bits = np.array([1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0], bool)
    write(
        "split.bin.gz",
        container.encode(
            container.KIND_SPLIT, len(bits), [Column("split", "bits", bits)], b"", TOKEN
        ),
    )

    def json_value(kind: str, value):
        # JSON numbers lose integers past 2^53 and hold no NaN.
        if value is None:
            return None
        if kind == "uint64":
            return str(value)
        if kind == "float32_list":
            return [None if np.isnan(x) else x for x in value]
        return value

    def values(columns: list[Column]) -> dict:
        out = {}
        for column in columns:
            assert isinstance(column.values, pa.Array)
            out[column.name] = {
                "type": column.kind,
                "values": [
                    json_value(column.kind, v) for v in column.values.to_pylist()
                ],
            }
        return out

    expected = {
        "token": TOKEN.decode(),
        "tile": {
            "pixel": TILE_PIXEL,
            "level": TILE_LEVEL,
            "table": TILE_TABLE,
            "columns": values(tile),
        },
        "node": {
            "centre": NODE_CENTRE,
            "half": NODE_HALF,
            "min_range": 13.0,
            "max_range": 40.0,
            "child_range": NODE_CHILD_RANGE,
            "depth": NODE_DEPTH,
            "columns": values(node),
        },
        "split": [bool(b) for b in bits],
    }
    text = json.dumps(expected, indent="\t", ensure_ascii=False) + "\n"
    (OUTPUT_DIR / "expected.json").write_text(text)
    print(f"Wrote 3 files and expected.json to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
