import json
import logging
import sys

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.extrasolar import __main__ as cli_module
from space_map_data.extrasolar import engine, ids, sky
from space_map_data.extrasolar.engine import IngestRun, Source
from space_map_data.extrasolar.registry import Registry, RegistryError
from tests.extrasolar.conftest import (
    GAIA,
    HIP,
    META,
    NAMES,
    POINT,
    centre,
    claim,
    gaia_rows,
    hip_rows,
    id_of,
    name_rows,
    offset,
    straddle,
    table_rows,
)

CELL = 5_000_123
RA, DEC = centre(CELL)


def near(arcsec: float, angle: float = 0.0) -> tuple[float, float]:
    return offset(RA, DEC, arcsec, angle)


def star(id_, arcsec=0.0, angle=0.0, **more) -> dict:
    ra, dec = near(arcsec, angle)
    return {"id": id_, "ra": ra, "dec": dec, **more}


def by_id(table: pa.Table) -> dict[int, dict]:
    return {row["id"]: row for row in table.to_pylist()}


class TestFirstIngest:
    """Serials, determinism and reruns."""

    def test_brightest_first_ties_by_catalogue_id(self, root, ingest):
        rows = gaia_rows(
            [
                star(500, 1, 0, mag=12.0),
                star(10, 2, 90, mag=8.0),
                star(9, 3, 180, mag=8.0),
                star(77, 4, 270, mag=None),
                star(3, 5, 45, mag=10.0),
            ]
        )
        result = ingest([(GAIA, rows)])
        assert result.entry["counts"]["minted"] == 5
        serials = {
            gid: ids.decode(id_of(root, GAIA, gid)) for gid in (500, 10, 9, 77, 3)
        }
        assert {key: value[1:] for key, value in serials.items()} == {
            key: (1, CELL) for key in serials
        }
        # 9 sorts before 10 as a number; a missing magnitude goes last.
        assert [serials[g][0] for g in (9, 10, 3, 500, 77)] == [0, 1, 2, 3, 4]

    def test_same_ids_from_another_registry_and_batch_order(self, tmp_path, ingest):
        stars = [star(i, i * 0.7, i * 37, mag=float(i % 5)) for i in range(1, 40)]
        ingest([(GAIA, gaia_rows(stars))])
        first = table_rows(tmp_path / "registry-root", "point")

        other = tmp_path / "other"
        with IngestRun.start(other, tmp_path / "other-backup", (POINT,), META) as run:
            shuffled = stars[::-1]
            run.add(GAIA, [gaia_rows(shuffled[:10]), gaia_rows(shuffled[10:])])
            run.commit()
        second = table_rows(other, "point")
        assert first.sort_by("id").equals(second.sort_by("id"))

    def test_rerun_mints_nothing(self, root, registry, ingest):
        rows = gaia_rows([star(i, i, i * 50, mag=float(i)) for i in range(1, 6)])
        hip = hip_rows([star(1, 0.1, mag=1.1), star(99, 60, mag=3.0)])
        ingest([(GAIA, rows), (HIP, hip)])
        before = table_rows(root, "point").sort_by("id")
        result = ingest([(GAIA, rows), (HIP, hip)])
        counts = result.entry["counts"]
        assert (
            counts["minted"] == 0 and counts["merged"] == 0 and counts["retired"] == 0
        )
        assert result.entry["sources"][0]["by_id"] == 5
        assert result.entry["sources"][1]["by_id"] == 2
        registry = Registry(root)
        assert not registry.part_regions("ids") or all(
            not path.parent.parent.name.endswith("000002")
            for region in registry.part_regions("ids")
            for path in registry.part_files("ids", region)
        )
        assert table_rows(root, "point").sort_by("id").equals(before)

    def test_new_objects_take_the_next_serials(self, root, ingest):
        ingest([(GAIA, gaia_rows([star(1, 1, mag=5.0), star(2, 2, 90, mag=6.0)]))])
        rows = gaia_rows(
            [star(1, 1, mag=5.0), star(2, 2, 90, mag=6.0), star(3, 3, 180, mag=1.0)]
        )
        ingest([(GAIA, rows)])
        assert ids.serial_of(id_of(root, GAIA, 3)) == 2
        assert ids.serial_of(id_of(root, GAIA, 1)) == 0


