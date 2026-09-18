# Surface imagery

This is a local data/download/processing pipeline, not an app export. It prioritizes
official preprocessed color imagery, includes partial panoramas, and retains source
files, credits, capture information, coverage, and localization evidence. No sky or
ground is synthesized. The imagery cache lives in the sibling `space-map-downloads/`
checkout, under `sources/images/panoramas/` and `derived/panoramas/`.

It covers the missions whose archives publish enough to place a panorama without
being asked twice: the Mars rovers and landers, and the Chang'e surface missions
on the Moon. The handful of curated sphere previews fitted by hand to published
flat imagery — Apollo, Venera, Huygens, Philae — are in
[other-world-panoramas.md](other-world-panoramas.md) instead.

## Collections and completeness

| Collection | Discovery scope | Output |
|---|---|---|
| `mastcamz` | Every page of ASU's full/partial mosaic gallery, plus the 360 collection | Color PNG originals, previews; numeric geometry initially unknown |
| `pancam` | Every linked page in ASU's full and small-panorama galleries for Spirit/Opportunity | Color landscape variants; separate mosaics on shared pages retained |
| `curiosity`, `spirit`, `opportunity` | All pages of NASA image-library panorama/mosaic/360 searches | Screened official color releases, including crops |
| `insight` | Curated first surface image, first/dusty/final selfies, late surface image | Five timeline frames; last exposure not claimed verified |
| `phoenix`, `pathfinder` | Official PIA13804 / PIA01466 hero panoramas | One preprocessed lander panorama each |
| Perseverance Navcam | Every PDS release inventory, supported RGB cylindrical products | Localized, north-aligned sphere textures |
| `curiosity-navcam` | Every PDS sol directory, thinned to one stopping point per 20 sols | Grayscale full/partial sphere textures with localization and north alignment |
| `spirit-mosaic`, `opportunity-mosaic` | The whole-mission mosaic index of each PDS operations volume, cylindrical Navcam and Pancam | Grayscale sphere textures, placed on the corrected traverse |
| `zhurong` | Every released NaTeCam frame, one eye of the stereo pair | Spheres mosaicked from the frames of each stop |
| `yutu-2` | Every released panoramic camera frame of Chang'e 4's rover, one eye | Lunar far-side spheres mosaicked the same way |

“Complete discovery” means traversing the specified source, **not** an exhaustive
inventory of every image ever released by a mission. Unsupported names, monochrome
products, ambiguous credits, and failed requests stay in the audit. Color variants,
overlapping crops, and multiple observations at one place are not distinct locations.
NASA search results are supplemental, not a substitute for the instrument galleries.

Curiosity also includes directly audited Photojournal masters PIA23623 and PIA26696.
These bypass the image library's smaller versions. A changed master checksum
invalidates its preview. Mastcam color is checked in the raster; the caption need
not literally contain the word “color.”

Grayscale mosaics — Curiosity Navcam and both Mars Exploration Rover cameras —
are separate collections, and the download CLI needs an explicit
`--include-monochrome` flag for them. A Pancam mosaic covers one filter, so the
colour these rovers are famous for would have to be composited from three
products at a stop; that is not implemented. Viking and raw-frame stitching are not yet
implemented. The lander timeline framework is available, but other missions' true
first/last exposures still need a dedicated audit.

## Run

From `data/`, using the project's installed Python environment:

```sh
uv run python -m space_map_data.panoramas.releases all \
  --source-dir ../../space-map-downloads/sources/images/panoramas/releases \
  --output-dir ../../space-map-downloads/derived/panoramas \
  --collections mastcamz pancam curiosity spirit opportunity insight phoenix pathfinder

uv run space-map-panoramas all \
  --source-dir ../../space-map-downloads/sources/images/panoramas \
  --output-dir ../../space-map-downloads/derived/panoramas \
  --missions perseverance

uv run python -m space_map_data.panoramas.clpds all \
  --source-dir ../../space-map-downloads/sources/images/panoramas \
  --output-dir ../../space-map-downloads/derived/panoramas \
  --missions zhurong yutu-2
```

