"""Download manifests — where every manually-staged asset came from.

The bytes these describe (textures, DEMs, meshes) are re-downloadable and stay
in the download dir. The manifests are not: they carry hand-curated source
URLs, licences, attribution and per-file loader overrides (nodata sentinels,
longitude conventions, unit scales) that were reverse-engineered once and would
be unrecoverable if the download dir were lost. Losing a manifest loses the
link, which is what makes the payload re-downloadable in the first place.
"""
