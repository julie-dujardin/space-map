"""Where a body's rotational elements came from.

The export merges four disjoint sets into one orientation table — the IAU/NAIF
PCK constants, spin poles converted from DAMIT's lightcurve inversions, and the
occultation and photometric fits of the small bodies that appear in no kernel —
and the merged record is what the frontend renders and credits. Without this
tag every asteroid on the map credits the IAU working group for a pole it never
published.

The last two carry a named paper on the record itself; the first two are
credited to the archive they were read from.
"""

ORIENTATION_SOURCE_PCK = "pck"
ORIENTATION_SOURCE_LIGHTCURVE = "lightcurve"
ORIENTATION_SOURCE_OCCULTATION = "occultation"
ORIENTATION_SOURCE_PHOTOMETRY = "photometry"
