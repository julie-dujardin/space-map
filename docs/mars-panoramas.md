# Mars surface imagery

This is a local data/download/processing pipeline, not an app export. It prioritizes
official preprocessed color imagery, includes partial panoramas, and retains source
files, credits, capture information, coverage, and localization evidence. No sky or
ground is synthesized. Everything runs in the `mars-panoramas` worktree.

## Collections and completeness

| Collection | Discovery scope | Output |
|---|---|---|
| `mastcamz` | Every page of ASU's full/partial mosaic gallery, plus the 360 collection | Color PNG originals, previews; numeric geometry initially unknown |
| `pancam` | Every linked page in ASU's full and small-panorama galleries for Spirit/Opportunity | Color landscape variants; separate mosaics on shared pages retained |
| `curiosity`, `spirit`, `opportunity` | All pages of NASA image-library panorama/mosaic/360 searches | Screened official color releases, including crops |
| `insight` | Curated first surface image, first/dusty/final selfies, late surface image | Five timeline frames; last exposure not claimed verified |
| `phoenix`, `pathfinder` | Official PIA13804 / PIA01466 hero panoramas | One preprocessed lander panorama each |
| Perseverance Navcam | Complete PDS collection inventory, supported RGB cylindrical products | Localized, north-aligned sphere textures |
| `curiosity-navcam` | Bounded initial PDS batch: 50 mosaics, sols 16–131 | Grayscale full/partial sphere textures with localization and north alignment |

“Complete discovery” means traversing the specified source, **not** an exhaustive
inventory of every image ever released by a mission. Unsupported names, monochrome
products, ambiguous credits, and failed requests stay in the audit. Color variants,
overlapping crops, and multiple observations at one place are not distinct locations.
NASA search results are supplemental, not a substitute for the instrument galleries.

Curiosity also includes directly audited Photojournal masters PIA23623 and PIA26696.
These bypass the image library's smaller versions. A changed master checksum
invalidates its preview. Mastcam color is checked in the raster; the caption need
not literally contain the word “color.”

Curiosity Navcam grayscale is included in the preview as a separate collection;
the download CLI uses an explicit `--include-monochrome` flag. Viking and raw-frame stitching are not yet
implemented. The lander timeline framework is available, but other missions' true
first/last exposures still need a dedicated audit.

## Run

From `data/`, using the project's installed Python environment:

```sh
uv run python -m space_map_data.panoramas.releases all \
  --source-dir ../.panorama-data/releases \
  --output-dir ../.panorama-data/derived \
  --collections mastcamz pancam curiosity spirit opportunity insight phoenix pathfinder

uv run space-map-panoramas all \
  --source-dir ../.panorama-data/sources \
  --output-dir ../.panorama-data/derived \
  --missions perseverance
```

There is no default sample limit. Full-resolution originals can consume hundreds
of GB. Release downloads stop starting new files when less than 20 GiB remains.
Do not run two writers against the same collection concurrently.

- Releases support `discover`, `download`, `process`, and `all`.
- Release `--limit N` bounds **new download attempts**, not inventory discovery.
- PDS supports `download`, `process`, and `all`; its optional `--limit N` bounds
  selected products. `--start-sol` defaults to zero; `--end-sol` is optional.
- Completed downloads are reused by URL and SHA-256. Interrupted individual files
  restart; `.part` files are not accepted as completed images.
- `--refresh` refreshes discovery metadata. Re-running downloads retries failures
  and repairs checksum mismatches.
- HTTP 429/502/503/504 responses receive bounded retries/backoff.
- PDS `--width` sets sphere texture width, even values 256–8192; default 4096.
- Curiosity Navcam requires `--missions curiosity --include-monochrome` explicitly.

## Coverage metadata

The output canvas is not the observed field of view. For example, a 360-degree
horizon strip covers 100% of horizontal directions but only part of the sphere.

| Field under `coverage` | Meaning |
|---|---|
| `horizontal_degrees` | Angular span of the source image |
| `horizontal_percent` | Angular span / 360 × 100 |
| `observed_horizontal_percent` | Fraction of output columns with nontransparent pixels, when a mask exists |
| `sphere_percent` | Nontransparent area weighted by solid angle, when geometry and a mask exist |
| `canvas_percent` | Unweighted nontransparent texture area; **not** sphere coverage |
| `method` | How these measurements were obtained |

