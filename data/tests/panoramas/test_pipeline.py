from dataclasses import replace
import json
from pathlib import Path
import re

import httpx
import numpy as np
import pytest

from space_map_data.panoramas import pipeline
from space_map_data.panoramas.labels import (
    Mosaic,
    attached_constants,
    read_pds3,
    read_pds4,
)
from space_map_data.panoramas.pipeline import (
    coordinate_grid_dn,
    download,
    fetch,
    positions,
    process,
    read_pixels,
    remove_coordinate_grid,
    remove_coordinate_label_borders,
    sphere_texture,
    coverage,
    m20_mosaic_listings,
    m20_version,
    M20,
    M20_INVENTORY,
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
    header = b"GRID='GRID_OVERLAY' GRID_DN=10000.0"
    pixels = (np.arange(3 * 360) % 2000 + 1000).astype(">i2").reshape(1, 3, 360)
    pixels[0, 1, 90:270] = 10000
    pixels[0, 0, 0] = 4096
    path.write_bytes(header + pixels.tobytes())

    rgba, _ = read_pixels(path, mosaic(height=3, offset=len(header)))

    assert rgba[1, 90:270, 3].all()
    assert not np.all(rgba[1, 90:270, :3] == 255)
    assert rgba[1, :90, 3].all()
    assert rgba[1, 270:, 3].all()
    assert rgba[0, 0, 3] == 255


def test_coordinate_grid_declaration_requires_value():
    assert coordinate_grid_dn("GRID='NOGRID'") is None
    assert coordinate_grid_dn("") is None
    assert coordinate_grid_dn("GRID='GRID_OVERLAY'") == pipeline.GRID_BLACK_DN


def test_an_overlay_without_a_value_is_declared_to_remain():
    """Only its black labels come out, so the product must not read as clean."""
    assert pipeline.coordinate_grid_remains("GRID='GRID_OVERLAY'")
    assert not pipeline.coordinate_grid_remains("GRID='GRID'  GRID_DN=15000")
    assert not pipeline.coordinate_grid_remains("GRID='GRID_LABELS'")
    assert not pipeline.coordinate_grid_remains("GRID='NOGRID'")


def test_every_archive_spelling_of_the_overlay_is_removed():
    """Mars Exploration Rover mosaics call it GRID, and may draw labels alone."""
    assert coordinate_grid_dn("GRID='GRID'  GRID_DN=15000") == 15000
    assert coordinate_grid_dn("GRID='GRID_LABELS'") == pipeline.GRID_BLACK_DN
    with pytest.raises(ValueError, match="Unrecognized coordinate overlay"):
        coordinate_grid_dn("GRID='HALFGRID'")


def test_coordinate_grid_does_not_extend_into_missing_canvas():
    pixels = np.zeros((5, 5, 1), dtype=np.float32)
    pixels[0, 0] = 2000
    pixels[2, 2] = 10000
    valid = np.any(pixels != 0, axis=2)

    _, valid = remove_coordinate_grid(pixels, valid, 10000)

    assert valid[0, 0]
    assert not valid[2, 2]


def test_coordinate_label_borders_are_not_exported():
    pixels = np.full((200, 200, 1), 2000, dtype=np.float32)
    valid = np.ones((200, 200), dtype=bool)

    _, valid = remove_coordinate_label_borders(
        pixels, valid, mosaic(width=200, height=200)
    )

    assert not valid[:32].any()
    assert not valid[-32:].any()
    assert not valid[:, :48].any()
    assert not valid[:, -48:].any()
    assert valid[32:-32, 48:-48].all()


def test_full_panorama_bridges_only_its_labelled_seam():
    pixels = np.full((200, 360, 1), 2000, dtype=np.float32)
    valid = np.ones((200, 360), dtype=bool)
    valid[:, :8] = False
    valid[:, -8:] = False

    _, valid = remove_coordinate_label_borders(
        pixels, valid, mosaic(width=360, height=200)
    )

    assert valid[32:-32].all()
    assert not valid[:32].any()
    assert not valid[-32:].any()


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


def _offline_curiosity(tmp_path):
    """Download and process one small Curiosity mosaic from a mock archive."""
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
    return process(tmp_path / "sources", output, "curiosity", width=256), name


def test_download_to_offline_catalog(tmp_path):
    entries, name = _offline_curiosity(tmp_path)
    output = tmp_path / "derived"
    color_catalog = output / "curiosity" / "catalog.json"
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
    assert generated["source_coverage"]["frame_is_north_referenced"]
    (tmp_path / "sources" / "curiosity" / "images" / (name + ".IMG")).write_bytes(
        b"corrupt"
    )
    with pytest.raises(ValueError, match="checksum"):
        process(tmp_path / "sources", output, "curiosity", width=256)


def test_a_lander_frame_sphere_claims_no_heading(tmp_path, monkeypatch):
    """A site frame is referenced to north, so the sphere is already aligned. A
    lander frame is referenced to the lander, and no label ties it to north, so
    the export must be left to report the heading as unknown."""
    import space_map_data.panoramas.pipeline as module

    real = module.read_pds3
    monkeypatch.setattr(
        module, "read_pds3", lambda text: replace(real(text), frame="LANDER_FRAME")
    )
    entries, _ = _offline_curiosity(tmp_path)
    generated = json.loads((tmp_path / "derived" / entries[0]["metadata"]).read_text())

    assert generated["north_azimuth_offset_deg"] is None
    assert not generated["source_coverage"]["frame_is_north_referenced"]
    assert "north" not in generated["pixel_convention"]


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


def m20_inventory(*identifiers):
    return "".join(
        f"P,urn:nasa:pds:mars2020_navcam_ops_mosaic:data:{identifier}::1.0\n"
        for identifier in identifiers
    )


def test_perseverance_products_come_from_the_release_that_delivered_them(tmp_path):
    """A product is served by the first release directory that lists it."""
    early = "n_lrgb_0413_rzs_0220532_cyl_l_autogenj"
    late = "n_lrgb_1859_rzs_0880844_cyl_l_autogenj"
    published = {
        "cumulative": m20_inventory(early),
        # Releases 1-7 were folded into `cumulative`; the gap must not end discovery.
        "r8": m20_inventory(early),
        "r16": m20_inventory(early, late),
    }

    def respond(request):
        directory = str(request.url).removeprefix(M20).removesuffix("/" + M20_INVENTORY)
        if directory not in published:
            return httpx.Response(404)
        return httpx.Response(200, content=published[directory])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        groups = m20_mosaic_listings(client, tmp_path, refresh=False)
    assert groups[413] == [
        (
            M20
            + "cumulative/mars2020_navcam_ops_mosaic/data/sol/00413/ids/rdr/mosaic/",
            early.upper() + "01.xml",
        )
    ]
    assert groups[1859] == [
        (
            M20 + "r16/mars2020_navcam_ops_mosaic/data/sol/01859/ids/rdr/mosaic/",
            late.upper() + "01.xml",
        )
    ]


def test_perseverance_release_probe_retries_a_flaky_mirror(tmp_path, monkeypatch):
    """A 503 on the first release must not hand its products to a later one."""
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    early = "n_lrgb_0413_rzs_0220532_cyl_l_autogenj"
    published = {"cumulative": m20_inventory(), "r8": m20_inventory(early)}
    seen: list[str] = []

    def respond(request):
        directory = str(request.url).removeprefix(M20).removesuffix("/" + M20_INVENTORY)
        seen.append(directory)
        if directory == "r8" and seen.count("r8") == 1:
            return httpx.Response(503)
        if directory not in published:
            return httpx.Response(404)
        return httpx.Response(200, content=published[directory])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        groups = m20_mosaic_listings(client, tmp_path, refresh=False)
    assert groups[413][0][0].startswith(M20 + "r8/")


def test_perseverance_release_probe_gives_up_loudly(tmp_path, monkeypatch):
    """An unreadable release stops the download rather than skipping a release."""
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        with pytest.raises(httpx.HTTPError):
            m20_mosaic_listings(client, tmp_path, refresh=False)


def test_perseverance_version_field_carries_on_in_base_36():
    """Above 99 the two-character version field continues from A0, not 100."""
    assert m20_version("1.0") == "01"
    assert m20_version("99.0") == "99"
    assert m20_version("100.0") == "A0"
    # The three products the archive actually holds above 99.
    assert m20_version("212.0") == "D4"
    assert m20_version("269.0") == "EP"
    assert m20_version("280.0") == "F0"
    with pytest.raises(ValueError, match="two-character field"):
        m20_version("1036.0")
