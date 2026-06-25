# Probe attitude (`attitude/{probe_id}/{N}.bin.gz`)

Per-probe orientation streams, refit from NAIF CK kernels for missions that
ship an `_attitude_index.json` under `MISSIONS_DIR/<MISSION>/`. One probe →
many ~200 KB chunk files at `v1/attitude/{probe_id}/{N}.bin.gz`; the decoder
walks keyframes, accumulates `dt_seconds` to recover absolute time, and SLERPs
between bracketing pairs to get attitude at any instant in the window. Probes
without attitude kernels simply have no `attitude/` directory and no manifest
key — the frontend falls back to the static [`pointing`](objects.md) heuristic.

This is a **distinct binary** from `position/` files (magic `ATTI`, not `SMAP`,
with its own version counter) so a misrouted file can't masquerade as a
position file. Coefficient quantisation is fixed: the three kept quaternion
components are stored as `int16 × 32767` over `[-1, 1]`.

## File format (`ATTI` v2)

### Header (16 bytes, 8-aligned)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | char[4] | Magic `ATTI` |
| 4      | uint16  | Version (2) |
| 6      | uint8   | Reserved |
| 7      | uint8   | Reserved |
| 8      | float64 | `start_jd` — JD TDB of the first keyframe |

### Keyframe (11 bytes, packed back-to-back after the header)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | float32 | `dt_seconds` — offset from the previous keyframe (first keyframe = 0) |
| 4      | uint8   | `idx` — index (0..3) of the dropped quaternion component |
| 5      | int16   | `a` — a kept component × 32767 |
| 7      | int16   | `b` |
| 9      | int16   | `c` |

Smallest-three encoding: the omitted component is recovered as
`sqrt(max(0, 1 − a² − b² − c²))` and reinserted at slot `idx`. `dt_seconds` is
float32: dense streams have sub-second keyframe spacing, and an integer-second
quantum accumulated into multi-minute timeline drift across a chunk. float32
keeps sub-second precision where spacing is small and tolerates coarse seconds
over long inertial cruises. The keyframe count per file is `(len − 16) / 11`.

## Manifest entry

The writer injects an `attitude` key into the probe's `__global__` object
bundle entry (`global_data["probe-{id}"]["attitude"]`), so a deep-linked probe
can discover its streams without listing the directory:

```typescript
interface ProbeAttitude {
  frame: string;          // CK reference frame name the quaternions are expressed in
  start_jd: number;       // coverage start (JD TDB)
  end_jd: number;         // coverage end (JD TDB)
  n_keyframes: number;    // total across all files
  // Per-phase spin baselines (spin-stabilised craft, e.g. Juno), subtracted
  // before encoding so the per-keyframe stream only carries the slow residual.
  // null for a non-spinner (keyframes are raw J2000→body). A spinner that holds
  // one rate has a single entry; one that steps rate across mission phases
  // (Juno: 1↔2 RPM) has one per phase, and each file's `baseline_index` selects
  // the span active over it.
  baselines: {
    kind: "spin";
    axis: [number, number, number];            // unit spin axis (J2000)
    rate_rad_s: number;
    anchor: [number, number, number, number];  // quaternion [w, x, y, z] at phase zero
    anchor_jd: number;                          // JD of phase zero
    start_jd: number;                           // span coverage (JD TDB)
    end_jd: number;
  }[] | null;
  files: {
    name: string;
    start_jd: number;
    end_jd: number;
    n_keyframes: number;
    baseline_index?: number;  // index into `baselines`; present iff baselines ≠ null
  }[];
}
```

To reconstruct the full attitude when `baselines` is present, take the active
file's `baseline_index`, compose that span's spin baseline at time `t` (`anchor`
rotated by `rate_rad_s · (t − anchor_jd)` about `axis`) with the
SLERP-interpolated residual from the keyframe stream. Spans never share a
keyframe interpolation: each carries the boundary attitude, so the decoder
clamps rather than SLERPing across a baseline switch.

`attitude/` is not a content-versioned class — it carries no `?v=` token and
falls through to the revalidating cache default (see [Caching & versioning](metadata.md#caching--versioning)).