A run takes everything the archive offers. Full-resolution originals can consume
hundreds of GB. Release downloads stop starting new files when less than 20 GiB
remains. Do not run two writers against the same collection concurrently.

- Releases support `discover`, `download`, `process`, and `all`.
- PDS supports `download`, `process`, and `all`. `--start-sol` defaults to zero;
  `--end-sol` is optional. The range bounds what a run examines again, not what
  the selection holds: sols outside it keep the products an earlier run found
  there, so a targeted re-run cannot truncate the mission.
- Completed downloads are reused by URL and SHA-256. Interrupted individual files
  restart; `.part` files are not accepted as completed images.
- `--refresh` refreshes discovery metadata. Re-running downloads retries failures
  and repairs checksum mismatches.
- HTTP 429/502/503/504 responses receive bounded retries/backoff.
- PDS `--width` sets sphere texture width, even values 256–8192; default 4096.
- Curiosity Navcam requires `--missions curiosity --include-monochrome` explicitly.
- The release-system missions support `download`, `process`, and `all`, and take
  the same `--width`. They mosaic frames rather than fetch mosaics.

### Mosaicking the frames China releases

China's Lunar and Planetary Data Release System publishes no mosaics for any of
its surface missions, only single frames, so the panoramas are built here. The
web portal is a script application but the API behind it is open, and a record's
download resolves to a direct URL on a second host.

What makes building them defensible is that each frame's PDS4 label states where
the craft stood and gives unit vectors for the four image corners and the centre.
Nothing is estimated: the frames of a stop are grouped by the sequence they were
taken in and where the craft was, and each is projected through its own camera
model. Position needs no traverse table at all.

Two conventions the archive never writes down had to be established, and both
are checked rather than assumed:

- **The pixel sign convention.** A rigid fit of the camera model onto the five
  stated directions settles it, and lands within 0.04° — under two pixels. A
  fit that misses by more than a pixel raises, because the alternative is a
  smeared sphere that still looks plausible.
- **The frame the vectors are in.** They are tagged as rover coordinates but
  are east-north-up. Reading them north-east-up mirrors every panorama about
  the meridian and still stitches seamlessly, so it cannot be caught by eye.
  Zhurong's stated yaw against the bearing it actually drove settles it, and
  the lunar labels settle it outright: they state the same position twice, once
  as latitude and longitude and once as metres from the lander, which agree to
  2 m over a kilometre. Any frame carrying both is checked on the way in.

Confirmation comes from a source never used to build the sphere: on Mars the
brightest horizon sky falls within 1-10° of the solar azimuth the label states,
wherever the sun is inside a sweep.

Three surface missions the release covers are left out. Chang'e 3 publishes its
frames with no label at all, so nothing states where Yutu stood or looked. The
Chang'e 5 and 6 landers aim their panoramic camera at the sampling area and at
themselves, a dozen frames deep on ground a metre away; those stitch, but a
camera that turns about its mast rather than its lens sees near ground from a
different place in each frame, and the result pictures the lander's own deck
rather than a view from it.

The stated pointing is where a sweep starts, not where it ends. Neighbouring
frames of one Zhurong sweep disagree by about a degree where they overlap, and
the lens stands some 18 cm off the mast axis, so ground a few metres away
shifts by two degrees from one frame to the next. `registration.py` measures
the overlaps and solves one small rotation for each frame. The lens positions
come from the label: they are east-north-up like the pointing vectors, which
the overlaps confirm — the mirrored reading misses them by half a degree, and
a lens taken to sit on the axis by a full one. The ground is taken as a level
plane at the height the label states, so each piece of ground lands at one
place on the sphere whichever lens saw it. A sweep keeps its stated pointing
when its overlaps hold too little texture, or when the solution fits them no
better than the label does; the metadata records which under
`source_coverage.registration`.

