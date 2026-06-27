# Export Format (v1 directory, position binary v10, attitude binary v1)

All files are served under `/data/v1/` and are gzip-compressed unless noted.

Every file under `position/` shares one binary format (`SMAP` v10, common
24-byte header + 8-byte format-specific extension); the format byte at offset 6
of the header dispatches between the columnar **elements** payload (Keplerian /
Parabolic / SGP4), the per-body **chebyshev** segments, and the per-probe
**probes** payload (mixed Kepler-with-drift + Chebyshev sub-chunks). One file
carries exactly one payload kind — bodies covered by chebyshev are excluded from
elements files entirely (no ride-along), since the frontend can derive
osculating Kepler elements from chebyshev positions when it needs to. Probe
**attitude** streams use a separate `ATTI` binary (see [Probe attitude](probe-attitude.md)).

## Directory structure

```
v1/
  metadata.json                                   (not gzipped) entry point — zone manifest, bundle counts, versions
  credits.json                                    (not gzipped) aggregated attribution for the /credits page
  labels/{lang}.gz                                pre-interaction labels for the promoted set (one per language)
  position/
    {zone}/[{zoom}/]{part}.bin.gz                 static parted        — small_bodies/{class} (zoomed), Earth-orbit spacecraft, small_body_moons
    {zone}/[{zoom}/]{label}/{part}.bin.gz         time-chunked + parted — earth (date label, flat), moons (chunk-idx label, flat)
    {zone}/[{zoom}/]{chunk}.bin.gz                time-chunked, unparted — chebyshev zones (only major is zoomed; major_asteroids, moons/{parent} are flat)
    probes/{zone}/{chunk}.bin.gz                  time-chunked, always flat — interplanetary probes (format byte = 2)
  attitude/{probe_id}/{N}.bin.gz                  probe orientation keyframe streams (ATTI format)
  objects/__global__/{bucket}.json.gz             global object details, hash-bucketed
  objects/{lang}/{bucket}.json.gz                 localized details, hash-bucketed
  groups/__index__.json                           (not gzipped) slug → {type, applies_to, member count}
  groups/__global__/{bucket}.json.gz              global group details, hash-bucketed
  groups/{lang}/{bucket}.json.gz                  localized group details, hash-bucketed
  groups/__orbit_samples__.json.gz                small-body orbit-class scatter samples
  groups/__sat_orbit_samples__.json.gz            earth-sat orbit-class scatter samples
  membership/earth.json.gz                        earth-sat group inverted index (slug → [object_id])
  nomenclature/positions/{body_id}.bin.gz         IAU surface-feature marker positions (SMNF format)
  nomenclature/__global__/{body_id}.json.gz       lean per-body marker metadata (name, approval_date, origin, parent_feature_id)
  nomenclature/details/__global__/{bucket}.json.gz   feature detail bundles, hash-bucketed by `{body_id}:{feature_id}`
  nomenclature/details/{lang}/{bucket}.json.gz       localized feature details, hash-bucketed
  images/{filename}/{label}.{ext}                 thumbnail variants (label = s | m | xl)
  images/{filename}/metadata.json.gz              per-image license + variants map
  textures/{id}/{tier}.webp                       tier = low | medium | high (single-frame)
  textures/{id}/{tier}_{NN}.webp                  monthly frames (type = cylindrical_monthly), NN = 01..frames
  textures/{id}/metadata.json                     texture source + exports
  textures/{id}_clouds/{tier}_{YYYYMMDDHH}.webp   cloud-overlay snapshots (type = clouds_overlay)
  textures/{id}_clouds/metadata.json              cloud-overlay source + tier/frame inventory
  textures/{id}_specular/{tier}.webp              specular/roughness map (type = cylindrical_specular)
  textures/{id}_specular/metadata.json            specular source + exports
  textures/stars/{tier}_{face}.webp               cubemap-skybox faces (type = cubemap_skybox), face ∈ px|nx|py|ny|pz|nz
  textures/stars/metadata.json                    skybox source + per-face exports
  rings/{id}/{channel}.webp                       channel = backscattered | forwardscattered | unlitside | transparency | color
  rings/{id}/metadata.json                        ring source + geometry + per-channel files
  models/{slug}/{tier}.glb                        tier = low | high — Meshopt geometry + WebP textures
  models/{slug}/metadata.json                     model kind + missions + per-tier exports (incl. credit)
  systems/global.json                             (not gzipped) always-loaded: per-body GMs + IAU nutation angles
  systems/{barycenter_id}.json                    per-system body metadata, loaded on system entry
```

## Sections

| File | Covers |
|------|--------|
| [metadata.md](metadata.md) | `metadata.json` entry point: zone manifest shapes, `shape → URL` dispatch, bundle counts, content-hash versioning & caching. |
| [zones.md](zones.md) | Zone catalogue and zoom levels; incremental-export sidecars/skip gates; the two time-segmented zones (`earth`, `moons`). |
| [position-binary.md](position-binary.md) | The 24-byte common header shared by every `position/` file, and the format-byte dispatch. |
| [elements.md](elements.md) | Elements payload (format 0): Keplerian / Parabolic / SGP4 columnar layouts, units, precision rationale. |
| [chebyshev.md](chebyshev.md) | Chebyshev payload (format 1): per-body headers, polynomial segments, evaluation. |
| [probes.md](probes.md) | Probes payload (format 2): per-probe sub-chunks (Kepler-pure / Kepler-drift / Chebyshev / uncoverable), fit centres, probe-id stability. |
| [probe-attitude.md](probe-attitude.md) | Probe orientation streams: `ATTI` binary format and the `attitude` manifest key. |
| [object-ids.md](object-ids.md) | How consumers rebuild full Object IDs (`naif-399`, `spkid-…`, `probe-…`) from the binary id-type bytes. |
| [labels.md](labels.md) | `labels/{lang}.gz` pre-interaction promoted-set labels. |
| [objects.md](objects.md) | Object detail bundles: global + localized hash-bucketed JSON schemas. |
| [groups.md](groups.md) | Group (`/g/<slug>`) detail bundles, the index, orbit-sample scatter sets, and the membership index. |
| [nomenclature.md](nomenclature.md) | IAU surface-feature markers (eager) + feature detail bundles (lazy). |
| [images.md](images.md) | Per-image thumbnail bundles, size variants, and image metadata. |
| [textures.md](textures.md) | Surface/cloud/specular/skybox textures, tiers, and metadata. |
| [rings.md](rings.md) | Ring radial-profile channels and metadata. |
| [models.md](models.md) | 3D spacecraft/satellite glTF bundles and metadata. |
| [systems.md](systems.md) | `systems/global.json` lookups + per-system `systems/{barycenter_id}.json`. |
| [credits.md](credits.md) | `credits.json` aggregated attribution manifest. |
| [consuming.md](consuming.md) | End-to-end consumer walkthrough. |
