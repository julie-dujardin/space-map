"""Probe trajectory pipeline: SPICE-kernel-based spacecraft positioning.

Distinct from `download/providers/spice/bodies/`, which extracts data for
natural bodies (planets/moons/asteroids). This package handles spacecraft
specifically — refitting NAIF/ESA mission SPKs into a compact per-zone /
per-chunk export format that the frontend can stream by zoom level.

See `zones.py` for the zone partitioning and `sizing.py` for the recon
helpers that pick between Kepler and Chebyshev per (probe, chunk, zone).
"""
