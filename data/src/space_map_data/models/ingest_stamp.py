"""Single-row stamp recording the last completed ingest run."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Mapped, Session, mapped_column

from space_map_data.models.object.base import Base

_ROW_ID = 1


class IngestStamp(Base):
    """Opaque token rewritten at the end of every ingest invocation.

    The export records the stamp it built from; a differing (or missing)
    stamp on the next run invalidates everything derived from DB content.
    """

    __tablename__ = "ingest_stamp"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column()
    finished_at: Mapped[str] = mapped_column()
    targets: Mapped[str] = mapped_column()


def write_ingest_stamp(session: Session, targets: list[str]) -> None:
    """Replace the stamp row; call once after any ingest targets ran."""
    stamp = session.get(IngestStamp, _ROW_ID) or IngestStamp(id=_ROW_ID)
    stamp.run_id = uuid.uuid4().hex
    stamp.finished_at = datetime.now(UTC).isoformat()
    stamp.targets = ",".join(targets)
    session.add(stamp)
    session.commit()


def read_ingest_stamp(session: Session) -> str | None:
    """Return the current stamp token, or None when no ingest recorded one."""
    stamp = session.get(IngestStamp, _ROW_ID)
    return stamp.run_id if stamp is not None else None
