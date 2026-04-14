"""SQLAlchemy ORM model for the launch_site table."""

from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object.base import Base


class LaunchSite(Base):
    """CelesTrak SATCAT launch site (e.g. TYMSC = Baikonur/Tyuratam).

    See: https://celestrak.org/satcat/launchsites.php
    """

    __tablename__ = "launch_site"

    code: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    wikidata_qid: Mapped[str | None] = mapped_column(default=None)
