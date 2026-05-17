"""Run just the probe-export stage from current DB + on-disk kernels.

Bypasses the full `space-map-export` pipeline so we can verify the synth
SPKs flow through to gzipped per-zone/per-chunk binaries without depending
on the rest of the export running cleanly.

Outputs land under `space-map-export/position/probes/`.
"""

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
    out_dir = EXPORT_DIR
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


if __name__ == "__main__":
    main()
