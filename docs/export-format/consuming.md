# Consuming the data

1. Fetch `metadata.json` to discover available zones and shapes.
2. Fetch `labels/{lang}.gz` once on app start (and on locale change) to get
   the pre-interaction label set: split by newline, parse `{id}\x1f{name}`
   per line, build a `Map<id, name>`. The keys *are* the promoted set —
   there's no separate frontend list.
3. For each (zone, zoom), dispatch on `shape`:
   - `parted` → fetch `position/{zone}/{zoom}/{part}.bin.gz`
   - `chunked-parted` → pick a label (date for `earth`, chunk index for
     `moons`) then fetch `position/{zone}/{zoom}/{label}/{part}.bin.gz`
   - `chunked` (chebyshev) → compute the chunk index from JD and fetch
     `position/{zone}/{zoom}/{chunk}.bin.gz`
4. Parse the file: read the common header, dispatch on the format byte at
   offset 6 to either the elements columnar reader or the chebyshev per-body
   reader. Rebuild full IDs from the id-type byte (elements) or the per-body
   `id_type` (chebyshev).
5. For elements rows, propagate at the target date with Kepler's equation
   (or Barker's for parabolic, or `json2satrec` + SGP4 for SGP4). For
   chebyshev bodies, evaluate the segment covering the target JD via
   Clenshaw's recursion to get a parent-relative position in km, then walk
   up the parent chain to your reference frame.
6. Read `has_localized` (last column on elements, byte 19 of the chebyshev
   per-body header) to gate localized object-detail fetches. Always fetch
   `objects/__global__/{bucket}.json.gz` where
   `bucket = sha256(id)[:4] % N_global`; only fetch
   `objects/{lang}/{bucket}.json.gz` when `has_localized` is `1`. On a 404,
   give up — there's no English fallback tier.
