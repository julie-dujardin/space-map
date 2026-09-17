"""Deep Space Network activity tracking.

NASA's DSN Now feed says which spacecraft each antenna is pointed at right
now, which is the only public, continuously-updated signal of whether a probe
is still being talked to. It carries no history — a contact is gone from the
feed the moment it ends — so the record has to be built by polling and keeping
what we saw.

The feed identifies spacecraft by short DSN codes (``VGR1``, ``M20``, ``EM1``)
that map to nothing we hold. ``store`` therefore keeps a first-sighting XML
snapshot per new code, so an unknown code can be researched and linked to an
object by hand later.
"""
