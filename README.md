# Space Map

Space Map is a real-time, real-scale, fully continuous map of the solar system, mapping 1,593,712 objects and 16,074 surface features as of 2026-06-27.

| | |
|:-:|:-:|
| [![Earth](docs/images/earth.png)](https://spacemap.co/b/399/Earth?at=2026-06-21T14:24:57.661Z,30.63812,-22.71399,0.0019850) | [![Mars](docs/images/mars.png)](https://spacemap.co/b/499/Mars?at=2026-06-03T05:09:05.427Z,-9.72405,91.33456,0.00093713) |
| [![Juno](docs/images/juno.png)](https://spacemap.co/p/107159552/Juno?at=2026-06-03T05:09:37.456Z,63.85408,34.68980,3.0640e-9) | [![Saturn](docs/images/saturn.png)](http://spacemap.co/b/699/Saturn?at=2020-06-02T14:10:11.542Z,39.08590,-147.48087,0.097742) |

## Features

Space Map computes positions at any date, using orbital elements from NASA, ESA, JAXA, and the US space force:

| Type | Count | Source |
| --- | --- | --- |
| Planets | 8 | [NASA SPICE kernels (NAIF)](https://naif.jpl.nasa.gov/naif/) |
| Dwarf planets | 10 | [NASA JPL Horizons](https://ssd.jpl.nasa.gov/horizons/) |
| Moons | 466 | [NASA JPL Horizons](https://ssd.jpl.nasa.gov/horizons/) |
| Asteroids | 1,519,013 | [Small-Body Database](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html) |
| Comets | 4,082 | [Small-Body Database](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html) |
| Spacecraft | 27,532 | [CelesTrak](https://celestrak.org/), [Space-Track](https://www.space-track.org/), NASA ([JPL Horizons](https://ssd.jpl.nasa.gov/horizons/), [NAIF](https://naif.jpl.nasa.gov/naif/), [PDS](https://pds.nasa.gov/)), [ESA SPICE Service](https://www.cosmos.esa.int/web/spice), [JAXA DARTS](https://darts.isas.jaxa.jp/) |
| Satellite debris | 42,601 | [CelesTrak](https://celestrak.org/), [Space-Track](https://www.space-track.org/) |
| Surface features | 16,074 | [Gazetteer of Planetary Nomenclature (IAU/USGS/NASA)](https://planetarynames.wr.usgs.gov/) |

Each of these is displayed at its current position, and shown at its real size (when known). Most asteroids, comets, and earth sats are displayed as points, but they're all clickable.

- Time control: Speed up or reverse time, go to any date.
- Collections: See all [Starlink](https://spacemap.co/g/const-starlink), [GPS](https://spacemap.co/g/const-gps), [Geostationary](https://spacemap.co/g/class-GEO) satellites, the [Jupiter Trojan asteroids](https://spacemap.co/g/class-TJN/Jupiter%20Trojan?at=now,34.60900,58.08478,131.68).
- Search: Text search & filters, infinite scroll - it's 2026, time to doomscroll [potentially hazardous objects](https://spacemap.co/b/399?f=pha).
- Historical positions for earth satellites & probes from 1959. Coverage is limited for early & non-US/EU/JA spacecraft.
- Over 100 spacecraft with 3D models: [ISS](https://spacemap.co/e/25544/International%20Space%20Station?at=now,-18.39666,1.9643e-9), [Hubble](https://spacemap.co/e/20580/Hubble%20Space%20Telescope?at=now,19.83363,-95.19624,1.9914e-9), [James Webb](https://spacemap.co/p/115347456/James%20Webb%20Space%20Telescope?at=now,54.61394,115.76731,1.9039e-9), [Juno](https://spacemap.co/p/107159552/Juno?at=2022-08-17T15:29:50.557Z,64.88818,-21.50912,1.0027e-9), [Cassini](https://spacemap.co/p/88592384/Cassini?at=2013-07-09T06:37:40.977Z,63.94176,-121.21263,2.1247e-9), [New Horizons](https://spacemap.co/p/104804352/New%20Horizons?at=2015-07-14T11:30:05.310Z,64.31879,-172.33606,4.7916e-9), [Voyager 2](https://spacemap.co/p/49000448/Voyager%202?at=1989-08-25T02:58:36.961Z,76.62626,0.66449,1.4615e-9).
- Textures for all planets, 25 moons, and 14 minor bodies; another 2,362 asteroids & comets carry a [TrueColorTools](https://github.com/Askaniy/TrueColorTools) color from spectral & taxonomic data, and ~136,000 more are shaded by their measured albedo.
- Images from Wikimedia Commons, descriptions from Wikipedia.
- Deep links: Easily share what you're looking at.
- Localization: Full localization in 12 languages, with content from Wikipedia. UI elements were localized by Claude Opus 4.8 & Fable 5.
- Credits & sources: see full attributions in the [credits page](https://spacemap.co/credits).
- Performance: Load a solar system faster than your bank can show you your balance.

## Architecture

Space Map has a hybrid serverless/bare metal on-premise architecture, allowing high performance and low cost.

```mermaid
    flowchart LR
    user((User browser))

    subgraph repo["GitHub repo"]
        fe[frontend/]
        data[data/]
    end

    subgraph ci["GitHub Actions"]
        wf_fe[frontend-deploy]
        wf_data[data-deploy]
    end

    subgraph hosts["Hosting"]
        pages[("Cloudflare Pages<br/>spacemap.co + static.spacemap.co")]
        ghcr[("ghcr.io image")]
    end

    subgraph vm["Debian VM"]
        container["space-map-data<br/>(daily data pipeline)"]
        meili["Meilisearch<br/>(search)"]
    end

    sources((CelesTrak / Space-Track / …))

    fe --> wf_fe -->|deploy| pages
    data --> wf_data -->|push image| ghcr --> container
    container -->|fetch| sources
    container -->|export static data| pages
    container -->|push index| meili

    user --> pages
    user -->|search| meili
```

Data endpoints are exported as static files served by Cloudflare pages. This allows high performance & low maintenance overhead. The exception is the search engine, which runs on a baremetal server.

The export pipeline compresses orbital elements from ~100GiB down to 1.6GiB, and splits them in chunks so the frontend can propagate the current position quickly. The loss in accuracy is significant, but very small for major objects: [planets, moons, and important small objects](docs/chebyshev-accuracy.md) and [spacecraft](docs/probe-accuracy.md) are typically off by meters to hundreds of meters.

## Other space maps

- [NASA's Eyes](https://science.nasa.gov/eyes/) - NASA's map of the solar system & nearby stars
- [celestrak.keeptrack.space](https://celestrak.keeptrack.space/) - Earth satellites
- [stuffin.space](https://stuffin-space.vader.zone/) - Earth satellites, live
- [satellitemap.space](https://satellitemap.space/) - Earth satellites, live
- [Google Maps Space](https://www.google.com/maps/space/mars) - Planets & moons, not continuous
- [If the moon were one pixel](https://joshworth.com/dev/pixelspace/pixelspace_solarsystem.html)
