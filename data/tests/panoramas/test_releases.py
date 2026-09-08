import json

import httpx
import pytest

from space_map_data.panoramas.releases import (
    API,
    FULL_POLICY,
    POLICY,
    discover_mastcam,
    mastcam_assets,
    timeline_select,
)


def post(html, title="Sol 15: Heli Airfield Mosaic"):
    return {
        "link": "https://mastcamz.asu.edu/galleries/example/",
        "date": "2026-08-01",
        "title": {"rendered": title},
        "content": {"rendered": html},
    }


def asset(eye="L0", color="NN", projection="CYL", revision="01"):
    return f"https://mcz-images.sese.asu.edu/zcam_mosaics/CZCAM_SOL0015_ZCAM07000_Z110_{eye}_{color}_SCI_{projection}_HELI_AIRFIELD_{revision}.png"


def test_color_variants_not_extra_scenes():
    html = "".join(
        f'<a href="{url}">PNG</a>'
        for url in (
            asset(),
            asset("R0"),
            asset(color="EE"),
            asset(color="AB"),
            asset(projection="VERT"),
            asset("L1"),
        )
    )
    result = mastcam_assets(post(html))
    assert len(result) == 1
    assert len(result[0]["variants"]) == 3
    assert result[0]["coverage"]["sphere_percent"] is None
    assert result[0]["capture_time"] is None
    assert result[0]["publication_time"] == "2026-08-01"


def test_legacy_360_no_invented_vertical_bounds():
    url = "https://mcz-images.sese.asu.edu/Mastcam-Z_360_Butler_Landing_1_Sols03-11_L0_natural.png"
    result = mastcam_assets(post(f'<a href="{url}">Full resolution PNG</a>'))[0]
    assert result["coverage"]["horizontal_percent"] == 100
    assert result["coverage"]["sphere_percent"] is None
    assert result["sol"] == 3


