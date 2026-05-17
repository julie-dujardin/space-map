"""Run just the probe-export stage from current DB + on-disk kernels.

Bypasses the full `space-map-export` pipeline so we can verify the synth
SPKs flow through to gzipped per-zone/per-chunk binaries without depending
on the rest of the export running cleanly.

Writes chunks to `space-map-export/v1/position/probes/{zone}/{chunk}.bin.gz`
matching the full-pipeline layout, and emits a minimal
`space-map-export/v1/metadata.json` carrying just the `position.zones`
section so the probe-diagnostic scripts (probe_benchmark, probe_chunks,
probe_gaps) can read the manifest.
"""

import json
import logging
import logging.config
import tomllib

from space_map_data.export.position.probes import write_probes
from space_map_data.utils.db import engine_scope, session_scope
from space_map_data.utils.paths import DATA_DIR, DOWNLOAD_DIR, EXPORT_DIR


def main() -> None:
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    log = logging.getLogger("horizons_synth_probe_export")
    # Match the full-pipeline layout so probe_benchmark / probe_chunks /
    # probe_gaps find the chunks and manifest where they expect.
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    with engine_scope():
        with session_scope() as session:
            # `has_localized` is the cross-Wikidata map of which probe rows
            # have IAU-named landing sites; we don't need it here, empty dict
            # means every probe is treated as un-localized (trajectory only).
            zones = write_probes(session, DOWNLOAD_DIR, out_dir, has_localized={})
            log.info(
                "Probe export complete: %d zones produced (%s)",
                len(zones),
                sorted(zones.keys()),
            )

    # Minimal manifest so probe-diagnostic scripts can find the zones.
    # `space-map-export` writes a much richer metadata.json but those extras
    # aren't needed for the probe scripts; we merge into an existing manifest
    # if one is already present so we don't clobber prior exports.
    manifest_path = out_dir / "metadata.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            manifest = {}
    manifest.setdefault("position", {}).setdefault("zones", {}).update(zones)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    log.info("Wrote manifest %s with %d zones", manifest_path, len(zones))


if __name__ == "__main__":
    main()
