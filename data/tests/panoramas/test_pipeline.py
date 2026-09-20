from dataclasses import replace
import json
from pathlib import Path
import re

import httpx
import numpy as np
import pytest

from space_map_data.panoramas import pipeline
from space_map_data.panoramas.labels import (
    describes_raster,
    Mosaic,
    attached_constants,
    read_pds3,
    read_pds4,
)
from space_map_data.panoramas.pipeline import (
    bracketed,
    coordinate_grid_dn,
    degrees_east,
    metres_apart,
    download,
    fetch,
    positions,
    process,
    resumable,
    revision_key,
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
    rgba, tone, _ = read_pixels(path, mosaic(height=3, offset=6))
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

    rgba, _, grid_remains = read_pixels(path, mosaic(height=3, offset=len(header)))

    assert rgba[1, 90:270, 3].all()
    assert not np.all(rgba[1, 90:270, :3] == 255)
    assert rgba[1, :90, 3].all()
    assert rgba[1, 270:, 3].all()
    assert rgba[0, 0, 3] == 255
    assert not grid_remains


def gridded_raster(path, header, grid_dn, *, every=10):
    """A 90-by-360 mosaic with an overlay of vertical lines `every` columns."""
    pixels = (np.arange(90 * 360) % 2000 + 1000).astype(">i2").reshape(1, 90, 360)
    pixels[0, :, ::every] = grid_dn
    path.write_bytes(header + pixels.tobytes())
    return mosaic(offset=len(header))


def test_an_undeclared_overlay_is_found_in_the_pixels_and_excluded(tmp_path):
    """Mars 2020 and Curiosity mosaics draw a grid at DN 4096 and say nothing."""
    path = tmp_path / "test.img"
    m = gridded_raster(path, b"TASK='MARSMAP'", 4096)

    rgba, _, grid_remains = read_pixels(path, m)

    assert not grid_remains
    assert not np.all(rgba[40, ::10, :3] == 255, axis=1).any()
    assert rgba[40, 5, 3] == 255


def test_an_overlay_declared_without_a_value_is_found_in_the_pixels(tmp_path):
    path = tmp_path / "test.img"
    m = gridded_raster(path, b"GRID='GRID_OVERLAY'", 15000)

    _, _, grid_remains = read_pixels(path, m)

    assert not grid_remains


def test_lines_at_no_regular_spacing_are_not_an_overlay(tmp_path):
    path = tmp_path / "test.img"
    m = gridded_raster(path, b"", 4096, every=7)

    rgba, _, grid_remains = read_pixels(path, m)

    assert not grid_remains
    assert np.all(rgba[40, ::7, :3] == 255, axis=1).all()


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
        download(client, tmp_path / "sources", "curiosity")
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
        process(tmp_path / "sources", output, "curiosity", width=256, rebuild=True)


def test_a_corrupt_source_behind_a_built_product_does_not_stop_a_resumed_run(tmp_path):
    """Only the bytes a run reads are worth a checksum; hashing the whole cache
    to skip what is already built costs a resumed run hours."""
    entries, name = _offline_curiosity(tmp_path)
    output = tmp_path / "derived"
    (tmp_path / "sources" / "curiosity" / "images" / (name + ".IMG")).write_bytes(
        b"corrupt"
    )

    assert process(tmp_path / "sources", output, "curiosity", width=256) == entries


def test_a_lander_frame_sphere_claims_no_heading(tmp_path, monkeypatch):
    """A site frame is referenced to north, so the sphere is already aligned. A
    lander frame is referenced to the lander, and no label ties it to north, so
    the export must be left to report the heading as unknown."""
    import space_map_data.panoramas.pipeline as module

    real = module.read_pds3
    monkeypatch.setattr(
        module,
        "read_pds3",
        lambda text, attached=None: replace(real(text, attached), frame="LANDER_FRAME"),
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


def test_one_unusable_mosaic_does_not_discard_the_run(tmp_path, monkeypatch):
    """A run writes its catalog only after its last product, so letting a bad
    mosaic raise would lose every good product with it."""
    import space_map_data.panoramas.pipeline as module

    real = module.read_pixels

    def explode(path, mosaic):
        raise ValueError("Mosaic has no displayable dynamic range")

    entries, name = _offline_curiosity(tmp_path)
    assert entries, "fixture must produce a product to then reject"

    monkeypatch.setattr(module, "read_pixels", explode)
    rebuilt = process(
        tmp_path / "sources", tmp_path / "derived", "curiosity", width=256, rebuild=True
    )

    assert rebuilt == []
    rejected = json.loads(
        (
            tmp_path / "derived" / "curiosity-navcam" / "processing-rejected.json"
        ).read_text()
    )
    assert [row["id"] for row in rejected] == [entries[0]["id"]]
    assert "dynamic range" in rejected[0]["reason"]
    monkeypatch.setattr(module, "read_pixels", real)


def test_catalog_rebuild_recovers_products_an_interrupted_run_left(tmp_path):
    """The export reads the index, so a product missing from it is invisible
    however complete it is on disk."""
    from space_map_data.panoramas.catalog import rebuild

    entries, _ = _offline_curiosity(tmp_path)
    derived = tmp_path / "derived"
    catalog = derived / "curiosity-navcam" / "catalog.json"
    truncated = json.loads(catalog.read_text())
    truncated["panoramas"] = []
    catalog.write_text(json.dumps(truncated))

    added, total = rebuild(derived, "curiosity-navcam")

    assert (added, total) == (len(entries), len(entries))
    recovered = json.loads(catalog.read_text())["panoramas"]
    assert {row["id"] for row in recovered} == {row["id"] for row in entries}
    assert all(row["sphere_ready"] for row in recovered)
    assert (derived / recovered[0]["metadata"]).is_file()


def test_a_second_run_keeps_what_it_would_only_rebuild(tmp_path, monkeypatch):
    """Reprocessing a whole mission to reach the products it has not built yet
    costs hours, so a resumed run repeats nothing."""
    import space_map_data.panoramas.pipeline as module

    entries, _ = _offline_curiosity(tmp_path)
    texture = (
        tmp_path / "derived" / "curiosity-navcam" / entries[0]["id"] / "panorama.webp"
    )
    stamp = texture.stat().st_mtime_ns

    def refuse(*args, **kwargs):
        raise AssertionError("an already-built panorama must not be built again")

    monkeypatch.setattr(module, "read_pixels", refuse)
    again = process(tmp_path / "sources", tmp_path / "derived", "curiosity", width=256)

    assert [row["id"] for row in again] == [row["id"] for row in entries]
    assert texture.stat().st_mtime_ns == stamp


def test_a_changed_recipe_discards_what_the_old_one_built(tmp_path, monkeypatch):
    """Half one recipe and half another is worse than rebuilding: the run must
    not leave textures its own metadata no longer describes."""
    import space_map_data.panoramas.pipeline as module

    entries, _ = _offline_curiosity(tmp_path)
    built = tmp_path / "derived" / "curiosity-navcam" / entries[0]["id"]
    (built / "stale-from-the-old-recipe.webp").write_bytes(b"stale")
    monkeypatch.setattr(module, "BUILD_VERSION", module.BUILD_VERSION + 1)

    again = process(tmp_path / "sources", tmp_path / "derived", "curiosity", width=256)

    assert [row["id"] for row in again] == [row["id"] for row in entries]
    assert not (built / "stale-from-the-old-recipe.webp").exists()
    rebuilt = json.loads((built / "metadata.json").read_text())
    assert rebuilt["build_version"] == module.BUILD_VERSION


def test_a_different_width_is_a_different_product(tmp_path):
    """The texture width is baked into the sphere, so a run asking for another
    one must not be handed the old size."""
    entries, _ = _offline_curiosity(tmp_path)
    built = tmp_path / "derived" / "curiosity-navcam" / entries[0]["id"]

    process(tmp_path / "sources", tmp_path / "derived", "curiosity", width=512)

    assert json.loads((built / "metadata.json").read_text())["width"] == 512


def test_rebuild_forces_a_fresh_build(tmp_path):
    """The escape hatch for a change the build version did not capture."""
    entries, _ = _offline_curiosity(tmp_path)
    built = tmp_path / "derived" / "curiosity-navcam" / entries[0]["id"]
    (built / "panorama.webp").write_bytes(b"clobbered")

    process(
        tmp_path / "sources", tmp_path / "derived", "curiosity", width=256, rebuild=True
    )

    assert (built / "panorama.webp").read_bytes() != b"clobbered"


def navcam_responses():
    """Three sols of servable Curiosity mosaics, one product each."""
    label = (FIXTURES / "curiosity.lbl").read_text()
    label = label.replace("7703", "360").replace("977", "90")
    label = (
        label.replace("15406", "720")
        .replace("21.3979", "1.0")
        .replace("132.629", "46.0")
    )
    return offline_navcam([24, 30, 44], label)


def counting_client(responses, fail_on=None):
    """A client that records every URL it serves, and may refuse one."""
    served = []

    def handle(request):
        url = str(request.url)
        served.append(url)
        if fail_on is not None and fail_on in url:
            raise httpx.ConnectError("interrupted")
        return httpx.Response(200, content=responses[url])

    return httpx.Client(transport=httpx.MockTransport(handle)), served


def test_an_interrupted_download_keeps_the_products_it_had_validated(tmp_path):
    """A run rewrites its selection from the first sol, so one that stops early
    must not leave an index naming less than it downloaded."""
    responses = navcam_responses()
    client, _ = counting_client(responses, fail_on="SOL00044")
    with client, pytest.raises(httpx.ConnectError):
        download(client, tmp_path / "sources", "curiosity")

    selection = json.loads(
        (tmp_path / "sources" / "curiosity" / "selection.json").read_text()
    )

    assert selection["complete"] is False
    assert [p["mosaic"]["sol"] for p in selection["products"]] == [24, 30]


def test_a_resumed_download_refetches_nothing_it_already_holds(tmp_path):
    responses = navcam_responses()
    client, _ = counting_client(responses, fail_on="SOL00044")
    with client, pytest.raises(httpx.ConnectError):
        download(client, tmp_path / "sources", "curiosity")

    client, served = counting_client(responses)
    with client:
        products = download(client, tmp_path / "sources", "curiosity")

    assert [product["mosaic"]["sol"] for product in products] == [24, 30, 44]
    # The two sols the first run validated cost nothing the second time round.
    assert not [url for url in served if "SOL00024" in url or "SOL00030" in url]
    selection = json.loads(
        (tmp_path / "sources" / "curiosity" / "selection.json").read_text()
    )
    assert selection["complete"] is True


class TestARunOverPartOfTheMission:
    """A sol range bounds what a run looks at again, not what the index holds.

    Curiosity lost four months of coverage to the opposite behaviour: a bounded
    run rewrote the index to name only its own sols, and the processing stage
    reads the index.
    """

    def full(self, tmp_path):
        client, _ = counting_client(navcam_responses())
        with client:
            download(client, tmp_path / "sources", "curiosity")
        return tmp_path / "sources" / "curiosity" / "selection.json"

    def test_the_sols_it_never_looked_at_stay_in_the_index(self, tmp_path):
        self.full(tmp_path)

        client, _ = counting_client(navcam_responses())
        with client:
            products = download(client, tmp_path / "sources", "curiosity", start_sol=30)

        assert [product["mosaic"]["sol"] for product in products] == [24, 30, 44]

    def test_it_asks_the_archive_only_about_the_sols_it_bounds(self, tmp_path):
        self.full(tmp_path)

        client, served = counting_client(navcam_responses())
        with client:
            download(client, tmp_path / "sources", "curiosity", start_sol=30)

        assert not [url for url in served if "SOL00024" in url]

    def test_it_inherits_the_completeness_it_did_not_re_establish(self, tmp_path):
        path = self.full(tmp_path)

        client, _ = counting_client(navcam_responses())
        with client:
            download(client, tmp_path / "sources", "curiosity", start_sol=30)

        assert json.loads(path.read_text())["complete"] is True

    def test_a_refreshed_run_still_keeps_the_sols_it_was_bounded_away_from(
        self, tmp_path
    ):
        """Refreshing re-fetches what a run walks; it does not empty the rest."""
        self.full(tmp_path)

        client, _ = counting_client(navcam_responses())
        with client:
            products = download(
                client,
                tmp_path / "sources",
                "curiosity",
                start_sol=30,
                refresh=True,
            )

        assert [product["mosaic"]["sol"] for product in products] == [24, 30, 44]

    def test_a_product_the_archive_drops_inside_the_range_is_not_kept(self, tmp_path):
        """Only the sols a run is bounded away from speak for themselves. One it
        walks states what is there now, so a withdrawn product goes.

        Refreshed because the caches would otherwise answer for the archive:
        the sol index and the label are both already on disk.
        """
        self.full(tmp_path)
        thinner = {
            url: body
            for url, body in navcam_responses().items()
            if "SOL00030" not in url
        }
        thinner[MSL] = thinner[MSL].replace('<a href="SOL00030/">sol</a>', "")

        client, _ = counting_client(thinner)
        with client:
            products = download(
                client,
                tmp_path / "sources",
                "curiosity",
                start_sol=30,
                refresh=True,
            )

        assert [product["mosaic"]["sol"] for product in products] == [24, 44]

    def test_a_bounded_run_with_nothing_before_it_claims_nothing(self, tmp_path):
        client, _ = counting_client(navcam_responses())
        with client:
            download(client, tmp_path / "sources", "curiosity", start_sol=30)

        selection = json.loads(
            (tmp_path / "sources" / "curiosity" / "selection.json").read_text()
        )
        assert selection["complete"] is False
        assert [p["mosaic"]["sol"] for p in selection["products"]] == [30, 44]


def test_a_selection_an_older_recipe_chose_is_not_resumed():
    """A recipe that would now accept different products must not inherit the
    products the old one accepted."""
    carried = {"label_url": "https://example.invalid/x.LBL"}

    assert resumable(
        {
            "selection_version": pipeline.SELECTION_VERSION,
            "products": [carried],
        }
    ) == {carried["label_url"]: carried}
    assert not resumable({"selection_version": 0, "products": [carried]})
    # A selection written before the recipe was versioned states nothing.
    assert not resumable({"products": [carried]})


def test_refresh_revalidates_rather_than_resuming(tmp_path):
    responses = navcam_responses()
    client, _ = counting_client(responses, fail_on="SOL00044")
    with client, pytest.raises(httpx.ConnectError):
        download(client, tmp_path / "sources", "curiosity")

    client, _ = counting_client(responses)
    with client:
        products = download(client, tmp_path / "sources", "curiosity", refresh=True)

    assert [product["mosaic"]["sol"] for product in products] == [24, 30, 44]


class TestBracketedPositions:
    """A stop the localization table skips still lies between the ones it
    records, which places the mosaic and states how wrong that can be."""

    LOOKUP = {
        (2, 4): {"latitude": -1.0, "longitude": 354.0, "elevation_m": -1000.0},
        (2, 8): {"latitude": -1.0, "longitude": 354.002, "elevation_m": -1010.0},
        (3, 6): {"latitude": -1.5, "longitude": 355.0, "elevation_m": None},
    }

    def bracket(self, counter):
        return bracketed(self.LOOKUP, sorted(self.LOOKUP), counter)

    def test_an_unrecorded_drive_is_placed_between_its_neighbours(self):
        found = self.bracket((2, 6))

        assert found["latitude"] == pytest.approx(-1.0)
        assert found["longitude"] == pytest.approx(354.001)
        assert found["elevation_m"] == pytest.approx(-1005.0)

    def test_the_bound_is_half_what_separates_the_neighbours(self):
        """The camera stood somewhere between the two, so the midpoint is
        wrong by at most half their separation."""
        found = self.bracket((2, 6))
        span = metres_apart(self.LOOKUP[(2, 4)], self.LOOKUP[(2, 8)])

        assert found["uncertainty_m"] == pytest.approx(round(span / 2, 1))
        assert found["position_bounds"]["separation_m"] == pytest.approx(round(span, 1))
        assert found["position_bounds"]["between_site_drive"] == [[2, 4], [2, 8]]

    def test_a_site_change_brackets_across_it(self):
        """Drive 0 of a new site is the moment the counter reset, which the
        tables never record and the stops either side still enclose."""
        found = self.bracket((3, 0))

        assert found["position_bounds"]["between_site_drive"] == [[2, 8], [3, 6]]

    def test_an_unknown_elevation_stays_unknown(self):
        assert self.bracket((3, 0))["elevation_m"] is None

    def test_a_stop_outside_the_traverse_is_not_placed(self):
        """Before the first recorded stop or after the last, nothing encloses it."""
        assert self.bracket((2, 1)) is None
        assert self.bracket((4, 0)) is None

    def test_a_traverse_across_the_prime_meridian_does_not_go_the_long_way(self):
        """Opportunity landed at 354 degrees east and drove past zero, so two
        stops metres apart can be written 359 degrees apart."""
        lookup = {
            (1, 0): {"latitude": -2.0, "longitude": 359.999, "elevation_m": None},
            (1, 4): {"latitude": -2.0, "longitude": 0.001, "elevation_m": None},
        }
        found = bracketed(lookup, sorted(lookup), (1, 2))

        assert found is not None
        assert found["longitude"] == pytest.approx(0.0)
        assert found["uncertainty_m"] < 60
        assert degrees_east(359.999, 0.001) == pytest.approx(0.002)


class TestPlacingAStopTheTableSkips:
    """A localization table records the drives it was corrected for, not every
    drive the rover made, and a mosaic naming one of the others is still on the
    traverse between the recorded stops either side."""

    def served(self, table_rows):
        label = (FIXTURES / "curiosity.lbl").read_text()
        label = label.replace("7703", "360").replace("977", "90")
        label = (
            label.replace("15406", "720")
            .replace("21.3979", "1.0")
            .replace("132.629", "46.0")
        )
        responses = offline_navcam([24], label)
        responses[PLACES] = (
            "frame,site,drive,planetocentric_latitude,longitude,elevation\n"
            + table_rows
        )
        return responses

    def download(self, tmp_path, table_rows):
        responses = self.served(table_rows)
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, content=responses[str(req.url)])
            )
        ) as client:
            return download(client, tmp_path / "sources", "curiosity")

    def test_a_skipped_drive_is_placed_between_the_recorded_stops(self, tmp_path):
        products = self.download(
            tmp_path,
            "ROVER,3,370,-4.5,137.4,-4500\nROVER,3,374,-4.5,137.5,-4600\n",
        )
        position = products[0]["position"]

        assert position["latitude"] == pytest.approx(-4.5)
        assert position["longitude"] == pytest.approx(137.45)
        assert position["uncertainty_m"] == pytest.approx(2954.6, abs=1)
        assert position["position_bounds"]["between_site_drive"] == [[3, 370], [3, 374]]

    def test_an_exactly_recorded_stop_states_no_uncertainty(self, tmp_path):
        products = self.download(tmp_path, "ROVER,3,372,-4.5,137.4,-4500\n")

        assert products[0]["position"] == {
            "latitude": -4.5,
            "longitude": 137.4,
            "elevation_m": -4500.0,
        }

    def test_a_stop_the_traverse_never_reaches_is_still_refused(self, tmp_path):
        """Nothing encloses a drive past the last the table records, so there
        is no range to state and the product is not taken."""
        with pytest.raises(ValueError, match="No supported localized panoramas"):
            self.download(tmp_path, "ROVER,3,300,-4.5,137.4,-4500\n")


