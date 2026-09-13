from dataclasses import replace
import json
from pathlib import Path
import re

import httpx
import numpy as np
import pytest

from space_map_data.panoramas.labels import (
    Mosaic,
    attached_constants,
    read_pds3,
    read_pds4,
)
from space_map_data.panoramas.pipeline import (
    download,
    fetch,
    positions,
    process,
    read_pixels,
    sphere_texture,
    coverage,
    MSL,
    PLACES,
)

FIXTURES = Path(__file__).parent / "fixtures"


def mosaic(**kwargs):
    return replace(
        Mosaic(
            "test",
            1,
            3,
            110,
            "",
            "",
            360,
            90,
            1,
            ">i2",
            0,
            0,
            1,
            1,
            46,
            "SITE_FRAME",
            (0,),
        ),
        **kwargs,
    )


def test_official_pds3_geometry():
    label = (FIXTURES / "curiosity.lbl").read_text()
    result = read_pds3(label)
    assert (result.sol, result.site, result.drive) == (24, 3, 372)
    assert (result.width, result.height, result.offset) == (7703, 977, 46218)
    assert (result.zero_line - 1) / result.scale_y == pytest.approx(6.1515, abs=0.0001)
    with pytest.raises(ValueError, match="Only angular"):
        read_pds3(label.replace("= CYLINDRICAL", "= CYLINDRICAL-PERSPECTIVE"))
    with pytest.raises(ValueError, match="multiple"):
        read_pds3(label.replace("F0030372", "F0030373", 1))


def test_official_pds4_geometry():
    label = (FIXTURES / "perseverance.xml").read_text()
    result = read_pds4(label)
    assert (result.sol, result.site, result.drive) == (14, 3, 110)
    assert (result.width, result.height, result.bands, result.offset) == (
        4646,
        1207,
        3,
        18584,
    )
    with pytest.raises(ValueError, match="not aligned"):
        read_pds4(
            label.replace("<geom:qcos>1.0</geom:qcos>", "<geom:qcos>0.9</geom:qcos>")
        )


def test_cardinal_directions_and_partial_sphere():
    rgba = np.full((90, 360, 4), 255, dtype=np.uint8)
    rgba[:, :, 0] = (np.arange(360) // 90)[None, :]
    result = np.asarray(sphere_texture(rgba, mosaic(azimuth=90), 360))
    assert result.shape == (180, 360, 4)
    assert result[90, [0, 90, 180, 270], 0].tolist() == [3, 0, 1, 2]
    assert not result[:40, :, 3].any()
    assert not result[140:, :, 3].any()
    assert result[90, :, 3].all()


def test_pds_one_based_horizon():
    rgba = np.zeros((3, 360, 4), dtype=np.uint8)
    rgba[1] = [150, 150, 150, 255]
    result = np.asarray(sphere_texture(rgba, mosaic(height=3, zero_line=2.5), 360))
    assert result[89, 0].tolist() == [150, 150, 150, 255]
    assert result[90, 0, 3] == 0


def test_big_endian_offset_and_missing_mask(tmp_path):
    path = tmp_path / "test.img"
    pixels = np.arange(360 * 3, dtype=">i2").reshape(1, 3, 360)
    path.write_bytes(b"header" + pixels.tobytes())
    rgba, tone = read_pixels(path, mosaic(height=3, offset=6))
    assert rgba[0, 0, 3] == 0
    assert rgba[-1, -1, 3] == 255
    assert rgba[-1, -1, 0] > rgba[0, 50, 0]
    assert tone["source_dn_range"][1] < 1080
    path.write_bytes(b"header")
    with pytest.raises(ValueError):
        read_pixels(path, mosaic(height=3, offset=6))


def test_coordinate_grid_is_excluded_from_image(tmp_path):
    path = tmp_path / "test.img"
    pixels = (np.arange(3 * 360) % 2000 + 1000).astype(">i2").reshape(1, 3, 360)
    pixels[0, 1, 90:270] = 4096
    path.write_bytes(pixels.tobytes())

    rgba, _ = read_pixels(path, mosaic(height=3, offset=0))

    assert not rgba[1, 90:270, 3].any()
    assert rgba[1, :90, 3].all()
    assert rgba[1, 270:, 3].all()


def test_ambiguous_localizations_are_excluded(tmp_path):
    path = tmp_path / "positions.json"
    rows = [
        {"site": 3, "drive": drive, "lat": lat, "lon": -1, "elev_geoid": -2500}
        for drive, lat in [(0, 18), (0, 19), (110, 18)]
    ]
    path.write_text(json.dumps({"features": [{"properties": row} for row in rows]}))
    result = positions("perseverance", path)
    assert (3, 0) not in result
    assert result[3, 110]["longitude"] == 359


def test_atomic_download_and_offline_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("space_map_data.panoramas.pipeline.time.sleep", lambda _: None)
    path = tmp_path / "image.img"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"image")
        )
    ) as client:
        fetch(client, "https://example.test/image", path)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        assert (
            fetch(client, "https://example.test/image", path).read_bytes() == b"image"
        )
        with pytest.raises(httpx.HTTPStatusError):
            fetch(client, "https://example.test/image", path, refresh=True)
    assert path.read_bytes() == b"image"


