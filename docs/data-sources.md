# Data sources and identifiers

## Primary keys by entity type

| Entity type | Is ID for type | Primary key | Example | Wikidata property | Provided by |
|---|---|---|---|---|---|
| Artificial satellite | ✅ | Norad CAT ID | 20580 | P377 | Celestrak |
|  | ❌ | Cospar ID | 1990-037B | P247 | Celestrak, horizons |
|  | ❌ | NAIF | -48 | P2956 | horizons |
| Probes | ✅ | NAIF | -254 | P2956 | horizons |
|  | ❌ | Cospar ID | 2003-027A | P247 | horizons |
|  | ❌ | (Norad CAT ID?) | | P377 | celestrak possibly for some entries? |
| Natural body (planet/moon) | ✅ | NAIF | 399 | P2956 | horizons |
|  | ❌ | Provisional designation | 2003J22 | P490 | horizons |
| Small body (dwarf/asteroid/comet) | ✅ | SPK ID | 20000001 | P716 | sbdb (horizons: computed from NAIF) |
|  | ❌ | MPC designation | 1; 2024 FG9 | P5736 | sbdb |
|  | ❌ | NAIF | 20000001 | P2956 | horizons (sbdb: computable from NAIF) |
| Star | ❔ | SIMBAD ID | NAME Proxima Centauri | P3083 | |
|  | ❔ | Gaia ID | 5853498713190525696 | P13228 | |
|  | ❔ | Exoplanet Archive ID | Proxima Cen | P5667 | |
|  | ❔ | Hipparcos | HIP 70890 | P528/P972 w/Q537199 | |
| Exoplanet | ❔ | Exoplanet Archive ID | Proxima Cen b | P5667 | |
|  | ❔ | SIMBAD ID | NAME Proxima Centauri b | P3083 | |
|  | ❔ | Extrasolar Planets Encyclopaedia | proxima_centauri_b--4042 | P5653 | https://exoplanet.eu/catalog/proxima_centauri_b--4042/ |
| Surface feature | ✅ | IAU Gazetteer feature ID | 162 | P2824 | |
| Any | ❌ | Wikipedia QID | Q2 | - | wikidata |

## Identifier reference

| Primary key | Tracks | Example | Link | Notes | Wikidata property | Provided by |
|---|---|---|---|---|---|---|
| Norad CAT ID | Artificial satellite, few Probes | 20580 | https://www.n2yo.com/satellite/?s=\<id\>, https://celestrak.org/NORAD/elements/graph-orbit-data.php?CATNR=\<id\> | | P377 | Celestrak |
| Cospar ID | Artificial satellite, few Probes | 1990-037B, 2003-027A | https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=\<id\>: unavailable, https://www.n2yo.com/database/?q=\<id\> | | P247 | Celestrak, horizons |
| NAIF | large bodies, small set of small bodies, Probes | 399, 20000001, -48, -254 | https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='\<id\>' | | P2956 | horizons (sbdb: computable from NAIF) |
| Provisional designation | large bodies | 2003J22 | | | P490 | horizons, sbdb |
| SPK ID | Small bodies | 20000001 | https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=\<id\> | | P716 | sbdb (horizons: computed from NAIF) |
| MPC designation | Small bodies | 1; 2024 FG9 | https://www.minorplanetcenter.net/db_search/show_object?object_id=\<id\> | | P5736 | sbdb |
| SIMBAD ID | Stars, Exoplanets | NAME Proxima Centauri, NAME Proxima Centauri b | https://simbad.u-strasbg.fr/simbad/sim-id?Ident=proxima+cen&NbIdent=1&Radius=2&Radius.unit=arcmin&submit=submit+id | Has references to HIP, Gaia DR2 & 3,  | P3083 | |
| Gaia ID | Stars | 5853498713190525696 | | May not be stable over new datasets | P13228 | |
| Exoplanet Archive ID | Stars, Exoplanets | Proxima Cen | | | P5667 | |
| Hipparcos | Stars | HIP 70890 | | | P528/P972 w/Q537199 | |
| Extrasolar Planets Encyclopaedia | Exoplanets | proxima_centauri_b--4042 | https://exoplanet.eu/catalog/proxima_centauri_b--4042/ | | P5653 |  |
| IAU Gazetteer feature ID | Surface feature | 162 | https://planetarynames.wr.usgs.gov/Feature/\<id\> | | P2824 | https://planetarynames.wr.usgs.gov/GIS_Downloads |
| Name | Any (reduced coverage) | Earth | | differs by language | name | wikidata |
| Wikipedia QID | Any (reduced coverage) | Q2 | | | - | wikidata |