def test_discovery_paginates_and_deduplicates(tmp_path):
    first = post(f'<a href="{asset()}">PNG</a>')
    second = post(f'<a href="{asset(revision="02")}">PNG</a>')
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if url in {POLICY, FULL_POLICY}:
            return httpx.Response(200, text="official policy")
        if url == API + "gallery?per_page=100":
            return httpx.Response(200, json=[{"id": 43, "slug": "panoramas-mosaics"}])
        return httpx.Response(
            200, json=[second] if url.endswith("page=2") else [first] * 100
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = discover_mastcam(client, tmp_path)
    assert result["source_post_count"] == 101
    assert len(result["products"]) == 1
    assert result["products"][0]["selected_url"] == asset(revision="02")
    assert any(url.endswith("page=2") for url in calls)
    assert json.loads((tmp_path / "mastcamz/inventory.json").read_text())[
        "discovery_complete"
    ]


def test_timeline_endpoints_cadence_and_events():
    rows = [
        {
            "id": str(year),
            "capture_time": f"{year}-01-01",
            "interesting_reasons": ["dust cleaning"] if year == 2021 else [],
        }
        for year in range(2018, 2024)
    ]
    rows.append({"id": "unknown", "publication_time": "2020-01-01"})
    selected, undated = timeline_select(rows)
    assert [row["id"] for row in selected] == ["2018", "2020", "2021", "2022", "2023"]
    assert undated[0]["id"] == "unknown"
    assert selected[0]["timeline_reasons"] == ["first"]
    assert selected[-1]["timeline_reasons"] == ["last"]
    with pytest.raises(ValueError):
        timeline_select(rows, years=0)


def test_single_timeline_frame_is_both_endpoints():
    result, _ = timeline_select([{"id": "one", "capture_time": "2020-02-29"}])
    assert result[0]["timeline_reasons"] == ["first", "last"]


def test_geographic_spirit_names_do_not_assign_the_rover():
    from space_map_data.panoramas.nasa_releases import rover_in_caption

    assert (
        rover_in_caption(
            "Spirit of St. Louis crater was imaged by Mars Exploration Rover Opportunity."
        )
        == "opportunity"
    )
    assert (
        rover_in_caption("NASA's Curiosity Mars rover captured this panorama.")
        == "curiosity"
    )
    assert (
        rover_in_caption("NASA’s Curiosity captured this Mastcam panorama.")
        == "curiosity"
    )


def test_curated_masters_bypass_thumbnail_transform(tmp_path):
    from space_map_data.panoramas.nasa_releases import CURATED_MASTCAM, curated_mastcam

    def respond(request):
        item = next(row for row in CURATED_MASTCAM if row[1] in str(request.url))
        return httpx.Response(
            200,
            text=f'<h1>Panorama</h1><p>NASA/JPL-Caltech/MSSS</p><a href="https://assets.science.nasa.gov/dynamicimage/assets/{item[2]}?w=150">Download</a>',
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        rows = curated_mastcam(client, tmp_path)
    assert len(rows) == 2
    assert (
        rows[0]["selected_url"]
        == "https://assets.science.nasa.gov/assets/PIA23623_hires.tif"
    )
    assert rows[1]["coverage"]["sphere_percent"] is None
    assert rows[1]["capture_time"] == "2025-11-09"


def test_preview_regenerated_when_master_changes(tmp_path):
    from PIL import Image
    from space_map_data.panoramas.pipeline import sha256, write_json
    from space_map_data.panoramas.releases import process_releases

    root, output = tmp_path / "sources", tmp_path / "derived"
    source = root / "curiosity" / "image.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (20, 10), (210, 80, 20)).save(source)
    write_json(
        source.parent / "inventory.json",
        {"products": [{"id": "test", "sol": 1, "title": "Color test"}]},
    )
    write_json(
        source.parent / "downloads.json",
        {
            "products": {
                "test": {
                    "status": "downloaded",
                    "path": "image.png",
                    "sha256": sha256(source),
                    "width": 20,
                    "height": 10,
                }
            }
        },
    )
    target = output / "curiosity" / "test"
    target.mkdir(parents=True)
    Image.new("RGB", (4, 4), (20, 80, 210)).save(target / "preview.webp")
    write_json(target / "metadata.json", {"source_sha256": "old-master"})
    assert len(process_releases(root, output, "curiosity")) == 1
    with Image.open(target / "preview.webp") as preview:
        assert preview.size == (20, 10)


def test_pancam_preserves_multiple_scenes_and_excludes_monochrome():
    from space_map_data.panoramas.pancam import color_assets

    html = "<p>NASA/JPL/Cornell/ASU</p>" + "".join(
        f'<p><a href="images/{name}">JPG</a></p>'
        for name in [
            "Sol100A_P100_L257atc.jpg",
            "Sol100A_P100_L257F.jpg",
            "Sol110A_P200_L257atc.jpg",
            "Sol110A_P200_L2_lmono.jpg",
            "Sol110A_P200_L257_vp.jpg",
        ]
    )
    rows = color_assets(
        html,
        {
            "mission": "spirit",
            "url": "https://pancam.sese.asu.edu/projects_6.html",
            "caption": "Multiple views",
            "full": False,
        },
    )
    assert len(rows) == 2
    assert {row["sol"] for row in rows} == {100, 110}
    assert len(rows[0]["variants"]) == 2
    assert all(row["coverage"]["sphere_percent"] is None for row in rows)


def test_grid_regression_handles_north_wrap_and_rejects_sparse_evidence():
    from space_map_data.panoramas.grid_geometry import fit_axis

    slope, origin, count = fit_axis(
        [(0, 340), (100, 350), (200, 0), (300, 10), (400, 20), (500, 30)],
        600,
        circular=True,
    )
    assert slope == pytest.approx(0.1)
    assert origin % 360 == pytest.approx(340)
    assert count == 6
    with pytest.raises(ValueError):
        fit_axis([(0, 0), (0, 0), (300, -10), (300, -10)], 400)


def test_pancam_caption_overrides_360_gallery_category():
    from space_map_data.panoramas.pancam import color_assets

    rows = color_assets(
        '<title>Bonneville</title><p>This 180-degree, false-color mosaic shows the crater.</p><p>Image credit: NASA/JPL/Cornell</p><a href="images/Sol123A_P200.jpg">Full Size JPG</a>',
        {
            "mission": "spirit",
            "url": "https://pancam.sese.asu.edu/bonneville.html",
            "caption": "Sol 123",
            "full": True,
        },
    )
    assert rows[0]["coverage"]["horizontal_degrees"] == 180
    assert "sol123a" in rows[0]["id"]


def test_exact_observation_frame_localization():
    from space_map_data.panoramas.localize import common_position, frame_counters

    rows = [
        {"title": {"rendered": title}}
        for title in [
            "ZL0 0015 0668279408 290RAD N0030376ZCAM07000 110085F",
            "ZR0 0015 0668279408 290RAD N0030376ZCAM07000 110085F",
            "ZL0 0016 0668279408 290RAD N0030999ZCAM07000 110085F",
            "ZL0 0015 0668279408 290RAD N0030999ZCAM07001 110085F",
        ]
    ]
    counters = frame_counters(rows, 15, "ZCAM07000")
    assert counters == {(3, 376)}
    location = {"latitude": 18.4, "longitude": 77.4, "elevation_m": -2500}
    assert common_position(counters, {(3, 376): location}) == location
    with pytest.raises(ValueError, match="Missing exact"):
        common_position(counters, {})
    with pytest.raises(ValueError, match="multiple"):
        common_position(
            {(3, 376), (3, 999)},
            {(3, 376): location, (3, 999): {**location, "latitude": 19}},
        )