def test_streamed_error_body_remains_readable(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"code": "invalid_page"})
        )
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            fetch(client, "https://example.test/page", tmp_path / "page.json")
    assert caught.value.response.json() == {"code": "invalid_page"}
    assert not (tmp_path / "page.json").exists()


def test_partial_horizontal_coverage_wraps_without_smearing():
    source = mosaic(width=90, height=180, azimuth=315, zero_line=90.5)
    source.validate()
    rgba = np.full((180, 90, 4), 255, dtype=np.uint8)
    texture = sphere_texture(rgba, source, 360)
    alpha = np.asarray(texture)[:, :, 3]
    assert alpha[90, 0] == 255
    assert alpha[90, 180] == 0
    metrics = coverage(texture, source)
    assert metrics["horizontal_percent"] == 25
    assert metrics["sphere_percent"] == pytest.approx(25, abs=0.3)


def test_sphere_area_is_not_canvas_area():
    from PIL import Image

    rgba = np.zeros((180, 360, 4), dtype=np.uint8)
    rgba[60:120, :, 3] = 255
    metrics = coverage(Image.fromarray(rgba), mosaic())
    assert metrics["canvas_percent"] == pytest.approx(100 / 3)
    assert metrics["sphere_percent"] == pytest.approx(50)
    rgba[:, 180:, 3] = 0
    assert coverage(Image.fromarray(rgba), mosaic())["sphere_percent"] == pytest.approx(
        25
    )


def test_pds4_site_frame_without_drive():
    label = (FIXTURES / "perseverance.xml").read_text()
    label = label.replace("LOCAL_LEVEL_FRAME", "SITE_FRAME")
    label = re.sub(
        r"<geom:Coordinate_Space_Index>\s*<geom:index_id>DRIVE</geom:index_id>.*?</geom:Coordinate_Space_Index>",
        "",
        label,
        flags=re.S,
    )
    result = read_pds4(label)
    assert (result.site, result.drive, result.frame) == (3, 110, "SITE_FRAME")


def test_pds4_rejects_moving_sources():
    label = (FIXTURES / "perseverance.xml").read_text()
    with pytest.raises(ValueError, match="multiple"):
        read_pds4(label.replace("_n0030110ncam", "_n0030111ncam", 1))


def test_download_to_offline_catalog(tmp_path):
    label = (FIXTURES / "curiosity.lbl").read_text()
    label = label.replace("7703", "360").replace("977", "90")
    label = (
        label.replace("15406", "720")
        .replace("21.3979", "1.0")
        .replace("132.629", "46.0")
    )
    metadata = read_pds3(label)
    name = metadata.product_id
    pixels = np.arange(360 * 90, dtype=">i2").reshape(90, 360)
    payload = bytes(metadata.offset) + pixels.tobytes()
    responses = {
        MSL: '<a href="SOL00024/">sol</a>',
        MSL + "SOL00024/": f'<a href="{name}.LBL">label</a>',
        MSL + f"SOL00024/{name}.LBL": label,
        MSL + f"SOL00024/{name}.IMG": payload,
        PLACES: "frame,site,drive,planetocentric_latitude,longitude,elevation\nROVER,3,372,-4.5,137.4,-4500\n",
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=responses[str(req.url)])
        )
    ) as client:
        download(client, tmp_path / "sources", "curiosity", limit=1)
    output = tmp_path / "derived"
    color_catalog = output / "curiosity" / "catalog.json"
    color_catalog.parent.mkdir(parents=True)
    color_catalog.write_text('{"panoramas": [{"id": "color-mastcam"}]}')
    entries = process(tmp_path / "sources", output, "curiosity", width=256)
    assert len(entries) == 1
    assert entries[0]["metadata"].startswith("curiosity-navcam/")
    assert entries[0]["sphere_ready"]
    assert (
        json.loads(color_catalog.read_text())["panoramas"][0]["id"] == "color-mastcam"
    )
    generated = json.loads((output / entries[0]["metadata"]).read_text())
    assert generated["position"]["latitude"] == -4.5
    assert generated["north_azimuth_offset_deg"] == 0
    assert 0.4 < generated["coverage_fraction"] < 0.6
    assert generated["sources"]["image_sha256"]
    (tmp_path / "sources" / "curiosity" / "images" / (name + ".IMG")).write_bytes(
        b"corrupt"
    )
    with pytest.raises(ValueError, match="checksum"):
        process(tmp_path / "sources", output, "curiosity", width=256)


