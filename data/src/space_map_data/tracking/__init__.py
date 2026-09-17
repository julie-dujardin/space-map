"""Ground-station network activity: who is still being talked to, and when.

Two networks, two resolutions. NASA's DSN Now publishes a live per-antenna feed
that resolves individual passes to the minute; ESA's ESTRACKnow publishes
monthly service volume per mission, and its real-time half appears dormant.
Neither covers the other's fleet, so a probe absent from one says nothing about
the other.

Anything derived from this has to carry which network saw the probe and at what
resolution — "active in September" and "last heard from at 14:32" are not the
same claim.
"""
