"""Tests for split-comet family grouping and fragment attachment."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.comet_fragments import family_group_slug
from space_map_data.export.objects.fragments import (
    NOTABLE_FRAGMENT_COUNT,
    build_comet_families,
)
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass


class _NoWikidata:
    """Stand-in cache: no entities on disk, so labels fall back to DB names."""

    def get_entity(self, qid):  # noqa: ARG002
        return None


class _FakeWikidata:
    """Cache returning canned English labels for given QIDs."""

    def __init__(self, labels: dict[str, str]) -> None:
        self._labels = labels

    def get_entity(self, qid):
        return {"labels": {"en": self._labels[qid]}} if qid in self._labels else None


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


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

    families = build_comet_families(session, _NoWikidata())  # type: ignore[arg-type]

    assert set(families) == {"73P"}
    fam = families["73P"]
    assert fam.parent_object_id == parent
    assert fam.parent_name == "73P/Schwassmann-Wachmann 3"
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

    families = build_comet_families(session, _NoWikidata())  # type: ignore[arg-type]

    fam = families["1882 R1"]
    assert fam.parent_object_id is None
    assert fam.parent_name == "C/1882 R1 (Great September comet)"
    assert fam.designation == "C/1882 R1"  # full IAU designation for lookup
    assert family_group_slug(fam.parent_pdes) == "comet-family-1882-r1"


def test_parentless_numbered_name(session: Session) -> None:
    # Numbered parentless comet: the suffix rides the name, not the designation
    # (483P/PANSTARRS-A), so a naive "483P-A" strip would miss it.
    _add(session, 1003464, "483P-A", CometPrefix.P, "483P/PANSTARRS-A")
    _add(session, 1003465, "483P-B", CometPrefix.P, "483P/PANSTARRS-B")
    session.commit()

    fam = build_comet_families(session, _NoWikidata())["483P"]  # type: ignore[arg-type]
    assert fam.parent_object_id is None
    assert fam.parent_name == "483P/PANSTARRS"
    assert fam.designation == "483P"  # numbered comets stay bare


def test_parentless_qid_picks_comet_over_fragment(session: Session) -> None:
    # Fragment A links to the comet's page, B to a per-fragment item; the
    # comet-level QID (label without a fragment suffix) wins, and names the page.
    _add(session, 1000366, "2001 A2-A", CometPrefix.C, "C/2001 A2-A (LINEAR)", qid="Qc")
    _add(session, 1000340, "2001 A2-B", CometPrefix.C, "C/2001 A2-B (LINEAR)", qid="Qf")
    session.commit()

    cache = _FakeWikidata({"Qc": "C/2001 A2 (LINEAR)", "Qf": "C/2001 A2-B"})
    fam = build_comet_families(session, cache)["2001 A2"]  # type: ignore[arg-type]
    assert fam.parent_qid == "Qc"
    assert fam.parent_name == "C/2001 A2 (LINEAR)"


def test_parentless_qid_all_fragments_declines(session: Session) -> None:
    # Both QIDs are per-fragment items (no comet-level page) → no family QID.
    _add(session, 1, "1996 J1-A", CometPrefix.C, "C/1996 J1-A (Evans)", qid="Qa")
    _add(session, 2, "1996 J1-B", CometPrefix.C, "C/1996 J1-B (Evans)", qid="Qb")
    session.commit()

    cache = _FakeWikidata(
        {"Qa": "C/1996 J1-A (Evans-Drinkwater)", "Qb": "C/1996 J1-B (Evans-Drinkwater)"}
    )
    fam = build_comet_families(session, cache)["1996 J1"]  # type: ignore[arg-type]
    assert fam.parent_qid is None


def test_fragment_ranking_prefers_image(session: Session) -> None:
    _add(session, 2, "51P-A", CometPrefix.P, "51P/Harrington-A", sitelinks=99)
    _add(session, 3, "51P-B", CometPrefix.P, "51P/Harrington-B", image=True)
    session.commit()

    fam = build_comet_families(session, _NoWikidata())["51P"]  # type: ignore[arg-type]
    # Image availability outranks sitelinks.
    assert fam.fragments[0].object_id == "spkid-3"


def test_member_ids_covers_all_fragments_beyond_display_cap(session: Session) -> None:
    # member_ids must hold every fragment (drives fragment_of), even past the
    # display cap — regression for 73P's 53rd piece losing its parent link.
    n = NOTABLE_FRAGMENT_COUNT + 3
    _add(session, 4999, "73P", CometPrefix.P, "73P/SW3", name="73P/SW3")
    for i in range(n):
        suffix = chr(ord("A") + i)
        _add(session, 5000 + i, f"73P-{suffix}", CometPrefix.P, f"73P/SW3-{suffix}")
    session.commit()

    fam = build_comet_families(session, _NoWikidata())["73P"]  # type: ignore[arg-type]
    assert len(fam.fragments) == NOTABLE_FRAGMENT_COUNT  # display list stays capped
    assert len(fam.member_ids) == n  # but every fragment is tracked
    assert fam.total == n


def test_non_comet_dash_excluded(session: Session) -> None:
    # Palomar-Leiden survey asteroid: dash syntax but no comet prefix.
    _add(session, 9, "6344 P-L", None, "(6344 P-L)")
    session.commit()

    assert build_comet_families(session, _NoWikidata()) == {}  # type: ignore[arg-type]