Sphere area uses latitude-band weights `sin(top elevation) - sin(bottom elevation)`.
Holes remain transparent. Native source dimensions are retained separately from
preview/texture dimensions. The legacy `coverage_fraction` is an unweighted canvas
fraction and remains only for compatibility.

Unknown bounds or masks produce `null`, never invented percentages. Published
full-360 coverage can establish the horizontal fields while sphere coverage remains
unknown. Some PDS mosaics include grid underlays; their coverage includes those
pixels and explicitly flags this limitation.

## Approximate printed-grid geometry

ASU's cylindrical display PNGs generally have printed azimuth/elevation grids but
no machine-readable bounds. The optional estimator requires the local `tesseract`
executable and runs offline after previews have been generated:

```sh
uv run python -m space_map_data.panoramas.grid_geometry \
  --directory ../.panorama-data/derived/mastcamz
```

It fits both grid axes, checks label agreement, spatial span, angular bounds, and
matching angular pixel scales. Failed estimates remain flat previews. Successful
estimates are **approximate, not publication-approved**: OCR can misread labels.
Inspect them visually before using them in the map.

These exploratory sphere renditions use the local preview, not the full-resolution
master. A conservative color mask excludes neutral grid marks but can also remove
real neutral pixels or retain compression fringes. Coverage and heading are marked
approximate; the master image remains untouched. Running release `process` again
rebuilds base metadata; run the grid estimator afterward.

## Localization

Perseverance's authoritative [PLACES best_interp.csv](https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_rover_places/data_localizations/best_interp.csv)
contains intermediate positions missing from the waypoint feed. Its
[specification](https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_rover_places/document/Mars2020_Rover_PLACES_PDS_SIS.pdf)
defines the best-estimate rover positions, planetocentric latitude, east-positive
longitude, and MOLA-areoid elevation.

```sh
uv run python -m space_map_data.panoramas.localize \
  --source-dir ../.panorama-data/releases \
  --output-dir ../.panorama-data/derived
```

Mastcam-Z observation sol/sequence IDs are matched against all corresponding
calibrated-frame gallery pages. Source frame site/drive counters must resolve to
one identical PLACES location. A multi-sol hero panorama can be associated only
when every sol in its capture interval is represented and all associated rover
positions are identical. Missing or conflicting evidence leaves `position: null`.
There is no nearest-sol or nearest-waypoint fallback.

Results and query hashes are stored in `localizations.json`. After regenerating
previews, reapply them offline with the same command plus `--apply-only`.
Positions refer to the rover, not the exact camera center; `uncertainty_m: null`
means unspecified, not zero. Curiosity/MER release localization remains pending.

## Stationary timelines

`timeline_select` preserves the first/last dated records in a source set, samples
approximately every two Earth years, and always retains explicitly curated
`interesting_reasons`. Undated records remain in a review queue. Publication dates
are not used as capture dates. Multi-month acquisitions retain their date interval
and precision. Being the last curated image does not establish the mission's final
camera exposure.

InSight currently includes the first surface image, clean first selfie, dusty 2019
selfie, final 2022 selfie, and the December 11, 2022 late surface image. These are
stills/selfies, not asserted to be spherical panoramas.

## Preview

```sh
uv run python -m space_map_data.panoramas.preview \
  --directory ../.panorama-data/derived
```

Open http://localhost:8765. The collection picker includes color rover images and
lander timelines. Verified/estimated sphere textures support dragging and zooming.
Images without a supported angular projection open as flat previews. Credits,
dimensions, coverage, and missing-location/approximate-geometry warnings are shown.

Generate a current count/readiness report and check catalog asset references:

```sh
uv run python -m space_map_data.panoramas.audit --directory ../.panorama-data/derived
```

This writes `audit.json` in the derived directory. Counts use active catalogs,
not superseded metadata directories or rejected originals retained in the cache.

## Provenance and reuse