class TestMatching:
    """Claims, positions, one-to-one matches and mint-only-if-matched."""

    def test_position_match_gives_one_id(self, root, ingest):
        result = ingest(
            [
                (GAIA, gaia_rows([star(1, mag=5.0, parallax=20.0)])),
                (HIP, hip_rows([star(7, 0.3, 40, mag=5.1, parallax=21.0)])),
            ]
        )
        assert result.entry["counts"]["minted"] == 1
        assert id_of(root, GAIA, 1) == id_of(root, HIP, 7) != 0
        row = by_id(table_rows(root, "point"))[id_of(root, GAIA, 1)]
        assert row["parallax"] == 20.0 and row["astrometry_source"] == "gaia"
        assert row["hp"] == pytest.approx(5.1)
        meta = by_id(table_rows(root, "metadata"))[id_of(root, GAIA, 1)]
        assert {c["catalogue"] for c in meta["cross_ids"]} == {"gaia", "hip"}
        assert meta["mask"] == 1 << 1 and meta["class_source"] == "gaia"

    def test_one_match_on_each_side(self, root, ingest):
        ingest(
            [
                (GAIA, gaia_rows([star(1, mag=5.0)])),
                (HIP, hip_rows([star(7, 0.2, mag=5.0), star(8, 0.6, 180, mag=5.0)])),
            ]
        )
        assert id_of(root, HIP, 7) == id_of(root, GAIA, 1)
        assert id_of(root, HIP, 8) not in (0, id_of(root, GAIA, 1))

    def test_far_rows_do_not_match(self, root, ingest):
        ingest(
            [
                (GAIA, gaia_rows([star(1, mag=5.0)])),
                (HIP, hip_rows([star(7, 20, mag=5.0)])),
            ]
        )
        assert id_of(root, HIP, 7) != id_of(root, GAIA, 1)

    def test_match_across_a_region_edge(self, root, ingest):
        (ra_a, dec_a), (ra_b, dec_b) = straddle(100)
        ingest(
            [
                (GAIA, gaia_rows([{"id": 1, "ra": ra_a, "dec": dec_a, "mag": 4.0}])),
                (HIP, hip_rows([{"id": 2, "ra": ra_b, "dec": dec_b, "mag": 4.0}])),
            ]
        )
        id_ = id_of(root, GAIA, 1)
        assert id_of(root, HIP, 2) == id_
        assert sky.region_of(ids.cell_of(id_)) == 100
        registry = Registry(root)
        point = registry.read_table("point", 100)
        assert point is not None and point["hp"].to_pylist() == [4.0]

    def test_mint_only_if_matched(self, root, ingest):
        flagged = gaia_rows(
            [star(1, mag=6.0, mint=False), star(2, 30, mag=7.0, mint=False)]
        )
        result = ingest([(GAIA, flagged)])
        assert result.entry["counts"]["minted"] == 0
        assert result.entry["counts"]["unminted"] == 2
        assert id_of(root, GAIA, 1) == 0

        hip = hip_rows(
            [
                star(5, 0.2, mag=6.1),
                star(6, 300, mag=1.0, claims=[claim("gaia", "dr3", 2)]),
            ]
        )
        result = ingest([(GAIA, flagged), (HIP, hip)])
        assert result.entry["counts"]["minted"] == 2
        assert id_of(root, GAIA, 1) == id_of(root, HIP, 5) != 0
        assert id_of(root, GAIA, 2) == id_of(root, HIP, 6) != 0
        # The object of a flagged Gaia source takes its cell and Gaia's values.
        gaia_2 = gaia_rows([star(2, 30, mag=7.0)])
        assert (
            ids.cell_of(id_of(root, GAIA, 2))
            == sky.cells(gaia_2["match_ra"].to_numpy(), gaia_2["match_dec"].to_numpy())[
                0
            ]
        )
        row = by_id(table_rows(root, "point"))[id_of(root, GAIA, 2)]
        assert row["astrometry_source"] == "gaia" and row["g"] == 7.0

    def test_claims_of_a_later_catalogue(self, root, ingest):
        gaia = gaia_rows([star(1, mag=3.0, claims=[claim("hip", "2007", 42)])])
        # Far apart, so only the claim links them.
        hip = hip_rows([star(42, 120, mag=3.0)])
        result = ingest([(GAIA, gaia), (HIP, hip)])
        assert result.entry["counts"]["minted"] == 1
        assert id_of(root, HIP, 42) == id_of(root, GAIA, 1)
        assert result.entry["sources"][1]["by_id"] == 1

    def test_a_missed_claim_blocks_a_position_match(self, root, ingest):
        gaia = gaia_rows([star(1, mag=5.0)])
        # Its own Gaia source is not in the input, so no object holds it.
        hip = hip_rows([star(7, 0.2, mag=5.0, claims=[claim("gaia", "dr3", 99)])])
        result = ingest([(GAIA, gaia), (HIP, hip)])
        assert result.entry["counts"]["minted"] == 2
        assert id_of(root, HIP, 7) not in (0, id_of(root, GAIA, 1))
        assert id_of(root, GAIA, 99) == id_of(root, HIP, 7)

    def test_small_caches_give_the_same_ids(self, tmp_path, monkeypatch, ingest):
        cells = [CELL + n * (1 << sky.REGION_SHIFT) for n in range(6)]
        gaia, hip = [], []
        for n, cell in enumerate(cells):
            ra, dec = centre(cell)
            gaia.append({"id": n, "ra": ra, "dec": dec, "mag": 5.0})
            ra, dec = offset(ra, dec, 0.2, 0)
            hip.append({"id": 100 + n, "ra": ra, "dec": dec, "mag": 5.0})
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip_rows(hip))])
        first = table_rows(tmp_path / "registry-root", "point").sort_by("id")

        monkeypatch.setattr(engine, "CACHE_ROWS", 1)
        other = tmp_path / "other"
        with IngestRun.start(other, tmp_path / "other-backup", (POINT,), META) as run:
            run.add(GAIA, [gaia_rows(gaia)])
            run.add(HIP, [hip_rows(hip)])
            result = run.commit()
        assert result.entry["sources"][1]["by_position"] == len(cells)
        assert table_rows(other, "point").sort_by("id").equals(first)

    def test_two_claims_on_one_object_conflict(self, root, ingest):
        gaia = gaia_rows([star(1, mag=3.0)])
        hip = hip_rows(
            [
                star(5, 100, mag=3.0, claims=[claim("gaia", "dr3", 1)]),
                star(6, 200, mag=3.0, claims=[claim("gaia", "dr3", 1)]),
            ]
        )
        result = ingest([(GAIA, gaia), (HIP, hip)])
        assert result.entry["counts"]["conflicts"] == 1
        assert id_of(root, HIP, 5) == id_of(root, GAIA, 1)
        assert id_of(root, HIP, 6) not in (0, id_of(root, GAIA, 1))

    def test_a_rejected_claim_does_not_join(self, root, ingest):
        gaia = gaia_rows([star(1, mag=3.0)])
        hip = hip_rows([star(7, 360, mag=4.0)])
        ra, dec = near(100)
        names = name_rows(
            [
                {
                    "id": "a-name",
                    "ra": ra,
                    "dec": dec,
                    "claims": [claim("gaia", "dr3", 1)],
                },
                {
                    "id": "b-name",
                    "ra": ra,
                    "dec": dec,
                    "claims": [claim("gaia", "dr3", 1), claim("hip", "2007", 7)],
                },
            ]
        )
        result = ingest([(GAIA, gaia), (HIP, hip), (NAMES, names)])
        counts = result.entry["counts"]
        assert (counts["minted"], counts["merged"], counts["conflicts"]) == (2, 0, 1)
        gaia_id, hip_id = id_of(root, GAIA, 1), id_of(root, HIP, 7)
        assert 0 not in (gaia_id, hip_id) and gaia_id != hip_id
        assert id_of(root, NAMES, "a-name") == gaia_id
        assert id_of(root, NAMES, "b-name") == hip_id
        meta = by_id(table_rows(root, "metadata"))
        assert meta[gaia_id]["name"] == "a-name" and meta[hip_id]["name"] == "b-name"
        assert {c["catalogue"] for c in meta[gaia_id]["cross_ids"]} == {"gaia", "iau"}

    def test_a_claim_of_an_object_taken_in_the_pass_does_not_join(self, root, ingest):
        gaia = gaia_rows([star(1, mag=3.0)])
        hip = hip_rows([star(7, 360, mag=4.0)])
        ra, dec = near(100)
        b_name: dict = {"id": "b-name", "ra": ra, "dec": dec}
        b_name["claims"] = [claim("gaia", "dr3", 1)]
        ingest([(GAIA, gaia), (HIP, hip), (NAMES, name_rows([b_name]))])
        gaia_id, hip_id = id_of(root, GAIA, 1), id_of(root, HIP, 7)

        # b-name keeps its object by id. a-name takes hip 7 first in the pass.
        a_name: dict = {"id": "a-name", "ra": ra, "dec": dec}
        a_name["claims"] = [claim("hip", "2007", 7)]
        b_name["claims"] = [claim("gaia", "dr3", 1), claim("hip", "2007", 7)]
        names = name_rows([a_name, b_name])
        result = ingest([(GAIA, gaia), (HIP, hip), (NAMES, names)])
        counts = result.entry["counts"]
        assert (counts["merged"], counts["conflicts"]) == (0, 1)
        assert id_of(root, GAIA, 1) == gaia_id and id_of(root, HIP, 7) == hip_id
        assert id_of(root, NAMES, "a-name") == hip_id
        assert id_of(root, NAMES, "b-name") == gaia_id


