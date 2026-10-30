"""Tests for split-comet family grouping and fragment attachment."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import space_map_data.export.objects.fragments as fragments_mod
from space_map_data.constants.comet_fragments import family_group_slug
from space_map_data.export.names import ObjectNames
from space_map_data.export.objects.fragments import (
    NOTABLE_FRAGMENT_COUNT,
    _designation_qids,
    build_comet_families,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass


class _NoWikidata(WikidataEntityCache):
    """Stand-in cache: no entities on disk, so labels fall back to DB names."""

    def __init__(self) -> None:  # skips the on-disk load
        pass

    def get_entity(self, qid):
        return None

    get_referenced = get_entity


class _FakeWikidata(WikidataEntityCache):
    """Cache returning canned English labels for given QIDs."""

    def __init__(self, labels: dict[str, str]) -> None:
        self._labels = labels

    def get_entity(self, qid):
        return {"labels": {"en": self._labels[qid]}} if qid in self._labels else None

    def get_referenced(self, qid):
        return None


@pytest.fixture(autouse=True)
def _no_designation_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the real Wikidata match files out of the lookups."""
    monkeypatch.setattr(fragments_mod, "SOURCES_METADATA_DIR", tmp_path)
    return tmp_path


def _write_matches(root: Path, pid: str, rows: list[tuple[str, str]]) -> None:
    d = root / "wikidata" / "ids" / "matches"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.csv").write_text("".join(f"{term},{qids}\n" for term, qids in rows))


def _add(
    session: Session,
    spkid: int,
    pdes: str,
    prefix: CometPrefix | None,
    full_name: str,
    *,
    name: str | None = None,
    image: bool = False,
    sitelinks: int = 0,
    qid: str | None = None,
) -> str:
    obj_id = f"spkid-{spkid}"
    session.add(
        Object(
            id=obj_id,
            name=name,
            object_type=ObjectType.comet,
            image_available=image,
            sitelinks_count=sitelinks,
            wikidata_qid=qid,
        )
    )
    session.add(
        SBDB(
            spkid=str(spkid),
            object_id=obj_id,
            pdes=pdes,
            prefix=prefix,
            full_name=full_name,
            class_=OrbitClass.JFC,
        )
    )
    return obj_id


def test_intact_parent_family(session: Session) -> None:
    parent = _add(
        session,
        1000394,
        "73P",
        CometPrefix.P,
        "73P/Schwassmann-Wachmann 3",
        name="73P/Schwassmann-Wachmann 3",
    )
    _add(session, 1000320, "73P-B", CometPrefix.P, "73P/Schwassmann-Wachmann 3-B")
    _add(session, 1000081, "73P-C", CometPrefix.P, "73P/Schwassmann-Wachmann 3-C")
    session.commit()

    families = build_comet_families(session, ObjectNames(_NoWikidata(), session))

    assert set(families) == {"73P"}
    fam = families["73P"]
    assert fam.parent_object_id == parent
    assert fam.names.name == "73P/Schwassmann-Wachmann 3"
    assert fam.total == 2
    assert {f.object_id for f in fam.fragments} == {"spkid-1000320", "spkid-1000081"}


def test_parentless_family_reconstructs_name(session: Session) -> None:
    _add(
        session,
        1000882,
        "1882 R1-A",
        CometPrefix.C,
        "C/1882 R1-A (Great September comet)",
    )
    _add(
        session,
        1000883,
        "1882 R1-B",
        CometPrefix.C,
        "C/1882 R1-B (Great September comet)",
    )
    session.commit()

    families = build_comet_families(session, ObjectNames(_NoWikidata(), session))

    fam = families["1882 R1"]
    assert fam.parent_object_id is None
    assert fam.names.name == "C/1882 R1 (Great September comet)"
    assert fam.designation == "C/1882 R1"  # full IAU designation for lookup
    assert family_group_slug(fam.parent_pdes) == "comet-family-1882-r1"


def test_parentless_numbered_name(session: Session) -> None:
    # Suffix rides the name (483P/PANSTARRS-A), not the designation, so a naive strip would miss it.
    _add(session, 1003464, "483P-A", CometPrefix.P, "483P/PANSTARRS-A")
    _add(session, 1003465, "483P-B", CometPrefix.P, "483P/PANSTARRS-B")
    session.commit()

    fam = build_comet_families(session, ObjectNames(_NoWikidata(), session))["483P"]
    assert fam.parent_object_id is None
    assert fam.names.name == "483P/PANSTARRS"
    assert fam.designation == "483P"  # numbered comets stay bare


