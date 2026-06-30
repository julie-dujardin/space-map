# System files

## Systems global (`systems/global.json`)

A single tiny top-level file fetched once at app start, paired with the per-system files below. Holds context-independent lookups the frontend needs regardless of which system the user is viewing.

```json
{
  "gm": {
    "0": 1.32712440041e11,
    "10": 1.32712440041e11,
    "3": 4.0350323562548e5,
    "399": 3.98600435507e5,
    "5": 1.267127641e8
  },
  "nut_prec_angles": {
    "1": [174.791086, 4.092335, 349.582171, 8.184670],
    "3": [125.045, -0.0529921, 250.089, -0.1059842],
    "5": [73.32, 91472.9, 24.62, 45137.2]
  }
}
```

- **`gm`** — gravitational parameters (km³/s²) per body NAIF id, sourced from SPICE PCK (`gm_de440.tpc`). Includes a synthesized SSB row (`"0"`) reusing the Sun's GM so chebyshev-only bodies that orbit SSB resolve correctly. Used by the chebyshev trail-buffer sizing path to estimate orbital periods via Kepler's third law (`n = √(GM/a³)`) for any parent NAIF id.
- **`nut_prec_angles`** — IAU nutation/precession angle pairs `(θ₀, θ₁)` per "owner" body — typically the planetary system barycenter. Bodies derive their owner as `naif_id // 100` if `naif_id ≥ 100`, else `naif_id`. Each owner's array is a flat `[θ₀_1, θ₁_1, θ₀_2, θ₁_2, …]` in degrees and degrees/century. Combined with each body's `nut_prec` coefficient arrays:

  ```
  θ_i(T) = angles[2i] + angles[2i+1]·T          (T = Julian centuries since J2000)
  α(T)  += Σ nut_prec.ra[i]  · sin(θ_i(T))
  δ(T)  += Σ nut_prec.dec[i] · cos(θ_i(T))
  W(d)  += Σ nut_prec.pm[i]  · sin(θ_i(T))
  ```

## System metadata (`systems/{barycenter_id}.json`)

Generated during export (not ingest). One file per planetary system, keyed by barycenter ID (e.g. `naif-3` for Earth-Moon, `naif-5` for Jupiter). Per-body entries carry available texture tiers, texture attribution, SPICE PCK orientation (pole/spin polynomial), nutation/precession coefficients, and triaxial radii when known.

```json
{
  "naif-399": {
    "tiers": ["high", "low", "medium"],
    "texture": {
      "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/",
      "organisation": "NASA",
      "type": "cylindrical_monthly",
      "frames": 12
    },
    "clouds": {
      "id": "naif-399_clouds",
      "tiers": ["low", "medium"],
      "frames": ["2026050100", "2026050103", "..."],
      "source": "https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png",
      "organisation": "EUMETSAT",
      "type": "clouds_overlay",
      "attribution": "Contains modified EUMETSAT data"
    },
    "specular": {
      "id": "naif-399_specular",
      "tiers": ["low", "medium", "high"],
      "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/topography-bathymetry-maps/",
      "organisation": "NASA",
      "type": "cylindrical_specular",
      "attribution": "NASA Earth Observatory — Blue Marble: Next Generation topography/bathymetry maps. Bathymetry derived from GEBCO."
    },
    "orientation": {
      "pole_ra_0": 0.0, "pole_ra_1": -0.641,
      "pole_dec_0": 90.0, "pole_dec_1": -0.557,
      "w0": 190.147, "w1": 360.9856235, "w2": 0.0
    },
    "nut_prec": { "ra": [], "dec": [], "pm": [] },
    "radii": { "a": 6378.1366, "b": 6378.1366, "c": 6356.7519 }
  },
  "naif-301": {
    "tiers": ["low"],
    "texture": { "source": "…", "organisation": "NASA", "type": "cylindrical" },
    "displacement": {
      "id": "naif-301_displacement",
      "tiers": ["low", "medium", "high"],
      "scale_km": 19.9,
      "bias_km": -9.13,
      "absolute_radius": false,
      "source": "https://svs.gsfc.nasa.gov/4720/",
      "organisation": "NASA",
      "type": "cylindrical_displacement",
      "attribution": "NASA's Scientific Visualization Studio. Elevation: Lunar Orbiter Laser Altimeter (LOLA), LRO."
    }
  },
  "naif-699": {
    "rings": {
      "source": "https://bjj.mmedia.is/data/s_rings/index.html",
      "organisation": "Björn Jónsson",
      "attribution": "Saturn ring profiles created by Björn Jónsson …",
      "inner_radius_km": 74510.0,
      "outer_radius_km": 140390.0,
      "sample_count": 13177,
      "color_space": "srgb",
      "channels": {
        "backscattered":    "backscattered.webp",
        "forwardscattered": "forwardscattered.webp",
        "unlitside":        "unlitside.webp",
        "transparency":     "transparency.webp",
        "color":            "color.webp"
      }
    }
  }
}
```

The frontend fetches this when entering a system: it preloads low-res textures for every listed body, applies the full IAU rotation polynomial + nutation sums to meshes, (where `radii` differ) flattens bodies into oblate ellipsoids, and shows per-organisation imagery attribution for bodies currently in view. `texture` mirrors the shape embedded in each body's global detail file.

When a body carries a `displacement` block, the frontend loads the height map as the material's `displacementMap`. `scale_km`/`bias_km` map each texel to a value — `km = bias_km + scale_km · texel` — which the renderer converts to scene units, so relief is physically scaled and tracks the per-frame sphere-LOD tessellation. When `absolute_radius` is true the value is radius-from-centre rather than elevation: the renderer subtracts the body's own sphere radius and skips triaxial flattening, letting the DEM carry the whole shape (used for irregular bodies like Vesta and Ceres). Ships as a sibling bundle (`textures/{host_id}_displacement/`) credited independently from the surface texture.

When a body carries a `rings` block, the frontend builds an annulus aligned to its IAU pole, fetches `${DATA_BASE}/v1/rings/{body_id}/{channels[name]}` for each channel, and routes the credit fields through the same per-organisation attribution path as textures. The `channels` map is flat (channel → filename) rather than tier-nested because rings ship at a single resolution.
