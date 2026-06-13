"""Tests for split-comet family grouping and fragment attachment."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.comet_fragments import family_group_slug
from space_map_data.export.objects.fragments import build_comet_families
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass


class _NoWikidata:
    """Stand-in cache: no entities on disk, so labels fall back to DB names."""

    def get_entity(self, qid):  # noqa: ARG002
        return None


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
    assert family_group_slug(fam.parent_pdes) == "comet-family-1882-r1"


def test_fragment_ranking_prefers_image(session: Session) -> None:
    _add(session, 2, "51P-A", CometPrefix.P, "51P/Harrington-A", sitelinks=99)
    _add(session, 3, "51P-B", CometPrefix.P, "51P/Harrington-B", image=True)
    session.commit()

    fam = build_comet_families(session, _NoWikidata())["51P"]  # type: ignore[arg-type]
    # Image availability outranks sitelinks.
    assert fam.fragments[0].object_id == "spkid-3"


def test_non_comet_dash_excluded(session: Session) -> None:
    # Palomar-Leiden survey asteroid: dash syntax but no comet prefix.
    _add(session, 9, "6344 P-L", None, "(6344 P-L)")
    session.commit()

    assert build_comet_families(session, _NoWikidata()) == {}  # type: ignore[arg-type]
