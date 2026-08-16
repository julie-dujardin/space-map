"""Download manifests — where every manually-staged asset came from.

The bytes (textures, DEMs, meshes) are re-downloadable and stay in the
download dir. The manifests are not: hand-curated source URLs, licences,
attribution and per-file loader overrides (nodata sentinels, longitude
conventions, unit scales) reverse-engineered once, unrecoverable if the
download dir were lost.
"""
