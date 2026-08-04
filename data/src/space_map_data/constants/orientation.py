"""Where a body's rotational elements came from.

The export merges three disjoint sets into one orientation table — the IAU/NAIF
PCK constants, spin poles converted from DAMIT's lightcurve inversions, and the
occultation poles of the four ringed small bodies — and the merged record is
what the frontend renders and credits. Without this tag every asteroid on the
map credits the IAU working group for a pole it never published.
"""

ORIENTATION_SOURCE_PCK = "pck"
ORIENTATION_SOURCE_LIGHTCURVE = "lightcurve"
ORIENTATION_SOURCE_OCCULTATION = "occultation"