class TestMerges:
    """A duplicate found later: the older ID survives, then the lower number."""

    def test_older_survives_and_rows_move(self, root, registry, ingest, caplog):
        # Two neighbouring cells; the Gaia star sits in the lower one.
        low, high = 4_000_000, 4_000_001
        g_ra, g_dec = centre(low)
        h_ra, h_dec = centre(high)
        hip = hip_rows(
            [{"id": 42, "ra": h_ra, "dec": h_dec, "mag": 2.0, "parallax": 30.0}]
        )
        ingest([(HIP, hip)])
        gaia: list[dict] = [
            {"id": 1, "ra": g_ra, "dec": g_dec, "mag": 2.1, "parallax": 31.0}
        ]
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        older, newer = id_of(root, HIP, 42), id_of(root, GAIA, 1)
        assert newer < older

        gaia[0]["claims"] = [claim("hip", "2007", 42)]
        with caplog.at_level(logging.WARNING):
            result = ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        assert result.entry["counts"]["merged"] == 1
        assert id_of(root, GAIA, 1) == older
        current = Registry(root)
        merges = current.merges(3).to_pylist()
        assert merges[0]["survivor"] == older and merges[0]["loser"] == newer
        assert (
            str(older) in merges[0]["evidence"] and str(newer) in merges[0]["evidence"]
        )
        assert any(
            str(older) in r.message and str(newer) in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
        assert f"{newer} → alias of {older}" in result.report
        assert current.unreviewed() == [3]

        point = by_id(table_rows(root, "point"))
        assert newer not in point
        assert point[older]["astrometry_source"] == "gaia"
        assert point[older]["parallax"] == 31.0 and point[older]["hp"] == 2.0
        meta = by_id(table_rows(root, "metadata"))
        assert meta[newer]["alias_target"] == older and meta[newer]["mask"] == 0
        assert meta[newer]["cross_ids"] is None
        assert {c["catalogue"] for c in meta[older]["cross_ids"]} == {"gaia", "hip"}

        # The next ingest keeps the alias and finds the Gaia id through it.
        result = ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        assert result.entry["counts"]["merged"] == 0
        assert by_id(table_rows(root, "metadata"))[newer]["alias_target"] == older

    def test_merge_across_a_region_edge(self, root, ingest):
        (ra_a, dec_a), (ra_b, dec_b) = straddle(200)
        hip_by_id_only = Source("hip", "hip", "2007", home=1)
        gaia: list[dict] = [{"id": 1, "ra": ra_a, "dec": dec_a, "mag": 3.0}]
        hip = hip_rows([{"id": 42, "ra": ra_b, "dec": dec_b, "mag": 3.1}])
        ingest([(GAIA, gaia_rows(gaia))])
        ingest([(GAIA, gaia_rows(gaia)), (hip_by_id_only, hip)])
        survivor, loser = id_of(root, GAIA, 1), id_of(root, HIP, 42)
        assert sky.region_of(ids.cell_of(survivor)) == 200
        assert sky.region_of(ids.cell_of(loser)) != 200

        gaia[0]["claims"] = [claim("hip", "2007", 42)]
        result = ingest([(GAIA, gaia_rows(gaia)), (hip_by_id_only, hip)])
        assert result.entry["counts"]["merged"] == 1
        assert id_of(root, HIP, 42) == survivor
        registry = Registry(root)
        point = registry.read_table("point", 200)
        assert point is not None
        assert by_id(point)[survivor]["hp"] == pytest.approx(3.1)
        loser_region = sky.region_of(ids.cell_of(loser))
        assert registry.read_table("point", loser_region) is None
        meta = by_id(table_rows(root, "metadata"))
        assert meta[loser]["alias_target"] == survivor
        assert {c["catalogue"] for c in meta[survivor]["cross_ids"]} == {"gaia", "hip"}

        # Next time the cross-id still comes over from the alias's region.
        result = ingest([(GAIA, gaia_rows(gaia)), (hip_by_id_only, hip)])
        assert result.entry["counts"]["merged"] == 0
        meta = by_id(table_rows(root, "metadata"))
        assert {c["catalogue"] for c in meta[survivor]["cross_ids"]} == {"gaia", "hip"}

    def test_same_ingest_lower_number_survives(self, root, ingest):
        low, high = 4_100_000, 4_100_001
        g_ra, g_dec = centre(high)
        h_ra, h_dec = centre(low)
        gaia: list[dict] = [{"id": 1, "ra": g_ra, "dec": g_dec, "mag": 2.1}]
        hip = hip_rows([{"id": 42, "ra": h_ra, "dec": h_dec, "mag": 2.0}])
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        gaia_id, hip_id = id_of(root, GAIA, 1), id_of(root, HIP, 42)
        assert hip_id < gaia_id
        gaia[0]["claims"] = [claim("hip", "2007", 42)]
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        assert id_of(root, GAIA, 1) == hip_id

    def test_review(self, root, backup, ingest, monkeypatch):
        low, high = 4_200_000, 4_200_001
        gaia: list[dict] = [
            {"id": 1, "ra": centre(low)[0], "dec": centre(low)[1], "mag": 2.0}
        ]
        hip = hip_rows([{"id": 42, "ra": centre(high)[0], "dec": centre(high)[1]}])
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        gaia[0]["claims"] = [claim("hip", "2007", 42)]
        ingest([(GAIA, gaia_rows(gaia)), (HIP, hip)])
        assert Registry(root).unreviewed() == [2]
        monkeypatch.setattr(cli_module, "REGISTRY_BACKUP_DIR", backup)
        monkeypatch.setattr(
            sys, "argv", ["space-map-extrasolar", "--root", str(root), "review", "2"]
        )
        cli_module.cli()
        registry = Registry(root)
        assert registry.unreviewed() == []
        assert registry.ingests[1]["reviewed"]
        host = registry.manifest["host"]
        copied = json.loads((backup / host / "manifest.json").read_text())
        assert copied["ingests"][1]["reviewed"] == registry.ingests[1]["reviewed"]


class TestRetire:
    """An ID with no row left retires and never comes back."""

    def test_retire_and_no_reuse(self, root, ingest):
        gaia = gaia_rows([star(1, mag=3.0)])
        hip = hip_rows([star(9, 60, mag=4.0)])
        ingest([(GAIA, gaia), (HIP, hip)])
        hip_id = id_of(root, HIP, 9)
        # The brighter Gaia star took serial 0 of the cell.
        assert ids.decode(hip_id) == (1, 1, CELL)

        with pytest.raises(RegistryError, match="retire"):
            ingest([(GAIA, gaia)])
        assert Registry(root).last_ingest == 1

        result = ingest([(GAIA, gaia)], max_retired=1)
        assert result.entry["counts"]["retired"] == 1
        assert id_of(root, HIP, 9) == 0
        assert hip_id not in by_id(table_rows(root, "metadata"))

        ingest([(GAIA, gaia), (HIP, hip)])
        again = id_of(root, HIP, 9)
        assert again not in (0, hip_id)
        assert ids.cell_of(again) == ids.cell_of(hip_id)
        assert ids.serial_of(again) == ids.serial_of(hip_id) + 1

    def test_partial_input_retires_nothing(self, root, backup):
        gaia = gaia_rows([star(1, mag=3.0), star(2, 30, mag=4.0)])
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [gaia])
            run.commit()
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [gaia.slice(0, 1)], complete=False)
            result = run.commit()
        assert result.entry["counts"]["retired"] == 0
        assert not result.entry["complete"]
        assert id_of(root, GAIA, 2) != 0

    def test_an_alias_of_a_retired_id_gets_a_new_id(self, root, ingest):
        # The last row's view holds the alias's region, without the survivor's.
        (ra_s, dec_s), (ra_a, dec_a) = straddle(200)
        alias_region = int(
            sky.region_of(sky.cells(np.array([ra_a]), np.array([dec_a]))[0])
        )
        far = set(sky.neighbour_regions(200)) | {200}
        row_region = next(
            r for r in sky.neighbour_regions(alias_region) if r not in far
        )
        ra_r, dec_r = centre(sky.region_cells(row_region)[0])
        hip_by_id_only = Source("hip", "hip", "2007", home=1)
        gaia: list[dict] = [{"id": 1, "ra": ra_s, "dec": dec_s, "mag": 3.0}]
        hip = [{"id": 42, "ra": ra_a, "dec": dec_a, "mag": 3.1}]
        ingest([(GAIA, gaia_rows(gaia))])
        ingest([(GAIA, gaia_rows(gaia)), (hip_by_id_only, hip_rows(hip))])
        survivor, alias = id_of(root, GAIA, 1), id_of(root, HIP, 42)
        gaia[0]["claims"] = [claim("hip", "2007", 42)]
        ingest([(GAIA, gaia_rows(gaia)), (hip_by_id_only, hip_rows(hip))])
        assert id_of(root, HIP, 42) == survivor
        assert ingest([], max_retired=1).entry["counts"]["retired"] == 1

        moved = [{"id": 42, "ra": ra_r, "dec": dec_r, "mag": 3.1}]
        result = ingest([(hip_by_id_only, hip_rows(moved))])
        assert result.entry["sources"][0].get("retired_hits") == 1
        assert id_of(root, HIP, 42) not in (0, survivor, alias)
        assert survivor not in by_id(table_rows(root, "point"))


