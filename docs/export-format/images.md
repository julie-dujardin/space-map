# Images

Sourced from Wikimedia Commons (Wikidata P18 image + P154 logo for objects; P18 image + P242 locator map for IAU nomenclature features) and Wikipedia pageimages across all supported languages. Downloaded during the `commons` download step; the export step generates per-image thumbnail bundles.

At selection time (ingest) candidates redundant with the app's own rendering are dropped using the Commons `Categories` metadata: orbit/trajectory diagrams, Solar-System schematic & size-comparison diagrams (including localized text-baked variants), and locator maps. Small-body radar / shape-model renders (asteroid/NEO radar) are kept but tagged `kind: "radar"` so they can be filtered once 3D shape rendering replaces them — planetary surface radar maps (Magellan/Venus, Cassini/Titan) are real imagery and stay `photo`. Country groups draw images only from their member objects (their own Wikidata image is a geographic locator map, irrelevant here).

**Path:** `v1/images/{filename}/{label}.{ext}` (+ `sidecar.json.gz` / `metadata.json.gz`, see below)

Each servable image is materialized as its own directory, keyed by the original Commons filename. The directory contains one or more size variants; viewer metadata rides inside the variants' EXIF so the deploy doesn't spend a Workers-assets file slot per image on a metadata file.

## Size variants

| Label | Max dimension |
|-------|---------------|
| s     | 512 px        |
| m     | 1024 px       |
| xl    | 4096 px       |

Which labels appear — and what extension each carries — depends on the source format:

| Source                        | Downscaled buckets | Resting bucket (first ≥ source dim) |
|-------------------------------|--------------------|-------------------------------------|
| `.jpg` / `.jpeg`              | lossy webp         | verbatim `.jpg` (re-encoding lossy just degrades) |
| `.png` and other lossless     | lossy webp         | lossy webp at source dim            |
| animated `.gif` (n_frames > 1)| animated AVIF      | animated AVIF at source dim         |
| static `.gif`                 | lossy webp         | lossy webp at source dim            |
| `.svg`, `.webm`               | —                  | verbatim `xl.<ext>` (size-capped at 25 MiB) |
| `.pdf`, `.stl`, `.djvu`       | — (skipped entirely — not renderable as thumbnails)       ||

Buckets strictly above the resting bucket are not emitted (no upscaling). The `variants` field on each `ObjectImage` records `{label: ext}` for the emitted set.

## Attribution tier (`ObjectImage.attr`)

Each entry carries an `attr` tier derived from the Commons `LicenseShortName`, so consumers can pick images for surfaces that can't display a credit (Open Graph / social cards) without fetching per-image metadata:

| `attr` | Meaning | Example licenses |
|--------|---------|------------------|
| `free`   | No credit required | CC0, Public domain / PD-*, "No restrictions", "Copyrighted free use" |
| `credit` | Usable with a text credit | CC BY, CC BY-SA, "Attribution", GODL, KOGL, OGL, FAL |
| `other`  | Can't be honoured in a card | copyleft software licenses (GPL), unknown/missing |

NC/ND/fair-use never appear — they're dropped at download. The credit string (artist + license) lives only in the per-image metadata, so a `credit` consumer resolves it for the single image it actually uses.

## Per-image metadata

Embedded in every raster variant as an EXIF ImageDescription with the envelope `SPACEMAP-META:v1:<byte-len>:<json>`. The JSON is ASCII-escaped, so clients byte-scan for the sentinel and slice out `<byte-len>` bytes — no EXIF parser and no extra request (the variant is usually already in the HTTP cache from display). Verbatim-copied JPEGs get the segment spliced in losslessly; SVG/WebM passthrough can't embed, and oversize payloads (JPEG APP1 caps a segment at 64 KiB) aren't embedded, so those bundles ship a deployed `v1/images/{filename}/sidecar.json.gz` fallback with the same payload.

```typescript
interface ImageMetadata {
  source_url: string;    // Commons file page URL
  license?: { name?: string; url?: string };       // from Commons extmetadata
  artist?: string | { [lang: string]: string };    // multilang or bare string
  description?: string | { [lang: string]: string };
  date?: string;         // ISO-truncated creation date: "YYYY-MM-DD" | "YYYY-MM" | "YYYY"
  depicts?: string[];    // Wikidata QIDs from Commons SDC P180 ("depicts")
}
```

`metadata.json.gz` in the same directory holds this payload plus bundle bookkeeping (`schema`, `variants`, source `width`/`height`) and doubles as the completion/skip marker — it stays on disk for every bundle but is excluded from deploys via `.assetsignore`.

`artist` and `description` are aggregated across the chosen image's derivative tree (chosen-file values win; tree members reachable via Commons `{{derived from}}` / `{{Other versions}}` fill in missing entries — per-locale for multilang dicts). `date` and `depicts` are also tree-aware but use whole-value fallback: the chosen file wins outright if it has any value, otherwise the closest tree member with one supplies it. `date` prefers the structured SDC P571 inception (truncated to its declared precision) and falls back to free-form `DateTimeOriginal`.

Bundles are reused across runs; schema mismatches trigger per-image regeneration (to force a full rebuild, wipe `v1/images/`). Bundles no longer referenced by any object/feature/group selection are pruned at the end of each export.
