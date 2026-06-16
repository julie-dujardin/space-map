"""SQLAlchemy ORM model for the GCAT launch log (planet4589.org launchlog.tsv)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.constants.earth_sats.launchlog import (
    Attachment,
    IdStatus,
    OperationalStatus,
    OrbitStatus,
    SpaceflightGroup,
    Subtype,
    TypeModifier,
    UNRegistration,
)
from space_map_data.models.object.base import Base


class Launchlog(Base):
    """Full mirror of Jonathan McDowell's GCAT launchlog.tsv — one row per payload.

    Keyed by JCAT (McDowell's catalogue number), which is unique per row.
    `piece` is the COSPAR designation and is NOT unique: sub-objects deployed
    under the same launch piece (e.g. several experiments at 2016-042A) each
    get a distinct JCAT but share the piece. The Object→Launchlog link lives on
    the Object side (`Object.launchlog_jcat`), matched on `piece` == cospar.
    """

    __tablename__ = "launchlog"

    jcat: Mapped[str] = mapped_column(primary_key=True)

    launch_tag: Mapped[str | None] = mapped_column(default=None, index=True)
    launch_date_iso: Mapped[str | None] = mapped_column(
        default=None
    )  # partial ISO 8601 at source precision (date / minute / second, UTC)
    launch_date_uncertain: Mapped[bool] = mapped_column(
        default=False
    )  # GCAT "?" marker — date/time is an estimate
    piece: Mapped[str | None] = mapped_column(default=None, index=True)  # COSPAR
    # Decoded GCAT SatType bytes 2-9 (byte 1 is always P; see constants module).
    type_modifier: Mapped[TypeModifier | None] = mapped_column(String, default=None)
    attachment: Mapped[Attachment | None] = mapped_column(String, default=None)
    subtype: Mapped[Subtype | None] = mapped_column(String, default=None)
    orbit_status: Mapped[OrbitStatus | None] = mapped_column(String, default=None)
    spaceflight_group: Mapped[SpaceflightGroup | None] = mapped_column(
        String, default=None
    )
    un_registration: Mapped[UNRegistration | None] = mapped_column(String, default=None)
    operational_status: Mapped[OperationalStatus | None] = mapped_column(
        String, default=None
    )
    id_status: Mapped[IdStatus | None] = mapped_column(String, default=None)
    name: Mapped[str | None] = mapped_column(default=None)
    plname: Mapped[str | None] = mapped_column(default=None)  # payload name
    sat_owner: Mapped[str | None] = mapped_column(default=None)
    sat_state: Mapped[str | None] = mapped_column(default=None)
    lv_type: Mapped[str | None] = mapped_column(default=None)  # launch vehicle
    flight_id: Mapped[str | None] = mapped_column(
        default=None
    )  # vehicle/booster serial
    platform: Mapped[str | None] = mapped_column(default=None)
    launch_site: Mapped[str | None] = mapped_column(default=None)
    launch_pad: Mapped[str | None] = mapped_column(default=None)
    ascent_site: Mapped[str | None] = mapped_column(default=None)
    ascent_pad: Mapped[str | None] = mapped_column(default=None)
    agency: Mapped[str | None] = mapped_column(default=None)  # launch agency
    lv_state: Mapped[str | None] = mapped_column(default=None)  # vehicle nationality
    launch_code: Mapped[str | None] = mapped_column(default=None)
    ltcite: Mapped[str | None] = mapped_column(default=None)  # provenance citation
