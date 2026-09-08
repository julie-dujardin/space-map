# Moon, Venus, and Titan sphere previews

Run from the panorama worktree, using the data environment:

```sh
PYTHONPATH=data/src python -m space_map_data.panoramas.other_worlds --source-dir .panorama-data/other-worlds --output-dir .panorama-data/derived
```

Add `--offline` to rebuild from cached originals. Originals are retained with
SHA-256 recorded in each product's metadata. Rendering uses an at-most-8192-pixel
working image and outputs 4096×2048 transparent WebP spheres. Existing unrelated
entries in the Moon/Titan catalogs are preserved. No application/map integration.

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
seams. No local sky/ground synthesis or recoloring is performed. The two Apollo
capture dates are left unknown pending frame-level verification.

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

Color rights remain unresolved: the [LPI color release](https://www.lpi.usra.edu/publications/slidesets/venus/slide_3.html) and [ESA release](https://www.esa.int/ESA_Multimedia/Images/2007/11/Surface_of_Venus_by_Venera_13) credit separate rights holders. Candidates/status remain in `.panorama-data/other-worlds/review.json`.

## Preview

- <http://localhost:8765/?collection=moon&panorama=apollo16-station1>
- <http://localhost:8765/?collection=moon&panorama=apollo17-landing>
- <http://localhost:8765/?collection=titan&panorama=huygens-pia08113>
- <http://localhost:8765/?collection=venus&panorama=venera13-lpi>

Tests cover Mercator inversion, transparent sky, preservation of dark Titan
terrain, invalid dimensions, missing offline inputs, and idempotent catalog builds.
