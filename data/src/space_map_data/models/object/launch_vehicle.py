"""SQLAlchemy ORM model for the GCAT launch-vehicle table (planet4589.org lv.tsv).

One row per launch-vehicle name (`lv_name`), the join key to
`launchlog.lv_type`. GCAT lists several sub-variant rows per name (e.g. "Atlas
V 551" base/C/G); we collapse to a single representative row since launchlog
carries only the bare name. `family` is GCAT's coarse design lineage (e.g.
"Atlas5", "R-7") used to bucket variants under a launch-vehicle group.
"""

from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object.base import Base


class LaunchVehicle(Base):
    __tablename__ = "launch_vehicle"

    lv_name: Mapped[str] = mapped_column(primary_key=True)

    family: Mapped[str | None] = mapped_column(default=None, index=True)
    manufacturer: Mapped[str | None] = mapped_column(default=None)
    alias: Mapped[str | None] = mapped_column(default=None)
    min_stage: Mapped[int | None] = mapped_column(default=None)
    max_stage: Mapped[int | None] = mapped_column(default=None)
    length_m: Mapped[float | None] = mapped_column(default=None)
    diameter_m: Mapped[float | None] = mapped_column(default=None)
    launch_mass_t: Mapped[float | None] = mapped_column(default=None)
    leo_capacity_kg: Mapped[float | None] = mapped_column(default=None)
    gto_capacity_kg: Mapped[float | None] = mapped_column(default=None)
    thrust_kn: Mapped[float | None] = mapped_column(default=None)
    lv_class: Mapped[str | None] = mapped_column(
        default=None
    )  # GCAT Class, e.g. "O" orbital
