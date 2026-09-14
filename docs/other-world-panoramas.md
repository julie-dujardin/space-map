# Moon, Venus, Titan, and comet sphere previews

Curated one-off previews, each fitted by hand to a published flat image. The
mission archives that state their own geometry are in
[surface-panoramas.md](surface-panoramas.md) instead.

Run from the panorama worktree, using the data environment:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.other_worlds --source-dir ../space-map-downloads/sources/images/panoramas/other-worlds --output-dir ../space-map-downloads/derived/panoramas
```

Add `--offline` to rebuild from cached originals. Originals are retained with
SHA-256 recorded in each product's metadata. Rendering uses an at-most-8192-pixel
working image and outputs 4096×2048 transparent WebP spheres. Existing unrelated
entries in each catalog are preserved. No application/map integration.

| Collection | Product | Source | Geometry |
| --- | --- | --- | --- |
| Moon | Apollo 16 Station 1, JSC2012e052598 | 10000×1038 color Hasselblad mosaic | Assumed 360° cylindrical strip; visual horizon |
| Moon | Apollo 17 landing site, JSC2007e045384 | NASA/JSC color Hasselblad mosaic | Assumed 360° cylindrical strip; visual horizon |
| Titan | Huygens PIA08113, 2005-01-14 | 14997×10830 color DISR mosaic | Published Mercator; estimated south-to-south crop and top-edge horizon |

These are curated examples, not exhaustive coverage. Horizontal and solid-angle
coverage are estimates (`estimated_horizontal_degrees`,
`estimated_horizontal_percent`, `estimated_sphere_percent`); calibrated fields
stay null. North and map coordinates remain unknown; `map_ready` is false.
Coverage describes the rendered source footprint, not proof that every pixel was
directly measured: published mosaics can contain blended/interpolated regions.

Apollo near-black pixels are made transparent, including removed sky but possibly
also real shadows. NASA's assembly already removed sky and lens flares and blended
seams. No local sky/ground synthesis or recoloring is performed. Apollo capture dates are resolved to UTC calendar days using the source frame
sequences and activity times in the Apollo Lunar Surface Journal.

Titan is an **aerial descent mosaic from approximately 10 km altitude**, not a
ground panorama. The annotated PIA08113 figure has South labels inset from both
edges; the approximate 1/18..17/18 horizontal crop avoids repeating the overlap.
Mercator inversion uses `y = -scale * asinh(tan(elevation))`, with the top row
assumed to be the horizon. Vertical calibration remains unverified.

## Reuse and source evidence

- [NASA/JSC Apollo assembly and credit](https://www.lpi.usra.edu/resources/apollopanoramas/about/): credit NASA/JSC, panorama assembly Warren Harold.
- [Huygens product and caption](https://science.nasa.gov/photojournal/mercator-projection-of-huygenss-view/), [annotated figure](https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia08/pia08113/figures/PIA08113_fig1.jpg).
- [ESA Huygens release](https://www.esa.int/ESA_Multimedia/Images/2006/05/Mercator_projection_of_Huygens_s_view) explicitly uses the [ESA Standard Licence](https://www.esa.int/ESA_Multimedia/Terms_and_conditions_of_use_of_images_and_videos_available_on_the_esa_website). Educational/editorial/informational use only; do not classify as public domain or generally commercially reusable. Credit ©ESA/NASA/JPL/University of Arizona. Recheck rights before commercial deployment.

## Venus: grayscale partial sphere

The user has approved grayscale. The [LPI CC BY 2.0 source](https://www.flickr.com/photos/lunarandplanetaryinstitute/4089158361/) now supplies the [Venera 13 crop](https://commons.wikimedia.org/wiki/File:Surface_of_Venus_from_Venera_13.jpg). Credit the Soviet mission, Stephen Paul Meszaros for NASA, LPI, and the Commons crop by 4throck; the viewer links the license and identifies our additional crop/reprojection. This is a high-contrast 2048×553 print, not full-fidelity telemetry.

The label and print borders are cropped at source coordinates (76, 94)–(1975, 478).
[Garvin, Helfenstein and Zuber (1983)](https://www.lpi.usra.edu/meetings/lpsc1983/pdf/1123.pdf) describe a nominal 180° scan, 40° vertical field, and 50° inclination. We invert a 50° downward rotation and sample the angular scan, retaining black terrain. This gives approximately 17.1% sphere area. Horizontal coverage is calculated from occupied longitude columns, not equated with the tilted scanner's 180° sweep. Print registration, exact angular bounds and north remain uncalibrated. Unsampled regions are transparent; no terrain or sky is invented.

Color rights remain unresolved: the [LPI color release](https://www.lpi.usra.edu/publications/slidesets/venus/slide_3.html) and [ESA release](https://www.esa.int/ESA_Multimedia/Images/2007/11/Surface_of_Venus_by_Venera_13) credit separate rights holders. Candidates/status remain in `../space-map-downloads/sources/images/panoramas/other-worlds/review.json`.

## Preview

- <http://localhost:8765/?collection=moon&panorama=apollo16-station1>
- <http://localhost:8765/?collection=moon&panorama=apollo17-landing>
- <http://localhost:8765/?collection=titan&panorama=huygens-pia08113>
- <http://localhost:8765/?collection=venus&panorama=venera13-lpi>

Tests cover Mercator inversion, transparent sky, preservation of dark Titan
terrain, invalid dimensions, missing offline inputs, and idempotent catalog builds.

## Beyond-Mars expansion

The `panoramas-beyond-mars` worktree adds five lunar panoramas and one comet
camera view. The two existing Apollo products now also have capture dates.
The Moon collection includes all six Apollo landing missions:

| Product | Capture date (UTC day) | Source master |
| --- | --- | --- |
| Apollo 11 landing site | 1969-07-21 | [JSC2007e045375](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045375) |
| Apollo 12 landing site | 1969-11-19 | [JSC2007e045376](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045376) |
| Apollo 14 landing site | 1971-02-05 | [JSC2007e045377](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045377) |
| Apollo 15 Station 9A | 1971-08-02 | [JSC2007e045378](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045378) |
| Apollo 15 landing site, EVA 2 | 1971-08-01 | [JSC2007e045379](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045379) |
| Apollo 16 Station 1 | 1972-04-21 | [JSC2012e052598](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2012e052598) |
| Apollo 17 landing site, EVA 1 | 1972-12-12 | [JSC2007e045384](https://www.lpi.usra.edu/resources/apollopanoramas/pans/?pan=JSC2007e045384) |

Each product records its constituent frame range, journal activity time (MET),
and capture-date source. Activity timestamps identify the sequence, not exact
shutter times. UTC dates can differ from dates in US-local mission captions.
The [Apollo Lunar Surface Journal](https://apollojournals.org/alsj/) is now hosted
at the site [linked by NASA](https://www.nasa.gov/history/alsj-and-afj/).
These are approximate 360° cylindrical fits; horizontal bounds, horizon heights,
and north remain uncalibrated. Source shadows, seams, and lens flares are retained,
except near-black pixels removed by the existing mask.

### Comet 67P: Philae at Abydos

[ESA's CIVA camera 4 release](https://www.esa.int/ESA_Multimedia/Images/2015/07/CIVA_camera_4_view)
identifies capture on November 13, 2014. The
[instrument team](https://www.ias.u-psud.fr/en/content/first-image-comet-churyumov-gerasimenko-civa-camera-rosettas-philae-lander)
specifies a nominal 60° field of view for each CIVA camera. The 1024×1024 frame
is projected as an approximate rectilinear camera onto a transparent sphere,
covering about 8% of its area. This is a single partial view, not the full CIVA
panorama. Camera tilt, north, and lens distortion remain uncalibrated. Black
pixels are retained as shadows; only directions outside the camera are transparent.

Credit ESA/Rosetta/Philae/CIVA. The ESA Standard Licence permits educational,
editorial, and informational use; this is not marked generally commercially
reusable. Preview: <http://localhost:8765/?collection=67p&panorama=philae-civa4>.

From the main checkout, reuse the existing cache:

```sh
PYTHONPATH=data/src /var/home/julie/code/git/personal/space-map/data/.venv/bin/python \
  -m space_map_data.panoramas.other_worlds --offline \
  --source-dir ../space-map-downloads/sources/images/panoramas/other-worlds \
  --output-dir ../space-map-downloads/derived/panoramas
