"""SQLAlchemy ORM model for SsODNet best-estimate physical properties."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class SsODNet(Base):
    """One row per small body carrying a SsODNet best estimate we use.

    SsODNet aggregates ~3000 papers and elects one best value per property;
    the Big Flat Table publishes those elections for every object at once.
    Only rows with something we consume are kept — overwhelmingly the
    taxonomic class, which is what the interior block turns into a
    composition estimate.

    `taxonomy_scheme` is the citation: a class letter means different things
    under Tholen, Bus, Bus-DeMeo and Mahlke, so the scheme travels with it
    all the way to the panel.
    """

    __tablename__ = "ssodnet"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    sso_number: Mapped[int | None] = mapped_column(default=None, index=True)

    taxonomy_class: Mapped[str | None] = mapped_column(default=None, index=True)
    # The class's parent group ("S" for "Sq"), so an unmapped compound class
    # can still fall back to something.
    taxonomy_complex: Mapped[str | None] = mapped_column(default=None)
    taxonomy_scheme: Mapped[str | None] = mapped_column(default=None)

    albedo: Mapped[float | None] = mapped_column(default=None)  # geometric, visual
    density: Mapped[float | None] = mapped_column(default=None)  # kg/m³
    diameter_km: Mapped[float | None] = mapped_column(default=None)

    object: Mapped["Object"] = relationship(back_populates="ssodnet")
