# Zones and zoom levels

**Non-SBDB zones** (zoom 0 unless noted):
- `major` zoom 0 — chebyshev for Sun, planets, Pluto, Ceres (shape `chunked`).
- `major` zoom 1 — horizons-sourced majors not in any SPK kernel; in practice
  dwarf planets with Horizons ephemerides but no chebyshev coverage.
- `major` zoom 2 — SBDB-only dwarves (Eris, Makemake, Quaoar, …) that aren't
  in any SPK kernel and still need a Kepler propagator.
- `major_asteroids` — the ~15 sb441-n16 perturber asteroids (chebyshev only).
- `moons` — non-whitelisted moons of planets with Method-C secular elements
  (chunk-indexed). Excludes SBDB-discovered satellites of small bodies — those
  ride in `small_body_moons`.
- `moons/{parent}` — whitelisted moons under each parent body, chebyshev coverage.
- `small_body_moons` — moons of asteroids/comets discovered via SBDB's
  per-object satellite payload (e.g. Dactyl around Ida, Linus around Kalliope).
  Static-parted, system-scale Keplerian. Only orbit-bearing rows ship here;
  publication-placeholder rows (no orbit) appear in object bundles for
  navigation but not in this position file. Parent ids are SPK-IDs (small
  bodies don't have NAIF IDs), surfaced in the manifest via `parent_id_type:
  "spkid"`.
- `earth` — Earth-orbiting spacecraft/debris (SGP4, date-segmented).
- `spacecraft` — spacecraft/debris orbiting other bodies.
- `probes/{zone}` — interplanetary and planetary-system probes refit from
  NASA/ESA SPICE kernels. One zone per Hill-sphere-2× region: `interplanetary`,
  `mercury`, `venus`, `earth-moon`, `mars`, `jupiter`, `saturn`, `uranus`,
  `neptune`, `pluto`. Mixed Kepler-with-drift + Chebyshev per sub-chunk —
  see [Probes payload](probes.md). A probe shows up in
  every zone its trajectory passes through (cruise + planet captures), so
  the same probe can appear in multiple zone files at different times.

**`small_bodies/{class}`** — SBDB-sourced asteroids and comets, one zone per
[orbit class](../../data/src/space_map_data/models/object/sbdb.py) (`small_bodies/APO`, `small_bodies/MBA`, `small_bodies/TJN`, …):
- Zoom 0 = named objects
- Zoom 1 = unnamed objects

Each (zone, zoom) pair may have multiple parts (10,000 objects per part).
Objects are hash-bucketed across parts by `Object.random_int` so the same id
always lands in the same part across runs — required for the per-part
incremental sidecar to be meaningful.

The shared `small_bodies/` prefix lets export wipe + prune target the whole
group as a unit: a fresh SBDB pull invalidates every part, but no other
zone's outputs are touched.

## Incremental export

Both `earth` and `small_bodies/{class}` parts carry a `{part}.meta.json`
sidecar (stored in `EXPORT_METADATA_DIR` mirror, never published) recording
the upstream snapshot that produced them:

- `earth/{date}/{part}.meta.json` — fingerprints that date's source.
  Recent CelesTrak dailies fingerprint the day's CSVs (`name + mtime_ns +
  size` per CSV); historical weekly snapshots fingerprint the Space-Track
  archive zip(s) feeding the week (`archive_inputs`). A re-downloaded day or
  re-fetched archive zip invalidates only the affected dates' parts.
- `small_bodies/{class}/{zoom}/{part}.meta.json` — fingerprints the SBDB
  download metadata (`downloaded_at + record_count + complete`). The unit
  of cacheability is the whole SBDB snapshot, so a re-download invalidates
  every `small_bodies/*` part; a no-op re-export drops the cost to a
  sidecar scan.

Both sidecar shapes carry `format_version` so a writer/encoding change
invalidates everything regardless of upstream freshness. Probes use the
same pattern at `probes/{zone}/{chunk}.meta.json` (see [Probes payload](probes.md)).

A post-export prune pass walks `position/small_bodies/` and deletes orphan
parts (and their sidecars) that this run didn't plan — covers asteroids
moving between classes, class shrinkage, or zooms disappearing.

Above the per-part sidecars sit run-level skip gates (all in the
`EXPORT_METADATA_DIR` mirror, see `export/pipeline/incremental.py`):

- `position/{zone}/__zone__.meta.json` — per-zone signature plus the
  snapshot stats `metadata.json` needs (gains a `{zoom}` segment only for the
  multi-zoom zones `major`, `small_bodies/{class}`). A matching zone skips its
  DB load and per-object build entirely, not just the re-encode.
- `position/chebyshev.meta.json` / `position/probes/__pass__.meta.json` —
  gate those whole passes behind their input fingerprints (npz tree /
  kernels + events + candidates + registry), caching the manifest fragments.
- `tier_b.meta.json` — fingerprint over everything feeding the per-object
  outputs (ingest stamp, wikidata/wikipedia/images download stamps, kernel
  tree). When it matches, bundles / labels / nomenclature details /
  messages / groups are skipped and their bucket counts reused.

Zone and pass skips require a clean tier-B fingerprint: DB- and
wikidata-derived row state (membership, `has_localized`, radius overrides)
is only tracked there. The `ingest_stamp` DB table is rewritten by every
ingest run, so any ingest invalidates tier B.

## Time-segmented zones

Two zones segment elements over time, distinguished by `label` in the
manifest:

- **`earth`** — date-segmented (`label: "date"`). Two sources share one date
  axis: recent CelesTrak dailies (one snapshot per downloaded day) and the
  historical Space-Track archive distilled to one snapshot per ISO week (the
  week's Monday is the date label; per satellite the TLE nearest the week
  midpoint is kept). Part counts vary per date, so the manifest ships
  `parts_by_date` (see Manifest shapes). Path:
  `position/earth/{YYYY-MM-DD}/{part}.bin.gz`. SGP4 accuracy degrades fast
  past the TLE epoch, so each snapshot's header `start_jd`/`end_jd` bounds it
  to `min(epoch)−14d … max(epoch)+14d`.

- **`moons`** — chunk-indexed (`label: "index"`). One snapshot per 6-month
  chunk over the Chebyshev coverage range. Method C secular elements are
  re-fitted at each chunk midpoint so Ω̇/ω̇/n_mean track multi-decade
  Kozai-Lidov-style drift on outer irregulars instead of being a single
  linear approximation across the whole range. Path:
  `position/moons/{chunk_idx}/{part}.bin.gz`. Compute the chunk index from
  a JD with `floor((jd - start_jd) / (chunk_years * 365.25))`. Header
  `start_jd`/`end_jd` bound the chunk's validity window. Whitelisted moons
  are absent from `moons` — they ride in their parent's chebyshev zone
  instead.
