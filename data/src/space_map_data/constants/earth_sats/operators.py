"""Satellite operators (companies, agencies, intergovernmental orgs).

An operator is a real-world entity that owns/operates satellites. It is linked
to the fleet through one of two paths:

- ``source``: a SATCAT ``OWNER`` code (see ``sources.py``) — used when
  CelesTrak assigns the operator its own code (Intelsat, Eutelsat, ...).
- ``constellations``: a tuple of constellation slugs — used when the operator
  isn't a SATCAT source but owns one or more constellations (SpaceX operates
  Starlink, Amazon operates Kuiper, EUMETSAT operates MetOp/Meteosat, ...).

The per-source ``operator`` free-text field on ``SourceSpec`` was removed in
favor of this structured form.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    wikidata_qid: str | None
    source: str | None = None  # SATCAT SOURCE/OWNER code, when one exists
    constellations: tuple[str, ...] = ()  # constellation slugs operated by this entity


OPERATORS: tuple[OperatorSpec, ...] = (
    # Linked via a dedicated SATCAT SOURCE code
    OperatorSpec("Arabsat", "Q65277396", source="AB"),
    OperatorSpec("Asia Broadcast Satellite", "Q18238088", source="ABS"),
    OperatorSpec("AsiaSat", "Q726812", source="AC"),
    OperatorSpec("European Space Agency", None, source="ESA"),
    OperatorSpec("European Space Research Organization", None, source="ESRO"),
    OperatorSpec(
        "EUMETSAT", "Q692163", source="EUME", constellations=("metop", "meteosat")
    ),
    OperatorSpec("Eutelsat", "Q848336", source="EUTE", constellations=("oneweb",)),
    OperatorSpec("Globalstar", "Q1202533", source="GLOB"),
    OperatorSpec(
        "Inmarsat",
        "Q827927",
        source="IM",
        constellations=("marecs", "marisat", "inmarsat"),
    ),
    OperatorSpec("Iridium", "Q3154356", source="IRID"),
    OperatorSpec("Indian Space Research Organisation", None, source="ISRO"),
    OperatorSpec("Intelsat", "Q778126", source="ITSO"),
    OperatorSpec("North Atlantic Treaty Organization", None, source="NATO"),
    OperatorSpec("ICO Global Communications", "Q3792482", source="NICO"),
    OperatorSpec("O3b Networks", "Q3347484", source="O3B"),
    OperatorSpec("Orbcomm", "Q16960684", source="ORB"),
    OperatorSpec("RascomStar-QAF", "Q3415056", source="RASC"),
    OperatorSpec("SES", "Q333025", source="SES"),
    # Linked only via constellation
    OperatorSpec("SpaceX", "Q193701", constellations=("starlink",)),
    OperatorSpec("Amazon", "Q3884", constellations=("kuiper",)),
)


OPERATOR_BY_SOURCE: dict[str, OperatorSpec] = {
    o.source: o for o in OPERATORS if o.source is not None
}
OPERATOR_BY_CONSTELLATION: dict[str, OperatorSpec] = {
    slug: o for o in OPERATORS for slug in o.constellations
}
