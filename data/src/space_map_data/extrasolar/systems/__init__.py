"""Star systems: one tree per system from the multiple-star catalogues.

The tree sources, in source order for the structure: Tokovinin's Multiple
Star Catalogue, SIMBAD's hierarchy, the planet catalogues' systems, the WDS,
the wide pairs of El-Badry, Rix & Heintz 2021, and the Gaia DR3 orbits. A
node is a point that holds one star, a point that holds several (an
unresolved system), or a resolved system of nodes. The builder does no I/O
on the registry: a `Resolver` gives it the objects.

Modules:
- nodes: the normal form of a tree source, and the source names
- msc, simbad, planets, wds: the tree sources
- pairs: El-Badry and the Gaia orbits, as pairs
- resolve: the resolver interface and the object facts
"""