def test_parentless_qid_picks_comet_over_fragment(session: Session) -> None:
    # A links to the comet's page, B to a per-fragment item; the comet-level QID wins.
    _add(session, 1000366, "2001 A2-A", CometPrefix.C, "C/2001 A2-A (LINEAR)", qid="Qc")
    _add(session, 1000340, "2001 A2-B", CometPrefix.C, "C/2001 A2-B (LINEAR)", qid="Qf")
    session.commit()

    cache = _FakeWikidata({"Qc": "C/2001 A2 (LINEAR)", "Qf": "C/2001 A2-B"})
    fam = build_comet_families(session, ObjectNames(cache, session))["2001 A2"]
    assert fam.parent_qid == "Qc"
    assert fam.names.name == "C/2001 A2 (LINEAR)"


def test_parentless_qid_all_fragments_declines(session: Session) -> None:
    # Both QIDs are per-fragment items (no comet-level page) → no family QID.
    _add(session, 1, "1996 J1-A", CometPrefix.C, "C/1996 J1-A (Evans)", qid="Qa")
    _add(session, 2, "1996 J1-B", CometPrefix.C, "C/1996 J1-B (Evans)", qid="Qb")
    session.commit()

    cache = _FakeWikidata(
        {"Qa": "C/1996 J1-A (Evans-Drinkwater)", "Qb": "C/1996 J1-B (Evans-Drinkwater)"}
    )
    fam = build_comet_families(session, ObjectNames(cache, session))["1996 J1"]
    assert fam.parent_qid is None


def test_fragment_ranking_prefers_image(session: Session) -> None:
    _add(session, 2, "51P-A", CometPrefix.P, "51P/Harrington-A", sitelinks=99)
    _add(session, 3, "51P-B", CometPrefix.P, "51P/Harrington-B", image=True)
    session.commit()

    fam = build_comet_families(session, ObjectNames(_NoWikidata(), session))["51P"]
    # Image availability outranks sitelinks.
    assert fam.fragments[0].object_id == "spkid-3"


def test_member_ids_covers_all_fragments_beyond_display_cap(session: Session) -> None:
    # member_ids must hold every fragment past the display cap — 73P's 53rd piece once lost its parent link.
    n = NOTABLE_FRAGMENT_COUNT + 3
    _add(session, 4999, "73P", CometPrefix.P, "73P/SW3", name="73P/SW3")
    for i in range(n):
        suffix = chr(ord("A") + i)
        _add(session, 5000 + i, f"73P-{suffix}", CometPrefix.P, f"73P/SW3-{suffix}")
    session.commit()

    fam = build_comet_families(session, ObjectNames(_NoWikidata(), session))["73P"]
    assert len(fam.fragments) == NOTABLE_FRAGMENT_COUNT  # display list stays capped
    assert len(fam.member_ids) == n  # but every fragment is tracked
    assert fam.total == n


def test_non_comet_dash_excluded(session: Session) -> None:
    # Palomar-Leiden survey asteroid: dash syntax but no comet prefix.
    _add(session, 9, "6344 P-L", None, "(6344 P-L)")
    session.commit()

    assert build_comet_families(session, ObjectNames(_NoWikidata(), session)) == {}


class TestDesignationLookup:
    """A parentless family finds its Wikidata item by designation."""

    def test_the_match_files_merge(self, _no_designation_matches: Path):
        # P490 holds hand-set prefixed designations; P5736 holds numbered ones.
        _write_matches(
            _no_designation_matches,
            "P490",
            [("C/1860 D1", "Q9826864"), ("C/1956 F1", "Q1")],
        )
        _write_matches(_no_designation_matches, "P5736", [("483P", "Q60977726")])
        out = _designation_qids()
        assert out["C/1860 D1"] == ["Q9826864"]
        assert out["C/1956 F1"] == ["Q1"]
        assert out["483P"] == ["Q60977726"]

    def test_no_match_files_match_nothing(self):
        assert _designation_qids() == {}

    def test_a_family_takes_the_item_of_its_designation(
        self, session: Session, _no_designation_matches: Path
    ):
        _write_matches(_no_designation_matches, "P5736", [("483P", "Qd")])
        _add(session, 1003464, "483P-A", CometPrefix.P, "483P/PANSTARRS-A")
        session.commit()

        cache = _FakeWikidata({"Qd": "483P/PANSTARRS comet"})
        fam = build_comet_families(session, ObjectNames(cache, session))["483P"]
        assert fam.parent_qid == "Qd"
        assert fam.names.name == "483P/PANSTARRS comet"
        assert fam.page_id == "comet-family-483p"