Matches near the horizon carry the solve; the steep near field holds the
craft's own deck and wheels, which no plane models, and a fit that chased them
put a step in the horizon. The overlaps cannot see a turn of the whole sweep,
so that stays as the label states it. The release also files some exposures twice under two frame numbers;
one exposure counts as one frame.

Each point of the sphere comes from the one frame that looks most squarely at
it, with a straight edge where the next frame takes over, as in the archives'
own mosaics. The seams and the exposure steps between frames are kept, and so
is the parallax of whatever stands above the ground, the rover's own deck first
of all. A panoramic camera is a stereo pair and one eye covers the sphere, so
only one is read.

### Where the Spirit and Opportunity mosaics live

Both rovers have the same operations mosaic volume the later missions have:
`mer2om_0xxx` for Spirit and `mer1om_0xxx` for Opportunity, under
`planetarydata.jpl.nasa.gov/img/data/mer/`. Each indexes its whole mission in one
`index/rdrindex.tab`, so there are no sol directories to crawl, and the
cylindrical Navcam and Pancam entries are the same angular projection the later
Navcam mosaics use.

Three things differ from the later archives:

- The label is attached to the front of the raster rather than delivered beside
  it, and a whole mosaic can reach tens of megabytes. Only the first 64 KiB is
  read to decide whether a product is usable.
- The label states the site its projection is referenced to but never the drive.
  Three things can supply it, in order: the `.nav` pointing-correction file,
  which states the rover position outright; the `.lis` input list, whose source
  frame names each carry their own site and drive; and failing both, a sol the
  rover held one stop for. About half the mosaics have no pointing file, so the
  input list carries most of them.
- A Pancam mosaic covers a single filter, so a colour sweep appears as two or
  three separate grayscale products at one stop.

### Where the Perseverance mosaics live

The Imaging Node's browsable mirror at `planetarydata.jpl.nasa.gov` still serves
the release-7 delivery of `mars2020_navcam_ops_mosaic`, which stops at sol 658 in
December 2022. Its `data/sol/` directories, its collection inventory, and the
`M20_waypoints.json` panorama references on `mars.nasa.gov` all end there or
resolve to files that are no longer public.

The live archive is the bucket behind the PDS Image Atlas,
`https://d1ejlg980osaur.cloudfront.net/m20/`. One directory per release holds
only what that release delivered — `cumulative` for everything up to release 7,
then `r8` upward — and each release inventory lists the collection as of that
release. Discovery walks the release directories in order, so the first one that
lists a product is the one that stores it. The bucket denies listing and
CloudFront drops query strings, so release numbers are probed rather than
enumerated: probing starts at release 8 and stops after eight consecutive
missing directories. A release probe that answers 429 or 5xx is retried and, if
it keeps failing, aborts the run — reading a live release as missing would hand
its products to the next release, which does not serve them.

### Where the Perseverance mosaics live

The Imaging Node's browsable mirror at `planetarydata.jpl.nasa.gov` still serves
the release-7 delivery of `mars2020_navcam_ops_mosaic`, which stops at sol 658 in
December 2022. Its `data/sol/` directories, its collection inventory, and the
`M20_waypoints.json` panorama references on `mars.nasa.gov` all end there or
resolve to files that are no longer public.

The live archive is the bucket behind the PDS Image Atlas,
`https://d1ejlg980osaur.cloudfront.net/m20/`. One directory per release holds
only what that release delivered — `cumulative` for everything up to release 7,
then `r8` upward — and each release inventory lists the collection as of that
release. Discovery walks the release directories in order, so the first one that
lists a product is the one that stores it. The bucket denies listing and
CloudFront drops query strings, so release numbers are probed rather than
enumerated: probing starts at release 8 and stops after eight consecutive
missing directories. A release probe that answers 429 or 5xx is retried and, if
it keeps failing, aborts the run — reading a live release as missing would hand
its products to the next release, which does not serve them.

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
| `includes_source_grid` | The archive's own coordinate overlay is still drawn on the texture |
| `method` | How these measurements were obtained |