def strip_constants(label: str) -> str:
    return re.sub(r"^\s*(?:INVALID|MISSING)_CONSTANT.*\n", "", label, flags=re.M)


def test_constants_fall_back_to_attached_header():
    label = (FIXTURES / "curiosity.lbl").read_text()
    assert read_pds3(label).missing == (0.0, 0.0)
    assert read_pds3(strip_constants(label)).missing == ()
    assert attached_constants(
        "NL=1 MISSING_CONSTANT=0.0 INVALID_CONSTANT=-1.5 NS=2"
    ) == (
        0.0,
        -1.5,
    )
    with pytest.raises(ValueError, match="attached header"):
        attached_constants("NL=1 PDS_MISSING_CONSTANT=0.0 INVALID_CONSTANT=0.0")


def offline_navcam(sols, label_text, payload_prefix=b""):
    """Serve one cylindrical Curiosity mosaic per requested sol."""
    metadata = read_pds3(label_text)
    name = metadata.product_id
    payload = (
        payload_prefix.ljust(metadata.offset, b"\0")
        + np.arange(360 * 90, dtype=">i2").reshape(90, 360).tobytes()
    )
    responses: dict[str, str | bytes] = {
        MSL: "".join(f'<a href="SOL{sol:05}/">sol</a>' for sol in sols),
        PLACES: "frame,site,drive,planetocentric_latitude,longitude,elevation\n"
        "ROVER,3,372,-4.5,137.4,-4500\n",
    }
    for sol in sols:
        label = label_text.replace(
            "PLANET_DAY_NUMBER               = 24",
            f"PLANET_DAY_NUMBER               = {sol}",
        )
        product = name.replace("_0024_", f"_{sol:04}_")
        label = label.replace(name, product)
        responses[MSL + f"SOL{sol:05}/"] = f'<a href="{product}.LBL">label</a>'
        responses[MSL + f"SOL{sol:05}/{product}.LBL"] = label
        responses[MSL + f"SOL{sol:05}/{product}.IMG"] = payload
    return responses


def test_attached_constants_admit_later_navcam_mosaics(tmp_path):
    label = (FIXTURES / "curiosity.lbl").read_text()
    label = label.replace("7703", "360").replace("977", "90")
    label = (
        label.replace("15406", "720")
        .replace("21.3979", "1.0")
        .replace("132.629", "46.0")
    )
    responses = offline_navcam(
        [24], strip_constants(label), b"MISSING_CONSTANT=0.0 INVALID_CONSTANT=0.0 "
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=responses[str(req.url)])
        )
    ) as client:
        products = download(client, tmp_path / "sources", "curiosity")
    assert products[0]["mosaic"]["missing"] == (0.0, 0.0)

    bare = offline_navcam([24], strip_constants(label))
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=bare[str(req.url)])
        )
    ) as client:
        with pytest.raises(ValueError, match="No supported"):
            download(client, tmp_path / "bare", "curiosity")


def test_sol_step_spreads_a_bounded_selection(tmp_path):
    label = (FIXTURES / "curiosity.lbl").read_text()
    label = label.replace("7703", "360").replace("977", "90")
    label = (
        label.replace("15406", "720")
        .replace("21.3979", "1.0")
        .replace("132.629", "46.0")
    )
    responses = offline_navcam([24, 30, 44], label)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=responses[str(req.url)])
        )
    ) as client:
        products = download(client, tmp_path / "sources", "curiosity", sol_step=20)
    assert [product["mosaic"]["sol"] for product in products] == [24, 44]
