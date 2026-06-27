# Chebyshev payload (format byte = 1)

High-accuracy polynomial ephemeris for bodies that a user zooms in on — the
Sun, planets, dwarf planets, planetary-system barycenters, the 16 sb441-n16
asteroid perturbers, and ~30 whitelisted surface-feature moons. Each
(zone, time-chunk) pair is one gzipped binary at
`position/{zone}/{chunk}.bin.gz` (only the multi-zoom `major` zone keeps a
`/0/` zoom segment: `position/major/0/{chunk}.bin.gz`); the per-body header carries `id_type` +
`obj_id_value` so consumers rebuild the full `{prefix}-{numeric}` Object ID
(e.g. `spkid-20134340` for Pluto) without a sidecar file. Evaluate with
Clenshaw's recursion on the Chebyshev basis.

Non-whitelisted moons (tiny irregulars, inner shepherds without surface
features) don't appear here — they're covered by the `moons` elements zone
with secular drift columns (`om_dot`, `w_dot`), populated via a numerical
mean-element fit at extraction time so the orbit captures J2/J4 secular
precession without shipping per-frame Chebyshev coefficients.

## Zones

Two tiers; the coarse set shares chunk cadence across zones, while moons
ship per-zone (per-parent) cadence so each chunk lands at ~200 KB regardless
of body density.

**Coarse, always-loaded set** (5y chunks, ~20 chunks over 100y):
- `major` — Sun, planets, dwarf planets, planetary-system barycenters.
- `major_asteroids` — the ~15 sb441-n16 perturber asteroids (Pallas, Vesta,
  Juno, Hebe, Iris, Hygiea, Eunomia, Psyche, Amphitrite, Europa-asteroid,
  Cybele, Sylvia, Thisbe, Davida, Interamnia — Ceres is in `major` as a
  dwarf planet).

**Per-system moons** — one zone per parent, each with its own `chunk_years`:
- `moons/earth` — the Moon (5y chunks).
- `moons/mars` — Phobos, Deimos (0.5y chunks).
- `moons/jupiter` — Galileans + Amalthea, Thebe (0.5y chunks).
- `moons/saturn` — 21 named bodies including ring shepherds and co-orbital
  Trojans (0.125y chunks; densest population).
- `moons/uranus` — 5 majors + 4 close-in chaotic shepherds (0.25y chunks).
- `moons/neptune` — Triton, Proteus + 4 close-in shepherds (0.25y chunks).
- `moons/pluto` — Charon, Nix, Kerberos, Styx (2y chunks).

Per-zone chunk cadence (`chunks`, `chunk_years`, `start_jd`, `end_jd`) lives
on the zone's manifest entry with `shape: "chunked"` — under `zooms[0]` for
the multi-zoom `major` zone, directly at zone level for the flat cheby zones
(`major_asteroids`, `moons/{parent}`).

## Chebyshev extension (8 bytes, offsets 24..31)

| Offset | Type    | Field |
|--------|---------|-------|
| 24     | uint32  | body_count |
| 28     | uint32  | Reserved (zero) |

## Per-body header (24 bytes, repeats body_count times)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | int32   | naif_id (SPICE-side identifier; used for parent linking and frame indexing) |
| 4      | int32   | parent_id (orbital reference body) |
| 8      | int32   | obj_id_value (numeric portion of the full `Object.id`; equals naif_id when id_type=naif) |
| 12     | float32 | radius_km (NaN if unknown) |
| 16     | uint16  | coeffs_per_axis (= polynomial degree + 1, per segment) |
| 18     | uint8   | id_type (`0 naif, 1 spkid, 2 norad_satcat, 255 unknown` — same ordinals as the elements extension byte) |
| 19     | uint8   | has_localized (1 iff the body has a localized detail bundle in at least one language) |
| 20     | uint8   | object_type (`ObjectType` ordinal — same map as the elements `objectType` column) |
| 21     | uint8   | Reserved |
| 22     | uint16  | segment_count |

Combine `id_type` with `obj_id_value` to rebuild the full Object ID for
cross-referencing with the elements export and object detail bundles. Pluto
and the perturber asteroids ride as `spkid-…` even though their SPICE
`naif_id` is the planetary ID, so consumers must not assume `naif-{naif_id}`.

`object_type` lets the frontend construct full body records (with the right
rendering style) from chebyshev alone, since cheb-covered bodies don't ship
in any elements file.

## Per-segment layout

Then `segment_count` segments, each laid out as:

| Type    | Field |
|---------|-------|
| float64 | seg_start_jd (JD TDB) |
| float64 | seg_end_jd (JD TDB, exclusive) |
| float32 × N | x coefficients (c₀ … c_{N-1}) |
| float32 × N | y coefficients |
| float32 × N | z coefficients |

where N = `coeffs_per_axis`. Each segment's coefficients form a Chebyshev
series in τ ∈ [-1, 1] giving the body's position in **km, ECLIPJ2000 frame,
relative to `parent_id`**.

## Evaluating a position at time t (JD TDB)

1. For a body, pick the segment with `seg_start_jd ≤ t < seg_end_jd`
   (binary-search; segments are sorted).
2. Normalize: `τ = 2 (t - seg_start_jd) / (seg_end_jd - seg_start_jd) - 1`.
3. Evaluate each axis with Clenshaw's recursion on the coefficients.

The returned vector is parent-relative in km. Walk up the parent chain
(accumulating positions) to get SSB-relative or any other frame you need.

## Precision

Segment bounds stay float64 for JD precision (same rationale as the elements
format's `epoch_jd`). Coefficients are float32: for the time windows and
sub-interval sizes produced by the pipeline, truncation error stays well
below meter-level for planets and sub-km for inner moons — below
visualization resolution in every realistic zoom.
