# Binary format — common header

Every file under `position/` starts with the same 24-byte common header,
followed by an 8-byte format-specific extension (32 bytes total before the
payload).

## Common header (24 bytes, 8-aligned)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | char[4] | Magic `SMAP` |
| 4      | uint16  | Version (10) |
| 6      | uint8   | Format: `0 = elements, 1 = chebyshev, 2 = probes` |
| 7      | uint8   | Reserved |
| 8      | float64 | `start_jd` — file validity start (JD TDB), `-Infinity` = unbounded |
| 16     | float64 | `end_jd` — file validity end (JD TDB), `+Infinity` = unbounded |

`start_jd`/`end_jd` define the window where propagation is defined for this
file. Outside it, consumers must hide every body in the file rather than call
the propagator — SGP4 diverges beyond the TLE epoch spread, and even Kepler
orbits fit from short observation arcs aren't trustworthy far out. Writers
use `±Infinity` for formats with no hard cutoff (Keplerian/parabolic orbits
are mathematical solutions); SGP4 files bound it to `min(epoch) − 14d …
max(epoch) + 14d`.
