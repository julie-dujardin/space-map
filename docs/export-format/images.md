# Images

Sourced from Wikimedia Commons (Wikidata P18 image + P154 logo for objects; P18 image + P242 locator map for IAU nomenclature features) and Wikipedia pageimages across all supported languages. Downloaded during the `commons` download step; the export step generates per-image thumbnail bundles.

At selection time (ingest) candidates redundant with the app's own rendering are dropped using the Commons `Categories` metadata: orbit/trajectory diagrams, Solar-System schematic & size-comparison diagrams (including localized text-baked variants), and locator maps. Small-body radar / shape-model renders (asteroid/NEO radar) are kept but tagged `kind: "radar"` so they can be filtered once 3D shape rendering replaces them — planetary surface radar maps (Magellan/Venus, Cassini/Titan) are real imagery and stay `photo`. Country groups draw images only from their member objects (their own Wikidata image is a geographic locator map, irrelevant here).

**Path:** `v1/images/{filename}/{label}.{ext}` + `v1/images/{filename}/metadata.json.gz`

Each servable image is materialized as its own directory, keyed by the original Commons filename. The directory contains one or more size variants and a gzipped metadata blob.

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

## Per-image metadata (`v1/images/{filename}/metadata.json.gz`)

```typescript
interface ImageMetadata {
  schema: number;        // bumped when variant rules or payload fields change; stale bundles are regenerated
  source_url: string;    // Commons file page URL
  variants: { [label: string]: string };  // mirrors ObjectImage.variants
  width?: number;        // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
  license?: { name?: string; url?: string };       // from Commons extmetadata
  artist?: string | { [lang: string]: string };    // multilang or bare string
  description?: string | { [lang: string]: string };
  date?: string;         // ISO-truncated creation date: "YYYY-MM-DD" | "YYYY-MM" | "YYYY"
  depicts?: string[];    // Wikidata QIDs from Commons SDC P180 ("depicts")
}
```

`artist` and `description` are aggregated across the chosen image's derivative tree (chosen-file values win; tree members reachable via Commons `{{derived from}}` / `{{Other versions}}` fill in missing entries — per-locale for multilang dicts). `date` and `depicts` are also tree-aware but use whole-value fallback: the chosen file wins outright if it has any value, otherwise the closest tree member with one supplies it. `date` prefers the structured SDC P571 inception (truncated to its declared precision) and falls back to free-form `DateTimeOriginal`.

Not cleaned on re-export — bundles are reused across runs. Schema mismatches trigger per-image regeneration; to force a full rebuild, wipe `v1/images/`.
