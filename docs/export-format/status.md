# Status (`status.json`)

Data-freshness report read by the standalone `/status` page: one row per
download provider, saying when that source was last pulled. A single
non-gzipped JSON file, written by `export/status.py` on every full export and
by `space-map-export --only status` on its own.

Each row is the provider's `metadata.json` (written by
`Downloader._save_metadata` into its output tree) joined with the display
metadata in `SOURCE_CATALOG`.

```typescript
interface Status {
  generated_at: string;          // ISO 8601 UTC — when this file was written
  categories: string[];          // render order; the frontend holds the localized names
  sources: Array<{
    id: string;                  // provider id, matching PROVIDERS ("celestrak", "sbdb", …)
    label: string;               // proper noun, shipped untranslated
    homepage: string;            // where a reader goes to see the source itself
    category: string;            // one of `categories`
    derived?: true;              // synthesised from data already on disk, not fetched
    due_after_days?: number;     // age past which the scheduler should have refreshed the row; absent when a complete download is trusted indefinitely
    downloaded_at?: string;      // ISO 8601 UTC; absent = never downloaded here
    checked_at?: string;         // ISO 8601 UTC; only when it differs from `downloaded_at` (SBDB)
    record_count?: number;       // provider-defined unit — rows, files or bodies
  }>;
}
```

Notes:

- **Rows are never dropped.** A provider that has never run keeps its row
  without dates, so the page can say so rather than staying silent.
- **`downloaded_at` vs `checked_at`.** Most providers move `downloaded_at` on
  every successful run. SBDB moves it only when the mirror content changed and
  reports `checked_at` for the last completed sync, so a row with both is fresh
  even when `downloaded_at` is old.
- **`record_count` is not comparable between sources.** Each provider counts
  what it fetches: catalogue rows for SBDB, mirrored files for the SPICE
  mission archives, texture channels for the ring profiles.
- **`derived` rows track a pipeline step, not an upstream.** Their date says
  when the synthesis last ran; `homepage` points at the data it was built from.
- **`due_after_days` is the provider's window plus the scheduler's revisit
  period** (one day for daily jobs, the interval for interval jobs). A row
  older than that has been missed by the scheduler, not merely expired.
- One-shot pulls that never expire (`UNLISTED` in `export/status.py`) get no
  row; there is no freshness to report.
- Panorama products are not covered — they carry per-product metadata rather
  than one record per source.
