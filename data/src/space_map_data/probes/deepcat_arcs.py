"""Assemble Deep Space Catalog phases into publishable heliocentric arcs.

One arc per solar phase: a two-body conic that starts where the phase starts
and is only claimed for as long as the phase lasts. Which phases are worth
publishing was decided by measurement, not by taste — 77 phases whose probes
also have archive trajectories were solved blind and scored against them, and
the classes below are the ones that separated cleanly.

Direct transfers between two inner bodies land within 0.03 AU, which is the
Hill sphere the anchor is taken from and therefore the floor. Returns to the
departure body are ten times worse and are dropped: they are the gravity-assist
loops, and the deep-space manoeuvre in the middle is exactly what a single
conic cannot represent.
"""

import logging
from dataclasses import dataclass
from enum import Enum


from space_map_data.probes.deepcat import (
    DatePrecision,
    DeepObject,
    DeepPhase,
    GcatDate,
    SolarElements,
)
from space_map_data.probes.deepcat_solve import (
    ANCHOR_NAIF,
    HILL_KM,
    BoundaryConstraint,
    ConicSolution,
    anchor_state,
    branch_score,
    choose_branch,
    solve_anchor,
)
from space_map_data.probes.propagation import AU_KM
from space_map_data.utils.time import jd_to_et

logger = logging.getLogger(__name__)

# Bodies whose Hill sphere is small enough to anchor against. Jupiter's is
# 0.34 AU across, so a phase boundary there states the position no better than
# the answer needs to be; measured error past Jupiter ran to several AU.
INNER_BODIES: frozenset[str] = frozenset({"Mercury", "Venus", "Earth", "Luna", "Mars"})

# GCAT states apsides to a thousandth of an AU; that rounding rides on top of
# the Hill-sphere anchor error when deciding whether an anchor is on the conic.
APSIS_ROUNDING_AU = 0.002

# Coarser than a day and the anchor body has moved a useful fraction of its own
# orbit before the date even resolves.
USABLE_PRECISION = (
    DatePrecision.DAY,
    DatePrecision.MINUTE,
    DatePrecision.SECOND,
)


class ArcClass(Enum):
    """What kind of phase this is, which is what its accuracy depends on."""

    TRANSFER = "transfer"
    OPEN = "open"


# Median position error per class, in AU, measured against archive
# trajectories by `scripts/deepcat_validate.py`. Shipped with the arc so a
# consumer states the error rather than implying there is none. The
# ninetieth percentiles behind these medians were 0.060 and 0.675 AU.
CLASS_ACCURACY_AU: dict[ArcClass, float] = {
    ArcClass.TRANSFER: 0.024,
    ArcClass.OPEN: 0.094,
}


@dataclass(frozen=True)
class SolvedArc:
    """One solar phase as a state vector plus the claim being made about it."""

    deep_id: str
    name: str
    phase: int
    arc_class: ArcClass
    anchor_body: str
    arrival_body: str | None
    start_et: float
    end_et: float | None
    solution: ConicSolution
    miss_hill: float | None

    @property
    def median_error_au(self) -> float:
        return CLASS_ACCURACY_AU[self.arc_class]


@dataclass(frozen=True)
class RejectedPhase:
    """A phase that was looked at and not published, and why. Kept so a run
    reports what it declined rather than only what it produced."""

    deep_id: str
    name: str
    phase: int
    reason: str


def _preceding_body(rows: list[DeepPhase], index: int) -> str | None:
    """The body the object was under before this phase — the one whose Hill
    sphere it crossed to enter solar orbit."""
    prev = rows[index - 1] if index else None
    return prev.body if prev is not None and prev.body in ANCHOR_NAIF else None


def _boundary(body: str | None, date: GcatDate | None) -> BoundaryConstraint | None:
    """A phase end as a constraint, when GCAT names a body we can place and
    dates it precisely enough for the placement to mean anything."""
    if body is None or date is None or date.precision not in USABLE_PRECISION:
        return None
    if body not in INNER_BODIES:
        return None
    et = jd_to_et(date.jd)
    state = anchor_state(body, et)
    if state is None:
        return None
    return BoundaryConstraint(body, et, state[0], state[1], HILL_KM[body])


def _solve_from(
    elements: SolarElements,
    anchor: BoundaryConstraint,
    far: BoundaryConstraint | None,
) -> tuple[ConicSolution, float | None] | None:
    """Best branch through ``anchor``, ranked against ``far`` when there is one.

    Anchoring at the arrival end instead, or taking whichever end reached the
    other more closely, was measured across 56 phases with archive
    trajectories: fifteen improved, fifteen worsened, and the median did not
    move. Departure always, and the extra branch is not worth its complexity."""
    solutions, failure = solve_anchor(
        elements,
        anchor.position_km,
        anchor.velocity_kms,
        anchor.et,
        tolerance_km=anchor.hill_km + APSIS_ROUNDING_AU * AU_KM,
    )
    if not solutions:
        return None
    pick = choose_branch(solutions, far)
    return pick, branch_score(pick, far) if far is not None else None


def solve_object(
    obj: DeepObject, rows: list[DeepPhase]
) -> tuple[list[SolvedArc], list[RejectedPhase]]:
    """Solve every publishable solar phase of one object. ``rows`` is that
    object's phase table; it is sorted here. Caller owns the kernel pool."""
    ordered = sorted(rows, key=lambda p: p.phase)
    arcs: list[SolvedArc] = []
    rejected: list[RejectedPhase] = []

    def drop(p: DeepPhase, reason: str) -> None:
        rejected.append(RejectedPhase(obj.deep_id, obj.name, p.phase, reason))

    for index, phase in enumerate(ordered):
        if phase.body != "Sun":
            continue
        if phase.elements is None:
            drop(phase, "no_elements")
            continue
        if phase.start is None:
            drop(phase, "no_start_date")
            continue
        if phase.start.precision not in USABLE_PRECISION:
            drop(phase, "start_too_coarse")
            continue

        anchor_body = _preceding_body(ordered, index)
        if anchor_body is None:
            drop(phase, "no_anchor_body")
            continue
        if anchor_body not in INNER_BODIES:
            drop(phase, "outer_anchor")
            continue

        arrival_body = phase.arrival_body
        if arrival_body is not None and arrival_body == anchor_body:
            drop(phase, "returns_to_anchor")
            continue

        departure = _boundary(anchor_body, phase.start)
        if departure is None:
            drop(phase, "no_anchor_ephemeris")
            continue
        arrival = _boundary(arrival_body, phase.end)

        solved = _solve_from(phase.elements, departure, arrival)
        if solved is None:
            drop(phase, "no_conic_through_anchor")
            continue
        pick, miss = solved

        arcs.append(
            SolvedArc(
                deep_id=obj.deep_id,
                name=obj.name,
                phase=phase.phase,
                arc_class=ArcClass.TRANSFER if arrival else ArcClass.OPEN,
                anchor_body=anchor_body,
                arrival_body=arrival_body if arrival else None,
                start_et=departure.et,
                end_et=arrival.et if arrival else None,
                solution=pick,
                miss_hill=miss,
            )
        )
    return arcs, rejected


__all__ = ["ArcClass", "SolvedArc", "solve_object"]
