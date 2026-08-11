"""Curated facts about how much ionizing radiation a place delivers.

Two tables and two models. `environments` is what a traveller absorbs standing on
a body or orbiting close to it; `belts` is the trapped-particle region a ship
crosses getting in or out, kept as geometry because the cost of a crossing
belongs to the trajectory rather than to the planet.

`schema` defines both, including the `DoseRate` wrapper that keeps the
shielding attached to the number. It reuses `Measurement` from the activity
package, which is where that qualifier type was first needed.

`field` is the cosmic ray dose everywhere the tables have no entry, which is
almost everywhere. The tables are points; the field is what joins them, and it
is kept honest by being fitted only at Earth and in cruise and then checked
against the lunar and Martian surfaces it was never shown. Trapped particles
are not in it — a belt is a table entry, not a term.

`belt_field` is the exception, and lives apart from `field` rather than inside
it so the two cannot be mistaken for equally solid. A swing-by past Jupiter is
dominated entirely by trapped particles, and it is the one thing a trajectory
planner proposes where a cosmic ray answer would be wrong by five orders of
magnitude. It is good to a factor of about four and says so.
"""
