# Probes payload (format byte = 2)

Spacecraft trajectories refit from NASA / ESA / NAIF-PDS SPICE kernels.
Each `(zone, chunk_idx)` file aggregates EVERY probe whose coverage
intersects the chunk's time window. Within a probe, the trajectory is
sliced into fixed-width **sub-chunks** (`subchunk_days` from the chunk
header) — each sub-chunk is independently fit as one of:

  * **Kepler pure** — 6-element snapshot at the snapshot epoch, propagated
    by `conics` (mu from the zone's central body), plus 1 anchor offset.
    Cheap (28/56 B). Used for clean heliocentric cruise where there's no
    J2 source.
  * **Kepler drift** — 6 snapshot elements + linear-fit `Ω̇, ω̇, Ṁ` + 1
    anchor offset (40/80 B). Used for J2-perturbed planetary orbiters
    (MAVEN, MEX, …); `Ṁ` absorbs any J2 mean-motion correction so the
    propagation honors secular drift without an analytic J2 term.
  * **Chebyshev** — degree-11 polynomial coefficients over a uniform
    sub-segment grid (3 axes × 12 coeffs = 144 / 288 B per segment).
    Used during flybys, maneuvers, EDLs, and other windows where Kepler
    error exceeds the zone threshold. Segment time bounds are NOT
    stored — they're implicit from the sub-chunk window divided by the
    coefficient count.
  * **Uncoverable** — placeholder when no fit produced finite output
    (typically a SPICE sampling failure mid-sub-chunk). Empty payload;
    the consumer hides the probe during that window.

A probe naturally switches methods over time — cruise on Kepler-pure,
flybys on Chebyshev, low-orbit phases on Kepler-drift.

## Probes extension (8 bytes, offsets 24..31)

| Offset | Type    | Field |
|--------|---------|-------|
| 24     | uint32  | `probe_count` |
| 28     | float32 | `subchunk_days` (from the zone's `kepler_subchunk_days`) |

`subchunk_days` is shared across every probe in the file — it's a zone
property — so it's promoted to the file header rather than repeated per
probe.

## Per-probe header (12 bytes, repeats `probe_count` times)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | int32   | `obj_id_value` — `probe_id` (combine with `id_type=PROBE` to rebuild `probe-{value}`) |
| 4      | uint8   | `id_type` (always `4` = `PROBE`; see [Object ID reconstruction](object-ids.md)) |
| 5      | uint8   | `object_type` (`ObjectType` ordinal — currently always `spacecraft`) |
| 6      | uint8   | `has_localized` (1 iff the probe has a localized detail bundle) |
| 7      | uint8   | Reserved |
| 8      | uint16  | `n_subchunks` |
| 10     | uint16  | `first_subchunk_offset` (in units of `subchunk_days`, from the chunk's `start_jd`) |

`first_subchunk_offset` lets probes start partway into a chunk without
having to ship dummy leading sub-chunks. The first sub-chunk's time bounds
are:

```
sub0_start_jd = chunk.start_jd + first_subchunk_offset * subchunk_days
sub0_end_jd   = sub0_start_jd + subchunk_days
```

Subsequent sub-chunks advance by `subchunk_days` each. No explicit
sub-chunk time bounds are stored.

## Per-sub-chunk record (8-byte header + variable payload)

Each probe's `n_subchunks` records follow its header, in time order:

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | uint8   | `method` (`0 uncoverable, 1 kepler_pure, 2 kepler_drift, 3 chebyshev`) |
| 1      | uint8   | Reserved |
| 2      | uint16  | Reserved |
| 4      | uint32  | `payload_len` (bytes following this header) |
| 8      | ...     | Method-specific payload (see below) |

`payload_len` is `uint32` because the finest-intlen Chebyshev sub-chunks
(interplanetary 7-day window × 0.03-day intlen × float64) can reach
~67 KiB and overflow a `uint16`.

## Method payloads

Coefficient dtype is **float32** by default, or **float64** when the
zone's `float64_coeffs` flag is `true` (currently only `probes/interplanetary`,
which sees Voyagers at 100+ AU where float32's ~600 km quantization floor
would dominate).

**`kepler_pure` (method = 1)** — 6 elements + 1 anchor offset:
```
[ a_km, e, i_rad, om0, w0, m0, t_anchor_offset_s ]   # 28 B (f32) or 56 B (f64)
```
The fit doesn't anchor at the sub-chunk midpoint — it anchors at
`t_snap`, the closest valid SPICE sample to the midpoint (some samples
get rejected when the orbit goes hyperbolic at flybys). `t_anchor_offset_s`
stores `t_snap - sub_t_start_et` so the consumer can reconstruct the
correct propagation epoch. Without it the implicit-midpoint assumption
costs millions of km on cruise probes.

Evaluation:
```
t_anchor = sub_t_start_et + t_anchor_offset_s
rp       = a_km * (1 - e)
position = spiceypy.conics([rp, e, i_rad, om0, w0, m0, t_anchor, mu], et)
```
where `mu` is the gravitational parameter of the zone's central body
(`fit_center_naif_id`). `conics` propagates `M` via `mu` from `t_anchor`.

**`kepler_drift` (method = 2)** — 9 elements + 1 anchor offset:
```
[ a_km, e, i_rad, om0, w0, m0,
  om_dot, w_dot, n_mean_rad_s,
  t_anchor_offset_s ]                                # 40 B (f32) or 80 B (f64)
```
Evaluate by manually drifting `om`, `w`, `M` from `t_anchor`, then calling
`conics` with `t0=et` (so it doesn't re-propagate `M`):
```
t_anchor = sub_t_start_et + t_anchor_offset_s
dt       = et - t_anchor
om_t     = om0 + om_dot * dt
w_t      = w0  + w_dot  * dt
m_t      = m0  + n_mean_rad_s * dt
position = spiceypy.conics([rp, e, i_rad, om_t, w_t, m_t, et, mu], et)
```
The fitted `n_mean_rad_s` (vs. `sqrt(mu/a³)`) bakes any J2 `Ṁ` correction
into the propagation.

**`chebyshev` (method = 3)** — `n_seg × 3 × (degree+1)` packed coefficients:
```
[ seg0_x_c0 … seg0_x_c11,
  seg0_y_c0 … seg0_y_c11,
  seg0_z_c0 … seg0_z_c11,
  seg1_x_c0 … ]                      # n_seg × 144 B (f32) or 288 B (f64)
```
`n_seg = payload_len / (3 * (degree+1) * coeff_bytes)`. Segments uniformly
divide the sub-chunk:
```
seg_dt = subchunk_days_seconds / n_seg
seg_k_start_et = sub_start_et + k * seg_dt
seg_k_end_et   = sub_start_et + (k+1) * seg_dt
```
Within a segment, evaluate each axis with Clenshaw's recursion on
`τ = 2 * (et - seg_k_start_et) / seg_dt - 1` ∈ `[-1, 1]`. Position is in
**km, ECLIPJ2000 frame, relative to the zone's `fit_center_naif_id`**:

| Zone                   | `fit_center_naif_id` | Frame center |
|------------------------|---------------------:|--------------|
| `probes/interplanetary`| 10  | Sun |
| `probes/mercury`       | 199 | Mercury |
| `probes/venus`         | 299 | Venus |
| `probes/earth-moon`    | 399 | Earth |
| `probes/mars`          | 499 | Mars |
| `probes/jupiter`       | 599 | Jupiter |
| `probes/saturn`        | 699 | Saturn |
| `probes/uranus`        | 799 | Uranus |
| `probes/neptune`       | 899 | Neptune |
| `probes/pluto`         | 999 | Pluto |

**`uncoverable` (method = 0)** — `payload_len = 0`. The consumer must hide
the probe through the sub-chunk's time window.

## Probe ID stability

`probe_id` is a synthetic int32 packing the spacecraft's inception MJD
(date of the start of its longest contiguous SPK coverage interval) plus a
per-day dedupe index:

```
probe_id = ((inception_mjd - 31412) << 12) | (dedupe & 0xFFF)
```

`31412` is the MJD of 1945-01-01. 20-bit date × 12-bit dedupe fits int32
and covers up to year ~4817 with 4096 distinct probes per inception day.

This synthetic ID exists because **NAIF integers are recycled** —
NAIF -76 was Mariner 10 in 1973 and is Mars Science Laboratory today;
NAIF -12 belongs to both LADEE and Pioneer Venus Multiprobe; NAIF -66
covers both InSight cruise and Vega-2 descent. The probe_id is pinned at
first ingest and cached at
`derived/position/tables/probe_ids.json` keyed by `(mission, naif_id)`,
so the value stays stable across DB rebuilds even when new earlier-coverage
kernels arrive.
