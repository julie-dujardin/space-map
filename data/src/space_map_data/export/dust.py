"""Export the dust nest to `v1/dust/`, beside the star tree.

The star tree's export replaces `v1/x/` whole, so the nest has a directory of its
own. Each level and tier is one volume file in the extrasolar container, and
`metadata.json` holds the rest. Levels, extents and sizes come from the build's
`encoding.json`, so the metadata describes the codes as they were encoded. A
variant whose tier is `undecided` may not reach the served root.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.dust.maps import PLANCK_ACKNOWLEDGEMENT
from space_map_data.dust import VARIANTS
from space_map_data.dust.encode import (
    TIERS,
    Recorded,
    codes_name,
    encoded_dir,
    read_recorded,
)
from space_map_data.dust.nest import (
    CUBE_25_FADE,
    CUBE_50_FADE,
    CUBE_Z_FADE,
    LOCAL_FADE,
    REGIONAL_FADE,
    galactic_to_icrs,
)
from space_map_data.dust.rest import (
    FLARE,
    FLARE_RADIUS,
    MAX_OVER_PLANCK_SCALE,
    R_SUN,
    SCALE_HEIGHT,
    SCALE_LENGTH,
    Z_SUN,
)
from space_map_data.dust.sources import source_terms
from space_map_data.export import swap
from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.skycultures import UNDECIDED, combined
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# Each source names the download directory that records its terms.
SOURCES = {
    "edenhofer-2024": {
        "name": "Edenhofer et al. 2024 3D dust map",
        "citation": "Edenhofer et al. 2024, arXiv:2308.01295",
        "source": "https://zenodo.org/records/10658339",
        "directory": "edenhofer-2024",
    },
    "zgr23": {
        "name": "Extinction curve of Zhang, Green & Rix 2023",
        "citation": "Zhang, Green & Rix 2023, MNRAS 524, 1855",
        "source": "https://doi.org/10.5281/zenodo.7811871",
        "directory": "edenhofer-2024",
    },
    "bayestar19": {
        "name": "Bayestar19",
        "citation": "Green et al. 2019, arXiv:1905.02734",
        "source": "https://doi.org/10.7910/DVN/2EJ9TX",
        "directory": "bayestar19",
    },
    "decaps-2025": {
        "name": "DECaPS 3D dust map",
        "citation": "Zucker et al. 2025, doi:10.3847/1538-4357/adfbe6",
        "source": "https://doi.org/10.7910/DVN/J9JCKO",
        "directory": "decaps-2025",
    },
    "planck-2013": {
        "name": "Planck 2013 thermal dust model",
        "citation": "Planck Collaboration XI 2014, doi:10.1051/0004-6361/201323195",
        "source": "https://irsa.ipac.caltech.edu/data/Planck/release_1/all-sky-maps/",
        "attribution": PLANCK_ACKNOWLEDGEMENT,
        "directory": "planck-2013",
    },
    "vergely-2022": {
        "name": "Vergely et al. 2022 v2 cubes",
        "citation": "Vergely et al. 2022, arXiv:2205.09087",
        "source": "https://zenodo.org/records/10405177",
        "directory": "explore-lallement-vergely",
    },
}
# The layers of each variant, with the sources whose values each one holds.
LAYERS = {
    "open": (
        ("local", "Edenhofer 2024", ("edenhofer-2024", "zgr23")),
        ("regional", "Edenhofer 2 kpc map", ("edenhofer-2024", "zgr23")),
        ("disc", "Bayestar19, DECaPS", ("bayestar19", "decaps-2025")),
        ("rest", "Planck total on an exponential disc", ("planck-2013",)),
    ),
    "vergely": (
        ("local", "Edenhofer 2024", ("edenhofer-2024", "zgr23")),
        (
            "regional",
            "Vergely 2022 over the Edenhofer 2 kpc map",
            ("vergely-2022", "edenhofer-2024", "zgr23"),
        ),
        ("disc", "Bayestar19, DECaPS", ("bayestar19", "decaps-2025")),
        ("rest", "Planck total on an exponential disc", ("planck-2013",)),
    ),
}


def volume_payload(codes: np.ndarray, level: int, tier: str) -> bytes:
    """One texture in the order of `texImage3D`: x runs fastest, then y, then z."""
    in_order = np.ascontiguousarray(codes.transpose(2, 1, 0)).reshape(-1)
    column = container.Column("codes", "uint8", pa.array(in_order))
    return container.volume_payload(column, codes.shape, level, tier)


def _sources(variant: str) -> tuple[list[dict], dict[str, dict]]:
    keys = sorted({key for _, _, used in LAYERS[variant] for key in used})
    terms = {key: source_terms(SOURCES[key]["directory"]) for key in keys}
    listed = [
        {
            "key": key,
            **{k: v for k, v in SOURCES[key].items() if k != "directory"},
            "license": terms[key]["license"],
            "distribution": terms[key]["distribution"],
        }
        for key in keys
    ]
    return listed, terms


def _distribution(variant: str) -> str:
    """The strictest tier among the sources whose values the variant holds."""
    _, terms = _sources(variant)
    return combined(*(entry["distribution"] for entry in terms.values()))


def _metadata(
    variant: str,
    files: Mapping[tuple[int, str], container.Written],
    token: str,
    recorded: Recorded,
    distribution: str,
) -> dict:
    sources, terms = _sources(variant)
    levels = []
    for index in sorted(recorded.levels):
        encoding = recorded.levels[index]
        entry = {
            "level": index,
            "half_extent_pc": list(recorded.half_extents[index]),
            "floor": encoding.floor,
            "top": encoding.top,
        }
        for tier in TIERS:
            written = files[(index, tier)]
            entry[tier] = {
                "path": written.path,
                "size": list(recorded.shapes[codes_name(index, tier)]),
                "bytes": written.size,
            }
        levels.append(entry)
    layers: list[dict] = []
    for key, name, used in LAYERS[variant]:
        layer = {
            "key": key,
            "name": name,
            "sources": list(used),
            "model": key == "rest",
            "distribution": combined(*(terms[item]["distribution"] for item in used)),
        }
        layers.append(layer)
    layers[-1]["unplaced_share_of_remainder"] = round(recorded.unplaced_share, 4)
    layers[-1]["share_of_sun_column_by_level"] = recorded.rest_share
    layers[-1]["shape"] = {
        "reference": "Drimmel & Spergel 2001, Table 1",
        "scale_length_pc": SCALE_LENGTH,
        "scale_height_pc": SCALE_HEIGHT,
        "flare_per_pc": FLARE,
        "flare_radius_pc": FLARE_RADIUS,
        "sun_radius_pc": R_SUN,
        "sun_height_pc": Z_SUN,
        "max_over_planck_scale": MAX_OVER_PLANCK_SCALE,
    }
    handovers = {"local_pc": LOCAL_FADE, "regional_pc": REGIONAL_FADE}
    if variant == "vergely":
        handovers |= {
            "cube_height_pc": CUBE_Z_FADE,
            "cube_25_pc": CUBE_25_FADE,
            "cube_50_pc": CUBE_50_FADE,
        }
    return {
        "format": container.VERSION,
        "exported": datetime.now(UTC).isoformat(timespec="seconds"),
        "token": token,
        "variant": variant,
        "distribution": distribution,
        "quantity": "A0 at 550 nm in mag/pc, mean over the voxel",
        "frame": {
            "origin": "the Sun",
            "unit": "pc",
            "axes": "x to the Galactic centre, y to l = 90 deg, z to the north Galactic pole",
            "rotation_to_icrs": galactic_to_icrs().round(10).tolist(),
        },
        "encoding": "floor * expm1(code / 255 * log1p(top / floor))",
        "calibration": recorded.gains,
        "handovers": handovers,
        "levels": levels,
        "layers": layers,
        "credits": sources,
    }


def export_dust(variant: str, root: Path) -> dict:
    """Write one variant to `root/v1/dust/` and return its metadata.

    The extrasolar export holds the same lock, so the two never run together.
    """
    if variant not in VARIANTS:
        raise swap.ExportRefused(f"no variant {variant}")
    distribution = _distribution(variant)
    if distribution == UNDECIDED and root.resolve() == EXTRASOLAR_DIR.resolve():
        raise swap.ExportRefused(
            f"variant {variant} is {UNDECIDED}: name a root other than {EXTRASOLAR_DIR}"
        )
    with swap.locked(root):
        return _write(variant, root, distribution)


def _write(variant: str, root: Path, distribution: str) -> dict:
    def write_files(
        staging: Path, recorded: Recorded
    ) -> dict[tuple[int, str], container.Written]:
        files = {}
        for index in sorted(recorded.levels):
            for tier in TIERS:
                codes = np.load(encoded_dir(variant) / codes_name(index, tier))
                payload = volume_payload(codes, index, tier)
                path = f"{tier}/l{index}.bin.gz"
                files[(index, tier)] = container.write(staging, path, payload)
        return files

    def metadata_of(
        files: Mapping[tuple[int, str], container.Written],
        token: str,
        recorded: Recorded,
    ) -> dict:
        return _metadata(variant, files, token, recorded, distribution)

    return swap.publish(
        root, "dust", lambda: read_recorded(variant), write_files, metadata_of
    )


def export_dust_only(variant: str, root: Path = EXTRASOLAR_DIR) -> None:
    metadata = export_dust(variant, root)
    sizes = {
        tier: sum(entry[tier]["bytes"] for entry in metadata["levels"])
        for tier in TIERS
    }
    logger.info(
        "dust %s: %s, %s bytes by tier, token %s",
        variant,
        metadata["distribution"],
        sizes,
        metadata["token"],
    )
