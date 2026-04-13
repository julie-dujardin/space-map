"""SQLAlchemy ORM model for the constellation table."""

from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object.base import Base


class Constellation(Base):
    """Satellite constellation (e.g. Starlink, Galileo)."""

    __tablename__ = "constellation"

    slug: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    wikidata_qid: Mapped[str | None] = mapped_column(default=None)