Sphere area uses latitude-band weights `sin(top elevation) - sin(bottom elevation)`.
Holes remain transparent. Native source dimensions are retained separately from
preview/texture dimensions. The legacy `coverage_fraction` is an unweighted canvas
fraction and remains only for compatibility.

Unknown bounds or masks produce `null`, never invented percentages. Published
full-360 coverage can establish the horizontal fields while sphere coverage remains
unknown. Processing reads the PDS Navcam coordinate underlay's declared DN,
reconstructs covered mosaic samples, and discards borders overwritten by labels.
Angular grids and labels are rendered only by the frontend.

## Approximate printed-grid geometry

ASU's cylindrical display PNGs generally have printed azimuth/elevation grids but
no machine-readable bounds. The optional estimator requires the local `tesseract`
executable and runs offline after previews have been generated:

```sh
uv run python -m space_map_data.panoramas.grid_geometry \
  --directory ../../space-map-downloads/derived/panoramas/mastcamz
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
  --source-dir ../../space-map-downloads/sources/images/panoramas/releases \
  --output-dir ../../space-map-downloads/derived/panoramas
```

Mastcam-Z observation sol/sequence IDs are matched against all corresponding
calibrated-frame gallery pages. Source frame site/drive counters must resolve to
one identical PLACES location. Missing or conflicting evidence leaves
`position: null`. There is no nearest-sol or nearest-waypoint fallback.

A multi-sol hero panorama names no sequence, so it is placed by its capture
interval instead. PLACES records one row per drive step: a sol with no row is a
sol the rover did not move on, which makes it the clearest case rather than an
unknown one. Such a panorama is placed when the position the rover already stood
at, together with every drive step inside the interval, is one position.

Results and query hashes are stored in `localizations.json`. After regenerating
previews, reapply them offline with the same command plus `--apply-only`.
Positions refer to the rover, not the exact camera center; `uncertainty_m: null`
means unspecified, not zero.

### The Spirit and Opportunity traverse

