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
stay null. `map_ready` is false. Where north and the camera's position are
known, [Map positions](#map-positions) and [North on the Moon](#north-on-the-moon)
say how.
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
[Garvin, Helfenstein and Zuber (1983)](https://www.lpi.usra.edu/meetings/lpsc1983/pdf/1123.pdf) describe a nominal 180° scan and a 50° inclination. The vertical field is 37°, as the [NSSDCA camera page](https://web.archive.org/web/2024/https://nssdc.gsfc.nasa.gov/nmc/experiment/display.action?id=1981-106D-01) states for Venera 13 and 14 (211 lines at 11′ each). We invert a 50° downward rotation and sample the angular scan, retaining black terrain. This gives approximately 15.9% sphere area. Horizontal coverage is calculated from occupied longitude columns, not equated with the tilted scanner's 180° sweep. Print registration, exact angular bounds and north remain uncalibrated. Unsampled regions are transparent; no terrain or sky is invented.

Venera 14 comes from the same LPI composite, through the [Commons crop](https://commons.wikimedia.org/wiki/File:Venera_14_surface_image.jpg) by the same user, cropped at (78, 123)–(2092, 545) of 2185×622, with the same scan geometry. It is placed at 13.25°S, 310°E, the landing site of its probe record.

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
These are cylindrical fits; horizon heights remain estimates. North and each
strip's sweep are measured ([North on the Moon](#north-on-the-moon)). Source
shadows, seams, and lens flares are retained, except near-black pixels removed by
the existing mask.

### Comet 67P: Philae at Abydos

`philae-civa` is the CIVA-P ring at Abydos, taken on 13 November 2014 between
06:13:53 and 06:14:54 UTC (the frame names of the archive data set
RL-C-CIVA-3-FSS-V1.0). ESA released all seven frames
([camera 1](https://www.esa.int/ESA_Multimedia/Images/2015/07/CIVA_camera_1_view)
to camera 7). The CIVA instrument description in the archive says the six
cameras look out 60° apart, each with a 70° field; camera 7 is camera 6's stereo
twin and is left out. ESA's [panorama with the lander drawn in](https://www.esa.int/ESA_Multimedia/Images/2014/11/Comet_panoramic_lander_orientation)
sets the frames out clockwise in camera order with their tops outward, and the
one pair with enough texture to compare (cameras 3 and 4) matches only in that
order. Each frame is projected as a rectilinear square camera, and each direction
is drawn from the camera that faces it most nearly. The ring covers about 56% of
the sphere.

The sphere is relative to the lander, which rests tilted about 30°: no north,
no level horizon, and camera tilt and lens distortion are uncalibrated. Camera 4,
the sunlit cliff, is put where the viewer first looks. ESA processed each frame
on its own, so brightness steps at the seams. Black pixels are kept as shadows.

Credit ESA/Rosetta/Philae/CIVA. The ESA Standard Licence permits educational,
editorial, and informational use; this is not marked generally commercially
reusable.

### Surveyor landers

The Planetary Society hosts Philip Stooke's reconstructions of the
hand-assembled mosaics of Surveyor 1, 3, 5, 6 and 7, under NASA's image use
policy, credit "NASA / Philip Stooke, University of Western Ontario". Each is a
4000 px greyscale sweep with the spacecraft at both ends and no stated angles or
dates. They are fitted like the Apollo sweeps: 360°, cylindrical scale, and the
horizon at the median top edge of the imaged ground (0.135, 0.058, 0.057, 0.097
and 0.061 of the height). The camera's tilt bends the horizon, most on
Surveyor 3. Surveyor 3 has a north
([North on the Moon](#north-on-the-moon)); the others are drawn with their ends
behind the opening view and claim none. Only near-black areas that reach the
edge of the image (sky, sectors never imaged) are made transparent, so the
spacecraft's shadows stay. The capture time is the landing day; the metadata
records the window up to the last transmission. Positions are the craft as LROC
images show them.

### Huygens: three more descent views

The DISR team's Poster B ([ESA](https://www.esa.int/ESA_Multimedia/Images/2006/05/Mercator_projections_of_Huygens_s_view_at_different_altitudes),
byte-identical to the [PDS copy](https://atmos.nmsu.edu/PDS/data/hpdisr_0001/DATA/HIGHER_LEVEL_DATA/POSTERS/POSTER_B.JPG))
holds Mercator views from 150, 15, 2 and 0.4 km. The 150 km view shows only
haze. The other three panels repeat their ends exactly 2400 px apart, which is
also the distance between the two South labels, so the crop between those labels
is one turn that starts at south. They are drawn north-first with
`orientation: "caption-aligned"`; the top row is taken as the horizon, as for
PIA08113. Same credit and licence as PIA08113.

From the main checkout, reuse the existing cache:

```sh
PYTHONPATH=data/src /var/home/julie/code/git/personal/space-map/data/.venv/bin/python \
  -m space_map_data.panoramas.other_worlds --offline \
  --source-dir ../space-map-downloads/sources/images/panoramas/other-worlds \
  --output-dir ../space-map-downloads/derived/panoramas
```

### Remaining candidates

- The USGS Surveyor 7 W/A sheet (camera azimuth/elevation grid printed on it) and the NASA SP-341 Surveyor 5 atlas (sectors captioned with compass directions): Surveyor with stated angles.
- The Huygens surface strip after landing (PIA08115), with the DISR camera geometry in the archive's `DISRINST.CAT`.
- Venera color products and the Soviet panoramas reprocessed by Don Mitchell: reuse attribution is unresolved or all rights reserved.

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

Every product exports with `geometry: "estimated"`. The Apollo pans sit at the
camera station (`reference_point: "camera station"`), the others at the landing
site. All lunar positions are in the LROC frame of the map's own imagery.

| Product | Position | Source |
|---|---|---|
| Apollo 11, 12, 14 landing sites | Hasselblad camera position for the pan's frames, 2–3 m | LROC Apollo spatio-temporal mapping shapefiles ([Apollo 11](https://data.lroc.im-ldi.com/lroc/view_rdr/SHAPEFILE_APOLLO_11), 12, 14) |
| Apollo 15 EVA 2, Apollo 17 EVA 1 landing sites | resected, 5 m: 19 m and 14 m north-northeast of the LM | bearings of two LM footpads in the pan, the LM at its [LROC coordinates](https://www.lroc.asu.edu/data/support/downloads/2016_LROC_Coordinates_of_Human_Features.pdf) |
| Apollo 15 Station 9A | 15 m | the journal's [annotated LROC frame](https://www.apollojournals.org/alsj/a15/a15.rille.html), matched to the LROC NAC orthophoto |
| Apollo 16 Station 1 | 8 m, southwest rim of Plum crater | the journal's LROC planimetric map ([images16](https://www.apollojournals.org/alsj/a16/images16.html)), Plum's centre measured on the LROC NAC orthophoto |
| Surveyor 1, 3, 5, 6, 7 | the craft | [LROC coordinates](https://www.lroc.asu.edu/data/support/downloads/2016_LROC_Coordinates_of_Human_Features.pdf) (Wagner et al. 2017) |
| Venera 13 | 7.5°S, 303°E | the probe's own landing record |
| Venera 14 | 13.25°S, 310°E | the probe's own landing record |
| Huygens, all four views | 10.25°S, 167.68°E | [NASA Huygens probe page](https://science.nasa.gov/mission/cassini/huygens-probe/) |
| Philae | 8.04°S, 1.60°W in the Cheops frame | Ulamec et al. (2017), as cited by [Hoang et al. (2020)](https://arxiv.org/abs/2008.03180) |

The Surveyor, Venera, Huygens and Philae traverses link to their probes in
`panoramas/missions.py`, so the probe page lists them and the viewer names the
craft. 67P has no flat map: the viewer drops the minimap there and the gallery
card shows the panorama instead.

## North on the Moon

`moon_north.json` holds each lunar pan's heading (the azimuth of the strip's
left edge), its sweep, the basis and the evidence. Two bases:

- **`sun and shadow`** (`orientation: "fitted to the Sun"`). The photographer's
  shadow lies at the antisolar azimuth, and the Sun's disc at the Sun's. Both
  come from DE440 at the frames' MET, converted through the landing's MET and
  UTC. Where both are in the strip, 180° apart, they also fix the sweep.
- **`skyline match to a terrain model`** (`orientation: "matched to a terrain
  model"`). The strip's skyline is correlated, after a 20° high-pass, with the
  horizon rendered from the camera station over the LROC NAC DTM and SLDEM2015.
  The fit searches the heading and, for a strip that is not one turn, the
  sweep. The LM and Sun glare are masked.

| Pan | Heading | Sweep | Basis | Agreement |
|---|---|---|---|---|
| Apollo 11 landing site | 209.8° | 360° | shadow | TV camera 22 m off +0.7°, solar wind sheet −0.8°, LM ~0°, flag −3.1°; skyline 210.4° |
| Apollo 12 landing site | 309.7° | 360° | Sun and shadow, 1.7° apart | flag +0.5°, LM ~0°; Surveyor crater on its bearing |
| Apollo 14 landing site | 247.4° | 345.3° | shadow and Sun 180° apart | LM centre −1.1°, flag +2.7° |
| Apollo 15 landing site | 303.7° | 327.6° | skyline, correlation 0.94 | next candidate 0.59 |
| Apollo 15 Station 9A | 275.1° | 360° | skyline, correlation 0.61 | next candidate 0.31 |
| Apollo 16 Station 1 | 256.3° | 348.1° | shadow; sweep from the skyline beyond 1.5 km | correlation 0.66, falling off by ±7° of sweep |
| Apollo 17 landing site | 228.1° | 360° | skyline, correlation 0.96 | Sun and shadow 228.3°; free sweep 360.0° |
| Surveyor 3 | 274° | 354° | skyline | camera azimuth stops 272.2° |

The three Apollo strips that were not cropped to one turn fall short of it by
12° to 32°: their ends do not meet, and the gap stays transparent. The bright
disc at the top of the Apollo 16 strip is a lens flare, not the Sun, which stood
24.5° high and above the frames.

Surveyor's TV camera turns between azimuth stops at +132° and −222°, which are
the mosaic's ends. A camera azimuth reads from the spacecraft's −Y axis,
counterclockwise from above, so the spacecraft's roll θ (SP-184 Table 3-8)
gives the heading θ − 132°. That agrees with the crater-rim skyline on
Surveyor 3 only. On Surveyors 1, 5, 6 and 7 the two disagree: their horizons
are a few degrees high and the 59 m SLDEM2015 cannot resolve them, so they stay
unoriented. Surveyor 7 has one LROC NAC stereo pair to try next.

The Huygens views are placed at the landing site although they were taken from
15 km down to 400 m above it during descent, and stay labelled as descent views
rather than surface panoramas.
