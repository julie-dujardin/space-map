"""The builder: the sources in, one tree per system and its decisions out.

    systems = build(Inputs(msc=..., simbad=..., ...), resolver)

1. `prepare`: each node of a tree source takes its candidate objects. A WDS
   component with no candidate takes the object of the MSC component of the
   same WDS id and letter, and the other way round. A WDS component that
   still has none goes to `Resolver.match` by position. A planet that is
   also a star of a star catalogue stays a planet: its object leaves every
   tree. Each source's trees become groups of points and interiors. El-
   Badry's pairs become groups of two points, the Gaia orbits interiors of
   two stars. A SIMBAD component inside the light of another point joins
   that point in every source.
2. `merge`: the groups merge into one tree per system.
3. `assemble`: each point takes the interior of its first source, and a
   point that SIMBAD types as a close pair holds two stars when no companion
   explains the type. Then the nodes, the members and the decisions.
"""

import logging
import time

from space_map_data.extrasolar.systems.assemble import Systems, assemble
from space_map_data.extrasolar.systems.merge import merge
from space_map_data.extrasolar.systems.prepare import Inputs, prepare
from space_map_data.extrasolar.systems.resolve import Resolver

logger = logging.getLogger(__name__)


def build(inputs: Inputs, resolver: Resolver) -> Systems:
    started = time.monotonic()
    prepared = prepare(inputs, resolver)
    logger.info("systems: prepared in %.0f s", time.monotonic() - started)
    merged = merge(prepared.sets)
    systems = assemble(prepared, merged, inputs)
    logger.info(
        "systems: %d nodes, %d members in %.0f s",
        systems.nodes.num_rows,
        systems.members.num_rows,
        time.monotonic() - started,
    )
    return systems