The PDS Rover Motion Counter bundle carries only wheel odometry, which drifts
over a mission-long drive; the science team corrected both traverses against
orbital imagery, and the Analyst's Notebook publishes the result as
[MERA_traverse.csv](https://an.rsl.wustl.edu/merb/merxbrowser/meri/MER/traverse/MERA_traverse.csv)
and [MERB_traverse_5130.csv](https://an.rsl.wustl.edu/merb/merxbrowser/meri/MER/traverse/MERB_traverse_5130.csv),
one row per drive with its site, drive, sol interval and corrected easting and
northing.

Spirit's corrected columns are metres in an equirectangular projection and
Opportunity's are metres from its lander, so both are read as a displacement
from the landing site rather than as absolute coordinates. The landing sites are
the map-tied ones the MER
[mission catalog](https://planetarydata.jpl.nasa.gov/img/data/mer/mer1om_0xxx/catalog/mission.cat)
states: 14.5692°S, 175.4729°E for Spirit and 1.9462°S, 354.4734°E for
Opportunity, in the MOLA IAU 2000 cartographic frame. Anchoring this way keeps
the two rovers on one footing and avoids depending on an undocumented datum tie;
it agrees with the archive to within a few hundred metres over the landing site
and reproduces Opportunity's published 45.16 km odometry to 45.10 km. The table
records no elevation, so `elevation_m` is null rather than guessed.

### Placing the galleries the mosaic pipeline does not read

```sh
uv run python -m space_map_data.panoramas.place \
  --source-dir ../../space-map-downloads/sources/images/panoramas/releases \
  --output-dir ../../space-map-downloads/derived/panoramas
```

Most catalogued panoramas were kept off the map by a missing body and position,
not by a missing sphere. `place` fills both in, and never overwrites a position
an exact association already established.

A lander has one published place for its whole mission: InSight from
[Golombek et al. 2020](https://doi.org/10.1029/2020EA001248), Phoenix from the
[Analyst's Notebook landing site page](https://an.rsl.wustl.edu/phx2008/help/landing_site.htm),
Pathfinder from its own [PDS mission catalog](https://planetarydata.jpl.nasa.gov/img/data/mpf/imp/mpim_0001/catalog/mission.cat).

Spirit and Opportunity gallery panoramas are placed by sol against the same
corrected traverse the mosaics use, and only for a sol the rover spent standing
in one place. A sol it drove on covers several stops and none of them is the one
a panorama was taken from, so those stay unplaced.

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
  --directory ../../space-map-downloads/derived/panoramas
```

Open http://localhost:8765. The collection picker includes color rover images and
lander timelines. Verified/estimated sphere textures support dragging and zooming.
Images without a supported angular projection open as flat previews. Credits,
dimensions, coverage, and missing-location/approximate-geometry warnings are shown.

Generate a current count/readiness report and check catalog asset references:

```sh
uv run python -m space_map_data.panoramas.audit --directory ../../space-map-downloads/derived/panoramas
```

This writes `audit.json` in the derived directory. Counts use active catalogs,
not superseded metadata directories or rejected originals retained in the cache.

## Provenance and reuse

Originals, source metadata, and generated assets live in `space-map-downloads/`.
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
- [Perseverance Navcam PDS](https://pds-imaging.jpl.nasa.gov/beta/archive-explorer?mission=mars_2020&bundle=mars2020_navcam_ops_mosaic):
  RGB intensity mosaics and PDS4 geometry. Optional grayscale data uses
  [Curiosity Navcam PDS](https://planetarydata.jpl.nasa.gov/img/data/msl/msl_navcam_mosaic/)
  and its PLACES table.

China's release states no reuse terms this project can rely on, so the Zhurong
and Yutu-2 spheres stay in the cache. Where each craft stood, and when, is
measurement its labels state, so each stop is exported as a place on the
traverse instead: dated, credited to the release, and marked
`imagery: "withheld"`. The map draws those traverses and the viewer has nothing
to open on them, so the gallery leaves them out.

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
PYTHONPATH=data/src python -m space_map_data.panoramas all --missions curiosity --include-monochrome --source-dir ../space-map-downloads/sources/images/panoramas --output-dir ../space-map-downloads/derived/panoramas
```

This covers sols 2 to the end of the archive and includes full and partial
sweeps. The archive holds more than 14,000 cylindrical candidates, so the run
needs tens of gigabytes and several hours. Other Mars grayscale instruments are
not yet automatically ingested by this command. Color collections remain available
separately and are not replaced by grayscale.
Preview: <http://localhost:8765/?collection=curiosity-navcam>.

From about sol 360 onward the detached PDS3 labels stop declaring
`MISSING_CONSTANT` and `INVALID_CONSTANT`. The VICAR image header attached to
the `.IMG` still declares both, so the reader takes them from there and rejects
only products where neither source declares them. Without this the collection
ended in 2012.

### Curiosity and InSight immersive strip previews

After processing the `curiosity` and `insight` releases, run:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.strip_spheres --directory ../space-map-downloads/derived/panoramas
```

This adds approximate immersive renditions for 21 Curiosity Mastcam releases and
InSight PIA23140 (sol 14). Every Curiosity fit is a published full circle, from
the first color panorama of August 2012 (PIA16029) to Nevado Sajama in November
2025 (PIA26696); InSight's sweep is 290°, not a full circle. PIA11241 (Ogunquit
Beach) and PIA21719 (Nathan Bridges Dune) state northwest at both ends, so their
seams are rotated to that heading.
The NASA originals retain their existing source credits and reuse provenance.
These renditions use the 2048-pixel flat previews, not the gigapixel masters.

Vertical geometry assumes a cylindrical strip with a visually estimated horizon;
vertical geometry remains uncalibrated. Murray Buttes is aligned using the caption’s north-at-both-ends statement; other headings remain unknown unless explicitly recorded. `sphere_percent` stays
null; `estimated_sphere_percent` reports masked solid angle under that assumption.
Near-black source holes and unsurveyed directions remain transparent; the mask
can also remove dark real terrain. No sky or ground is synthesized.
These products are explicitly excluded from `map_ready`.
Release processing now reapplies curated strip fits automatically. The standalone command also updates existing active catalogs without rereading the masters.

Open `http://localhost:8765/?collection=curiosity&panorama=curiosity-pia20840`
or `http://localhost:8765/?collection=insight&panorama=insight-pia23140`.
Immersive products appear before flat-only products in each collection.

### Dated Mastcam-Z 360 spheres

The manifest also fits all 53 panoramas of ASU's Mastcam-Z 360 collection, sols 3
to 1879. They are ASU's curated Mastcam-Z releases, at a longer focal length than
the Navcam mosaics that now cover the same sols. The published 360° extent comes
from the collection page; the horizon is visually estimated like every other
curated strip, and no heading is recorded.

The gallery names a sol, not an Earth date. Each capture interval therefore comes
from the Mars 2020 raw-image feed: the UTC dates of the frames returned for the
first and last sol of the sequence. A sol spans two UTC dates, so a single-sol
panorama can still carry a two-day interval. Sol 840 has no Mastcam-Z frames in
that feed; its date comes from the other instruments on the same sol.

Preview: <http://localhost:8765/?collection=mastcamz>.

```sh
uv run pytest -q tests/panoramas
uv run ruff check src/space_map_data/panoramas tests/panoramas
uv run ty check src/space_map_data/panoramas
```

Tests cover real PDS labels, partial-sphere geometry, seam wrapping, solid-angle
coverage, discovery pagination, color/variant selection, timeline endpoints/events,
mission-name ambiguity, coordinate joins, cache integrity, and printed-grid fitting.
Live source completeness and visual validation are separate from the unit tests.

### Dated Spirit and Opportunity spheres

The versioned `data/src/space_map_data/panoramas/curated_strips.json` manifest
adds 17 reviewed Pancam panoramas: 13 full sweeps and four partial sweeps
(Summit 130°, Columbia Hills 120°, Viking Crater 136°, Horizon Strip 150°).
Capture dates span 2004–2009. Multi-day acquisitions retain both endpoints,
with day precision and no assumed UTC exposure time. Sources are the linked
product captions and the [Pancam full-panorama gallery](https://pancam.sese.asu.edu/panoramas.html).

[Santorini](https://pancam.sese.asu.edu/Santorini.html) states that north is at
its center; the renderer rotates that point to the sphere seam. The existing
[Murray Buttes](https://science.nasa.gov/photojournal/rovers-panorama-taken-amid-murray-buttes-on-mars/)
fit now has its September 4, 2016 capture date and published north alignment.
Other new headings remain unknown. All new vertical fits remain approximate,
with transparent gaps and no local fill. Published mosaics can already contain
blended sky. These are immersive previews, not calibrated map-ready products.

Product-specific captions take precedence over gallery summaries: Thanksgiving
starts November 24, 2004, and Legacy ends March 5, 2004. Bonneville is excluded
because the page describes a 180° product under a 360° gallery entry. Home Plate
South is excluded because its colored missing-area fill needs a dedicated mask.
Outcrop-only views without a defensible horizon estimate remain flat.

Fits are bound to master SHA-256 hashes and restricted to active catalog IDs.
Changed masters require another geometry review. Credits and original files
are retained. To update the existing cache from the main checkout:

```sh
PYTHONPATH=data/src data/.venv/bin/python -m space_map_data.panoramas.strip_spheres \
  --directory ../space-map-downloads/derived/panoramas
PYTHONPATH=data/src data/.venv/bin/python -m space_map_data.panoramas.audit \
  --directory ../space-map-downloads/derived/panoramas
```

The audit reports dated spherical renditions and dated renditions with known
north alignment separately. Estimated geometry is still counted explicitly;
these counts describe products, not unique observing locations.

Validated cache result: 527 → 544 spherical renditions, including 10 new Spirit
and seven new Opportunity products. All 17 additions have capture dates; the
asset audit reports no missing references. Reprojection and release-regeneration
tests cover partial gaps, seam wrapping, caption heading, dates, changed-source
rejection, and active-catalog filtering.

### Validated temporal coverage

Cache result after the attached-constant fallback, the sampled Curiosity Navcam
run, and the new curated fits: 544 → 960 spherical renditions, 767 of them dated,
with no missing asset references.

| Collection | Spherical | Dated | Span |
|---|---:|---:|---|
| `curiosity-navcam` | 389 | 389 | 2012–2025, at least 20 per year after 2012 |
| `curiosity` (Mastcam color) | 21 | 21 | 2012–2025; no official full-circle release exists for 2013, 2014 or 2020 |
| `mastcamz` (Mastcam-Z color) | 246 | 53 | 2021–2026 for the dated 360 collection; the other 193 are printed-grid estimates without dates |
| `perseverance` (Navcam) | 276 | 276 | 2021–2022, the full extent of the PDS delivery |

The MSL archive's last sol directory trails the current sol by several months, so
`curiosity-navcam` ends earlier than Mastcam-Z does.

## Placing the Curiosity colour releases

All 21 Mastcam colour panoramas now export. The two things they lacked were a
position and a north.

**Position.** A colour release carries a caption, not a PDS label, so it has no
site and drive to join on. Eighteen captions state the capture sol outright;
PIA16029 (sol 2) and PIA23623 (sol 2595) are reviewed entries in
`curated_strips.json`, each dated by the sol the NASA raw-image archive gives
the same UTC day. `msl_localize` joins that sol to the PLACES stopping point the
rover ended it on:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.msl_localize \
  --directory ../space-map-downloads/derived/panoramas \
  --positions ../space-map-downloads/sources/images/panoramas/curiosity/positions.csv
```

Sixteen fall on sols the rover never drove, so the fix is exact. The other five
record the sol's drive length as `uncertainty_m` — 1.9 m at Ubajara up to 42.9 m
on sol 3871 — because the panorama could have been shot anywhere along it.

**North.** Three captions state a cardinal direction. For the rest,
`orientation` matches the release's skyline against the north-referenced Navcam
spheres from the same stopping point, and reports a score per reference:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.orientation \
  --directory ../space-map-downloads/derived/panoramas \
  --collection curiosity --references curiosity-navcam --output proposals.json
```

Blind-tested on 400 Navcam pairs with a randomised true north, the matcher lands
within 5° for 86–100% of pairs scoring 0.85 or better, and is no better than a
coin flip below that. PIA11241, whose caption gives the answer independently,
comes back 0.6° out at 0.90. Cross-instrument matches score lower than
Navcam-against-Navcam ones, so the accepted five were each reviewed against the
reference skyline rather than taken on score alone; the eight remaining stay
`orientation_status: unknown`.

| Heading | Panoramas |
|---|---|
| Published cardinal direction | PIA11241, PIA20840, PIA21719 |
| Skyline match to an archival sphere | PIA22545, PIA24269, PIA25176, PIA26363, PIA26696 |
| Unknown | the other 13 |

An unknown north is exported as `orientation: "unknown"` with a zero offset. The
viewer then draws no field-of-view wedge on the minimap and no traverse arrows
in the scene, because both would point at ground the sphere cannot vouch for.
Every one of these products also carries `geometry: "estimated"`: the sphere is
fitted to a published flat image, not read off an archive label.