class TestFailures:
    """A failed ingest leaves the previous registry and tables in force."""

    def test_failed_table_build_keeps_old_tables(self, root, ingest, monkeypatch):
        gaia = gaia_rows([star(1, mag=3.0)])
        ingest([(GAIA, gaia)])
        before = table_rows(root, "point")

        def broken(*args):
            raise RuntimeError("table build failed")

        monkeypatch.setattr(engine, "merge_by_source_order", broken)
        with pytest.raises(RuntimeError):
            ingest([(GAIA, gaia_rows([star(1, mag=3.0), star(2, 9, mag=2.0)]))])
        registry = Registry(root)
        assert registry.last_ingest == 1
        assert table_rows(root, "point").equals(before)
        assert not (root / "tables" / "point" / "000002").exists()
        assert not (root / "registry" / "segments" / "000002").exists()

    def test_crash_before_commit(self, root, backup, monkeypatch):
        gaia = gaia_rows([star(1, mag=3.0)])
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [gaia])
            run.commit()
        manifest = (root / "registry" / "manifest.json").read_text()

        # A killed process cleans nothing up.
        monkeypatch.setattr(IngestRun, "abort", lambda self: self._release())
        monkeypatch.setattr(
            Registry,
            "commit",
            lambda self, *a: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        with (
            pytest.raises(KeyboardInterrupt),
            IngestRun.start(root, backup, (POINT,), META) as run,
        ):
            run.add(GAIA, [gaia_rows([star(1, mag=3.0), star(2, 9, mag=2.0)])])
            run.commit()
        assert (root / "registry" / "manifest.json").read_text() == manifest
        assert (root / "registry" / "segments" / "000002").exists()
        assert id_of(root, GAIA, 2) == 0
        assert table_rows(root, "point").num_rows == 1

        monkeypatch.undo()
        with IngestRun.start(root, backup, (POINT,), META) as run:
            assert run.ingest == 2
            assert not (root / "registry" / "segments" / "000002").exists()
            assert not list((root / "registry" / "staging").glob("*"))
            run.add(GAIA, [gaia_rows([star(1, mag=3.0), star(2, 9, mag=2.0)])])
            run.commit()
        assert id_of(root, GAIA, 2) != 0

    def test_failed_backup_keeps_the_ingest(
        self, root, backup, ingest, monkeypatch, caplog
    ):
        def nas_down(self, backup_root):
            raise OSError("the NAS is down")

        with monkeypatch.context() as patched, caplog.at_level(logging.ERROR):
            patched.setattr(Registry, "backup", nas_down)
            result = ingest([(GAIA, gaia_rows([star(1, mag=3.0)]))])
        assert Registry(root).last_ingest == 1 and id_of(root, GAIA, 1) != 0
        assert result.backup_error is not None and "NAS" in result.backup_error
        command = f"space-map-extrasolar --root {root} --backup-root {backup} backup"
        assert f"`{command}`" in result.report
        assert any(
            r.levelno == logging.ERROR and command in r.message for r in caplog.records
        )

        # The lock is free, and the command that the report names copies it.
        monkeypatch.setattr(sys, "argv", command.split())
        cli_module.cli()
        host = Registry(root).manifest["host"]
        assert (backup / host / "segments" / "000001").is_dir()

    def test_registry_parts(self, root, ingest):
        ingest(
            [
                (GAIA, gaia_rows([star(1, mag=3.0), star(2, 1, mag=4.0)])),
                (HIP, hip_rows([star(5, 0.2, mag=3.0)])),
            ]
        )
        registry = Registry(root)
        region = sky.region_of(CELL)
        id_records = registry.read_part("ids", region)
        assert set(id_records["status"].to_pylist()) == {"live"}
        xids = registry.read_part("xids", region).to_pylist()
        links = {(x["catalogue"], x["catalogue_id"]): x["link"] for x in xids}
        assert links == {
            ("gaia", "1"): "mint",
            ("gaia", "2"): "mint",
            ("hip", "5"): "position",
        }
        assert next(x for x in xids if x["link"] == "position")["score"] >= 0
        positions = registry.read_part("positions", region)
        assert positions.num_rows == 2 and set(positions["source"].to_pylist()) == {
            "gaia"
        }
        cells = ids.cell_of(np.array(id_records["id"].to_pylist()))
        assert (np.diff(cells) >= 0).all()
