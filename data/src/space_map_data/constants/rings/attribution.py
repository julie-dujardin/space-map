"""Attribution primitives shared by the ring render bundles and the catalogue."""

from typing import NamedTuple


class RingSource(NamedTuple):
    """One work a bundle or catalogue draws on. Both usually mix several —
    boundaries from one table, vertical extents from another — so each states
    what it contributed rather than the whole claiming a single origin.

    Several bundles of one body routinely cite the same work for different
    things; the credits export merges those into a single row, which is why
    ``contribution`` is a bare noun phrase and the work is named separately.
    """

    url: str
    # Kept short so the same body reads as one name across the credit UI:
    # "NASA", not "NASA PDS Ring-Moon Systems Node / NSSDCA".
    organisation: str
    license: str
    # Title of the work itself, e.g. "NSSDCA Saturnian Rings Fact Sheet".
    work: str
    # Lowercase noun phrase: what this work gave *this* bundle.
    contribution: str


NASA = "NASA"
# Matches the plain wording every other bundle uses; the organisation column
# already carries the "who".
NASA_LICENSE = "Public domain"

IAU = "IAU"
IAU_LICENSE = "Public domain"
