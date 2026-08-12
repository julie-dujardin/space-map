"""SQLAlchemy ORM models for the GCAT site tables (sites.tsv, lp.tsv).

`launchlog.launch_site` / `.launch_pad` name a place only by code; these two
tables are what turn those codes into a position. GCAT splits a place into
phases — a renamed or re-chartered range gets a fresh `code` row — so `ucode`
is the stable identity across phases and the key to join on. Both tables state
a positional `error_deg` alongside the coordinate: a site row is one coarse
point standing for a whole range (Baikonur's sits 28 km from Gagarin's Start),
while a launch point is the individual pad and is usually good to a few metres.
"""

from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object.base import Base


class LaunchSite(Base):
    """One GCAT sites.tsv row — a launch site in one of its naming phases."""

    __tablename__ = "launch_site"

    code: Mapped[str] = mapped_column(primary_key=True)  # GCAT Site
    ucode: Mapped[str | None] = mapped_column(default=None, index=True)

    site_type: Mapped[str | None] = mapped_column(default=None)  # LS / LC / LZ
    state_code: Mapped[str | None] = mapped_column(default=None)
    t_start: Mapped[str | None] = mapped_column(default=None)  # GCAT vague date
    t_stop: Mapped[str | None] = mapped_column(default=None)
    short_name: Mapped[str | None] = mapped_column(default=None)
    name: Mapped[str | None] = mapped_column(default=None)
    location: Mapped[str | None] = mapped_column(default=None)
    longitude: Mapped[float | None] = mapped_column(default=None)  # deg, east-positive
    latitude: Mapped[float | None] = mapped_column(default=None)  # deg
    error_deg: Mapped[float | None] = mapped_column(default=None)
    parent: Mapped[str | None] = mapped_column(default=None)  # operating org code
    site_group: Mapped[str | None] = mapped_column(default=None)  # GCAT Group
    # Matched on position and name, not joined: no Wikidata property carries a
    # GCAT code. Set on the canonical phase row only.
    wikidata_qid: Mapped[str | None] = mapped_column(default=None, index=True)


class LaunchPad(Base):
    """One GCAT lp.tsv row — an individual pad, keyed within its site.

    `site` is the site code this pad hung off during the phase the row covers,
    which is not always the phase the launchlog names; resolve both through
    `LaunchSite.ucode` rather than matching the code directly.
    """

    __tablename__ = "launch_pad"

    site: Mapped[str] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(primary_key=True)

    ucode: Mapped[str | None] = mapped_column(default=None)
    t_start: Mapped[str | None] = mapped_column(default=None)
    t_stop: Mapped[str | None] = mapped_column(default=None)
    short_name: Mapped[str | None] = mapped_column(default=None)
    name: Mapped[str | None] = mapped_column(default=None)
    location: Mapped[str | None] = mapped_column(default=None)
    longitude: Mapped[float | None] = mapped_column(default=None)  # deg, east-positive
    latitude: Mapped[float | None] = mapped_column(default=None)  # deg
    error_deg: Mapped[float | None] = mapped_column(default=None)
    parent: Mapped[str | None] = mapped_column(default=None)
    wikidata_qid: Mapped[str | None] = mapped_column(default=None, index=True)