Originals, source metadata, and generated assets live in ignored `.panorama-data/`.
Nothing is published, added to the app export, or included in the software license.

- [Mastcam-Z landscape collection](https://mastcamz.asu.edu/mastcam-zs-landscape-mosaic-collection/)
  and [360 collection](https://mastcamz.asu.edu/mastcam-zs-360-panorama-collection/):
  explicit public/scientific reuse, credit NASA/JPL-Caltech/ASU/MSSS. Policy HTML is cached.
- [Pancam full](https://pancam.sese.asu.edu/panoramas.html) and
  [partial](https://pancam.sese.asu.edu/mosaics.html) galleries: official mission-team
  mosaics with NASA/JPL/Cornell/Arizona State University credits. Credit pages are cached.
- [JPL image-use policy](https://www.jpl.nasa.gov/jpl-image-use-policy/): retain
  credits, do not imply endorsement, and exclude separately copyrighted material.
  NASA library releases require a recognized institutional credit; unfamiliar
  credits remain in the review queue. Direct policy caching can return 403; the
  browser-verified policy review is recorded separately in that case.
- [Perseverance Navcam PDS](https://planetarydata.jpl.nasa.gov/img/data/mars2020/mars2020_navcam_ops_mosaic/):
  RGB intensity mosaics and PDS4 geometry. Optional grayscale data uses
  [Curiosity Navcam PDS](https://planetarydata.jpl.nasa.gov/img/data/msl/msl_navcam_mosaic/)
  and its PLACES table.

Third-party stitched panoramas and AI-generated fill are not used. Color labels
distinguish natural/approximate-true, enhanced, and source color composites where
known; they are not a guarantee of human-eye color accuracy.

## Verification

### Mars grayscale coverage

Grayscale is now in scope alongside color. Curiosity Navcam outputs go to the
separate `curiosity-navcam` collection, preserving the `curiosity` Mastcam color
catalog. These official PDS cylindrical mosaics use label-derived sphere geometry
and an exact site/drive localization join, not an assumed strip projection.

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas all --missions curiosity --include-monochrome --source-dir .panorama-data/sources --output-dir .panorama-data/derived --limit 50
```

This bounded starter batch includes full and partial sweeps. Omit `--limit` for
all supported localized products; budget disk space before doing so. Other Mars
grayscale instruments are not yet automatically ingested by this command.
Color collections remain available separately and are not replaced by grayscale.
Preview: <http://localhost:8765/?collection=curiosity-navcam>.

### Curiosity and InSight immersive strip previews

After processing the `curiosity` and `insight` releases, run:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.strip_spheres --directory .panorama-data/derived
```

This adds approximate immersive renditions for Curiosity PIA20840 (Murray Buttes),
PIA23623, PIA26696 (Nevado Sajama), and InSight PIA23140 (sol 14).
Curiosity's published sweeps are 360°; InSight's is 290°, not a full circle.
The NASA originals retain their existing source credits and reuse provenance.
These renditions use the 2048-pixel flat previews, not the gigapixel masters.

Vertical geometry assumes a cylindrical strip with a visually estimated horizon;
neither that geometry nor true north has been calibrated. `sphere_percent` stays
null; `estimated_sphere_percent` reports masked solid angle under that assumption.
Near-black source holes and unsurveyed directions remain transparent; the mask
can also remove dark real terrain. No sky or ground is synthesized.
These products are explicitly excluded from `map_ready`.
Rerun this command after rebuilding release metadata.

Open `http://localhost:8765/?collection=curiosity&panorama=curiosity-pia20840`
or `http://localhost:8765/?collection=insight&panorama=insight-pia23140`.
Immersive products appear before flat-only products in each collection.

```sh
uv run pytest -q tests/panoramas
uv run ruff check src/space_map_data/panoramas tests/panoramas
uv run ty check src/space_map_data/panoramas
```

Tests cover real PDS labels, partial-sphere geometry, seam wrapping, solid-angle
coverage, discovery pagination, color/variant selection, timeline endpoints/events,
mission-name ambiguity, coordinate joins, cache integrity, and printed-grid fitting.
Live source completeness and visual validation are separate from the unit tests.