```

### Remaining candidates

- [Philae's complete CIVA panorama](https://blogs.esa.int/rosetta/2014/11/13/comet-with-a-view/): recover camera-by-camera placement and lander attitude; the presentation collage cannot be treated as a cylindrical strip.
- [Surveyor panoramas](https://www.nasa.gov/history/55-years-ago-surveyor-1-makes-a-soft-landing-on-the-moon/): identify original scan geometry and capture intervals before adding a rendition.
- [Additional Huygens descent mosaics](https://www.jpl.nasa.gov/images/pia06438-titans-surface/): some are overhead ground maps assembled during descent; they need their published projection inverted and must remain labeled aerial observations.
- Venera color products: reuse attribution is still unresolved; the existing grayscale scan remains available.

## Repeated terrain at lunar panorama ends

Four source mosaics extend beyond one complete turn. Reviewed terrain-feature
matches establish approximate one-turn crops in `apollo_sweep_crops.json`:

| Panorama | Original width | Retained x interval (pixels, right exclusive) | Estimated original sweep |
| --- | ---: | ---: | ---: |
| Apollo 11 landing site | 16245 | 290–15690 | 379.8° |
| Apollo 12 landing site | 16335 | 260–16190 | 369.2° |
| Apollo 15 Station 9A | 15822 | 170–15240 | 378.0° |
| Apollo 17 landing site | 16955 | 55–15235 | 402.1° |

Crops are applied to the full-resolution source before resizing and projection.
The original files and dimensions remain intact; metadata records crop bounds,
source checksum, matched terrain points, and the cropped rendition dimensions.
The angular pixel scale is computed from the retained turn, not the oversized
original. A changed source fails validation and requires another crop review.

All seven Apollo panoramas were checked. Apollo 14, Apollo 15's landing-site
view, and Apollo 16 had no sufficiently consistent repeated-terrain matches and
are left uncropped. This does not establish calibrated 360° coverage for them.
The overlap checks use SIFT matches with RANSAC and visual review; normal
processing only needs the checked-in crop manifest, not OpenCV. Source scale,
roll, lighting, and vertical seam differences remain; this is not a seamless
photogrammetric reconstruction or a north calibration.

Rebuild just the Moon collection with `other_worlds --offline --collections moon`
using the source/output paths above. Reload the preview page after rebuilding.

## Map positions

Nine of the ten non-Mars products now export. Each carries a published landing
site as its position, `geometry: "estimated"` and `orientation: "unknown"` —
none of these sweeps has a calibrated north, so the viewer shows where they were
taken without claiming which way they face.

| Product | Position | Source |
|---|---|---|
| Apollo 11, 12, 14, 15, 17 landing sites | Lunar Module coordinates | [ALSJ landing site coordinates](https://apollojournals.org/alsj/alsjcoords.html) |
| Apollo 15 Station 9A | Lunar Module, `uncertainty_m` 3500 | as above |
| Apollo 16 Station 1 | Lunar Module, `uncertainty_m` 1400 | as above |
| Venera 13 | 7.5°S, 303°E | the probe's own landing record |
| Huygens | 10.25°S, 167.68°E | [NASA Huygens probe page](https://science.nasa.gov/mission/cassini/huygens-probe/) |

The two station panoramas are placed at their lander because the journal maps
the traverse stations against local landmarks rather than coordinates; the
uncertainty is the traverse distance, so both currently sit on top of their
landing-site panorama. Station coordinates would be a worthwhile refinement.

Huygens is placed at the landing site although the mosaic was taken from about
10 km above it during descent, and stays labelled as a descent view rather than
a surface panorama.

**Philae is still not exported.** No published Abydos coordinates were found on
the ESA or NASA mission pages; without them the CIVA frame has no position. The
Rosetta imaging papers that fix the site are the place to look next.