class TestProductIdentity:
    """A mosaic must be the one its name promised, but the Mars Exploration
    Rover volume redelivers a sweep under a later version than the label
    inside it carries."""

    def test_a_later_delivery_of_the_same_sweep_is_the_same_product(self):
        assert revision_key(
            "opportunity", "1PP002IFF02CYL00P2217R777M3"
        ) == revision_key("opportunity", "1PP002IFF02CYL00P2217R777M1")

    def test_a_different_sweep_is_not(self):
        assert revision_key(
            "opportunity", "1PP002IFF02CYL00P2217R777M1"
        ) != revision_key("opportunity", "1PP002IFF02CYL00P2218R777M1")

    def test_a_label_naming_a_campaign_rather_than_a_product_still_differs(self):
        """Some labels carry a scene name where the product id belongs, which
        confirms nothing about what was served."""
        assert revision_key("spirit", "santa_anita_iff_R7") != revision_key(
            "spirit", "2PP136IFF54CYLCAP2264R222M2"
        )


class TestALabelThatOnlyPointsAtItsRaster:
    """From sol 4712 the Curiosity volume stopped repeating the raster
    description in the detached label, leaving it only inside the raster."""

    def split(self):
        label = (FIXTURES / "curiosity.lbl").read_text()
        raster = re.search(
            r"^\s*OBJECT\s*=\s*IMAGE\s*$[\s\S]*?^\s*END_OBJECT\s*=\s*IMAGE\s*$",
            label,
            re.M,
        )
        assert raster
        return label[: raster.start()] + label[raster.end() :], raster[0]

    def test_a_detached_label_alone_no_longer_describes_the_raster(self):
        detached, _ = self.split()

        assert not describes_raster(detached)
        assert describes_raster((FIXTURES / "curiosity.lbl").read_text())

    def test_the_raster_is_read_from_the_label_attached_to_it(self):
        detached, attached = self.split()
        whole = read_pds3((FIXTURES / "curiosity.lbl").read_text())

        split = read_pds3(detached, attached)

        assert (split.width, split.height, split.dtype) == (
            whole.width,
            whole.height,
            whole.dtype,
        )
        assert split.product_id == whole.product_id
        assert split.missing == whole.missing

    def test_a_split_label_without_its_raster_half_is_still_refused(self):
        detached, _ = self.split()

        with pytest.raises(ValueError, match="Missing PDS block: IMAGE"):
            read_pds3(detached)
