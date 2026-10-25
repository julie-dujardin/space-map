"""Matching by position between catalogues.

A matcher sees each row that no catalogue id links to a known object. Its
candidates are the registry positions, and the positions that earlier sources
of the same ingest gave, within a search radius of the row. The radius comes
from the row's position error and size, and from `reach`, the largest error
and size of a candidate, never from the cell. The matcher scores each pair:
lower is better, and NaN rejects the pair. Each row then takes at most one
candidate and each candidate at most one row, by best score, mutually.

Between releases of one catalogue (Gaia DR3 to DR4) a position match is not
certain enough to keep an ID. That ingest gives the new release no matcher.
Its rows claim the old release's ids from the release's own cross-matches and
neighbourhood table, so only a certain match keeps an old ID. The old release
is not ingested again, so an old ID that no row claims has no row left and
retires. This needs no code beyond claims.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


@dataclass
class Pairs:
    """Candidate pairs. Errors, sizes and magnitudes are NaN where unknown."""

    # Arcsec between the two positions at J2016.0.
    separation: np.ndarray
    row_error: np.ndarray
    row_size: np.ndarray
    row_mag: np.ndarray
    row_kind: pa.Array
    key_error: np.ndarray
    key_size: np.ndarray
    key_mag: np.ndarray
    key_kind: pa.Array


class Matcher(Protocol):
    def radius(self, error: np.ndarray, size: np.ndarray) -> np.ndarray:
        """The search radius in arcsec of rows with this error and size."""
        ...

    def score(self, pairs: Pairs) -> np.ndarray:
        """A score for each pair, lower is better; NaN rejects the pair."""
        ...


@dataclass(frozen=True)
class PositionMatcher:
    """Distance over the combined error and size, plus magnitude agreement.

    Errors and sizes are in arcsec; a size is the radius of the object's
    extent. A pair farther than `near_sigma` and than `near_arcsec` must have
    a magnitude on both sides.
    """

    n_sigma: float = 5.0
    near_sigma: float = 3.0
    near_arcsec: float = 0.0
    # The smallest error that either side counts.
    min_error: float = 0.1
    reach: float = 1.0
    max_mag_diff: float = 1.0
    # The expected row magnitude minus the candidate magnitude.
    mag_offset: float = 0.0
    mag_sigma: float = 0.3
    # (row kind, candidate kind) pairs that agree, beside equal kinds. A pair
    # with a kind missing on either side agrees.
    kinds: frozenset[tuple[str, str]] = frozenset()

    def _error(self, error: np.ndarray) -> np.ndarray:
        return np.fmax(error, self.min_error)

    def radius(self, error: np.ndarray, size: np.ndarray) -> np.ndarray:
        extent = np.hypot(self._error(error), np.nan_to_num(size))
        return self.n_sigma * np.hypot(extent, self.reach)

    def score(self, pairs: Pairs) -> np.ndarray:
        error = np.hypot(self._error(pairs.row_error), self._error(pairs.key_error))
        size = np.hypot(np.nan_to_num(pairs.row_size), np.nan_to_num(pairs.key_size))
        sigma = pairs.separation / np.hypot(error, size)
        mag_diff = np.abs(pairs.row_mag - pairs.key_mag - self.mag_offset)
        both_mags = np.isfinite(mag_diff)
        ok = sigma <= self.n_sigma
        ok &= ~both_mags | (mag_diff <= self.max_mag_diff)
        near = (sigma <= self.near_sigma) | (pairs.separation <= self.near_arcsec)
        ok &= near | both_mags
        ok &= self._kinds_agree(pairs.row_kind, pairs.key_kind)
        mag_term = np.where(both_mags, (mag_diff / self.mag_sigma) ** 2, 0)
        return np.where(ok, sigma**2 + mag_term, np.nan)

    def _kinds_agree(self, row: pa.Array, key: pa.Array) -> np.ndarray:
        agree = pc.equal(row, key)
        if self.kinds:
            joined = pc.binary_join_element_wise(row, key, "\0")
            allowed = pa.array(["\0".join(pair) for pair in self.kinds])
            agree = pc.or_(agree, pc.is_in(joined, value_set=allowed))
        # A null comparison means a kind is missing.
        return agree.fill_null(True).to_numpy(zero_copy_only=False)


def assign(row: np.ndarray, key: np.ndarray, score: np.ndarray) -> np.ndarray:
    """The pairs to keep: each row and each key at most once, best score first.

    Pairs are ordered by (score, row, key). A pair is kept when it comes first
    for both its row and its key among the pairs left; the rows and keys it
    takes then leave. This gives the same pairs as a greedy pass in that order.
    Returns indexes into the inputs.
    """
    usable = np.flatnonzero(np.isfinite(score))
    alive = usable[np.lexsort((key[usable], row[usable], score[usable]))]
    kept = []
    while alive.size:
        best = np.zeros(alive.size, bool)
        _, first_of_row = np.unique(row[alive], return_index=True)
        best[first_of_row] = True
        first_of_key = np.zeros(alive.size, bool)
        first_of_key[np.unique(key[alive], return_index=True)[1]] = True
        taken = alive[best & first_of_key]
        kept.append(taken)
        alive = alive[
            ~np.isin(row[alive], row[taken]) & ~np.isin(key[alive], key[taken])
        ]
    return np.sort(np.concatenate(kept)) if kept else np.zeros(0, np.int64)
