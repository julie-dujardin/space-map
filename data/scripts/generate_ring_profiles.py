"""Synthesise ring radial-profile bundles for the tenuous ring systems.

Saturn's *main* rings are measured Cassini data (bjj_rings downloader); no
published equivalent exists for the tenuous systems, so this generates the
same five-channel 1×N bundle from the ring catalogue
(``constants/rings/catalog.py``): tabulated feature boundaries + normal
optical depths → supersampled τ(r) → channels.
That covers Jupiter, Uranus and Neptune whole, plus the Saturn bundles that
fall outside the measured strip (its D ring and its outer tenuous rings).

Opacity stays physical. 8-bit strips cannot hold τ ~1e-6 directly, so every
channel is stored normalised to the bundle's ``intensity_scale`` (recorded in
ring-metadata.yaml); stored × scale = physical value, making ring systems
directly comparable to each other and to Saturn's measured data (implicit
scale 1). Consequence: these systems render as faint as they really are.

Writes ``sources/textures/rings/<slug>/{channel}.txt`` + ``ring-metadata.yaml``
in the exact layout the bjj_rings downloader uses, so ingest's RingProcessor
picks the bundles up unchanged. ``--preview-dir`` additionally renders
quick-look PNGs (top-down annulus + per-channel strips) without touching the
DB or export dir.

    uv run python scripts/generate_ring_profiles.py [--preview-dir DIR] [--only SLUG]
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml

from space_map_data.constants.rings.catalog import (
    RING_CATALOGS,
    RenderedFeature,
    RingBundle,
    bundle_features,
)
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

# Sub-samples per output pixel: rings narrower than a pixel (Uranus' 1.5 km
# "Six" at ~5 km/px) keep their equivalent depth as fractional coverage.
SUPERSAMPLE = 16

# Artistic per-kind photometry: macroscopic "dense" rings are backscatter-
# bright; µm "dusty" rings light up in forward scatter and transmit to the
# unlit side. Applied as weights on τ before the shared normalisation.
KIND_WEIGHTS = {
    "dense": {"backscattered": 1.0, "forwardscattered": 0.35, "unlitside": 0.35},
    "dusty": {"backscattered": 0.30, "forwardscattered": 2.0, "unlitside": 1.2},
}

# NSSDCA equatorial radii, preview planet disc only. Keyed by planet name
# since several bundles can share one host.
PREVIEW_EQ_RADIUS_KM = {
    "Jupiter": 71_492.0,
    "Saturn": 60_268.0,
    "Uranus": 25_559.0,
    "Neptune": 24_766.0,
}

# Planet display names for generated text and previews; the catalogue and
# downloaded bundle yamls name only the NAIF body.
PLANET_BY_BODY = {
    "naif-599": "Jupiter",
    "naif-699": "Saturn",
    "naif-799": "Uranus",
    "naif-899": "Neptune",
}


def synthesise(
    bundle: RingBundle, features: tuple[RenderedFeature, ...]
) -> tuple[float, float, float, float, dict[str, np.ndarray]]:
    """Rasterise the feature table into the channel arrays.

    Returns (inner_km, outer_km, intensity_scale, thickness_scale_km,
    channels) where scalar channels are (N,) and color is (N, 3), all in
    [0, 1]; multiplying a stored value by its scale recovers the physical
    one. A ``thickness`` channel is present only when a feature has a
    tabulated vertical extent (thickness_scale_km > 0): the τ-weighted mean
    over the features covering each radius. The renderer spreads all material
    at a radius over one thickness, so weighting by opacity keeps the bright
    thin main ring thin where the faint 8,800 km Thebe ring overlaps it,
    while pure-gossamer radii keep their full extent.
    """
    inner = min(f.inner_km for f in features)
    outer = max(f.outer_km for f in features)
    n = bundle.sample_count
    edges = np.linspace(inner, outer, n * SUPERSAMPLE + 1)
    r = ((edges[:-1] + edges[1:]) / 2.0).reshape(n, SUPERSAMPLE)

    tau = np.zeros_like(r)
    tau_ch = {c: np.zeros_like(r) for c in KIND_WEIGHTS["dense"]}
    rgb_num = np.zeros((n, SUPERSAMPLE, 3))
    thickness_num = np.zeros_like(r)

    for f in features:
        x = (r - f.inner_km) / (f.outer_km - f.inner_km)
        inside = (x >= 0.0) & (x <= 1.0)
        if f.profile == "flat":
            shape = np.ones_like(r)
        elif f.profile == "fade_inner":
            shape = x
        elif f.profile == "fade_outer":
            shape = 1.0 - x
        else:  # peak
            shape = 1.0 - np.abs(2.0 * x - 1.0)
        contrib = np.where(inside, f.optical_depth * shape, 0.0)
        tau += contrib
        for c, w in KIND_WEIGHTS[f.kind].items():
            tau_ch[c] += w * contrib
        rgb_num += contrib[..., None] * np.asarray(f.tint or bundle.tint)
        if f.thickness_outer_km is None:
            thickness = f.thickness_km
        else:
            # Flaring ring (Saturn's outer E ring): interpolate the extent
            # across the feature instead of stepping between sub-features.
            span = f.thickness_outer_km - f.thickness_km
            thickness = f.thickness_km + span * np.clip(x, 0.0, 1.0)
        thickness_num += contrib * thickness

    tau_px = tau.mean(axis=1)
    alpha = 1.0 - np.exp(-tau_px)
    physical = {c: 1.0 - np.exp(-t.mean(axis=1)) for c, t in tau_ch.items()}

    # One shared scale across all channels keeps their relative levels intact.
    scale = max(float(alpha.max()), *(float(a.max()) for a in physical.values()))
    channels: dict[str, np.ndarray] = {"transparency": 1.0 - alpha / scale}
    for c, a in physical.items():
        channels[c] = a / scale
    # Opacity-weighted mean of the feature tints; gaps fall back to the system
    # tint (fully transparent there anyway).
    rgb = rgb_num.mean(axis=1) / np.maximum(tau_px, 1e-12)[:, None]
    rgb[tau_px <= 0.0] = bundle.tint
    channels["color"] = np.clip(rgb, 0.0, 1.0)

    thickness_scale_km = float(
        max(max(f.thickness_km, f.thickness_outer_km or 0.0) for f in features)
    )
    if thickness_scale_km > 0.0:
        thickness_px = thickness_num.mean(axis=1) / np.maximum(tau_px, 1e-12)
        thickness_px[tau_px <= 0.0] = 0.0
        channels["thickness"] = np.clip(thickness_px / thickness_scale_km, 0.0, 1.0)
    return inner, outer, scale, thickness_scale_km, channels


def write_bundle(
    body: str,
    bundle: RingBundle,
    features: tuple[RenderedFeature, ...],
    out_root: Path,
) -> tuple[float, float, float, dict[str, np.ndarray]]:
    inner, outer, scale, thickness_scale_km, channels = synthesise(bundle, features)
    out_dir = out_root / bundle.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    for name, arr in channels.items():
        filename = f"{name}.txt"
        np.savetxt(out_dir / filename, arr, fmt="%.6f")
        files[name] = filename

    planet = PLANET_BY_BODY[body]
    payload = {
        "body": body,
        "bundle": bundle.name,
        # One entry per work, each stating its own contribution — a bundle
        # mixes boundaries from one table with vertical extents from another.
        "sources": [
            {
                "source": s.url,
                "organisation": s.organisation,
                "license": s.license,
                "work": s.work,
                "contribution": s.contribution,
                # Credits appends a caveat: these profiles are reconstructions
                # from the tabulated numbers, not the source's own photometry.
                "synthesised": True,
            }
            for s in bundle.sources
        ],
        "description": (
            f"Synthetic 1-D radial profiles of {planet}'s {bundle.covers}: "
            "the same five-channel bundle as the measured Saturn strips, "
            "generated from tabulated feature boundaries and normal optical "
            "depths."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "inner_radius_km": float(inner),
        "outer_radius_km": float(outer),
        "sample_count": bundle.sample_count,
        # Stored channel value × intensity_scale = physical value; the strips
        # only use the 8-bit range fully, they do not brighten anything.
        "intensity_scale": scale,
        "channels": files,
    }
    if thickness_scale_km > 0.0:
        # Physical km for a thickness-channel value of 1.0.
        payload["thickness_scale_km"] = thickness_scale_km
    (out_dir / "ring-metadata.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    )
    logger.info(
        "wrote %s: %d samples over %.0f-%.0f km (%d features, scale %.3g)",
        out_dir,
        bundle.sample_count,
        inner,
        outer,
        len(features),
        scale,
    )
    return inner, outer, scale, channels


# Preview-only exposure boost so faint (correctly faint) bands stay legible.
PREVIEW_GAIN = 2.5


def _lit_premultiplied(channels: dict[str, np.ndarray], scale: float) -> np.ndarray:
    """Approximate the shader's lit-side composite over black, per strip px,
    at physical brightness (so systems compare truthfully)."""
    alpha = np.clip((1.0 - channels["transparency"]) * scale, 0.0, 1.0)
    back = np.clip(channels["backscattered"] * scale, 0.0, 1.0)
    return channels["color"] * (back * alpha)[:, None]


def render_previews(
    slug: str,
    planet: str,
    sample_count: int,
    inner: float,
    outer: float,
    channels: dict[str, np.ndarray],
    preview_dir: Path,
    scale: float = 1.0,
) -> None:
    from PIL import Image

    n = sample_count
    preview_dir.mkdir(parents=True, exist_ok=True)
    lit = _lit_premultiplied(channels, scale)

    # Top-down annulus, planet disc in dim grey. Each preview pixel
    # box-averages the strip over its radial footprint — nearest sampling
    # would reduce sub-pixel rings (Uranus classics) to speckle.
    size = 1000
    c = (size - 1) / 2.0
    km_per_px = outer * 1.02 / c
    cum = np.concatenate([np.zeros((1, 3)), np.cumsum(lit, axis=0)])
    yy, xx = np.mgrid[0:size, 0:size]
    r_km = np.hypot(xx - c, yy - c) * km_per_px
    px_km = (outer - inner) / n
    i0 = np.clip(((r_km - km_per_px / 2 - inner) / px_km).astype(int), 0, n)
    i1 = np.clip(((r_km + km_per_px / 2 - inner) / px_km).astype(int) + 1, 0, n)
    out = (cum[i1] - cum[i0]) / np.maximum(i1 - i0, 1)[..., None]
    out[i1 <= i0] = 0.0
    out = np.clip(out * PREVIEW_GAIN, 0.0, 1.0) ** (1.0 / 2.2)
    out[r_km <= PREVIEW_EQ_RADIUS_KM[planet]] = 0.18
    Image.fromarray((out * 255.0 + 0.5).clip(0, 255).astype(np.uint8)).save(
        preview_dir / f"{slug}_annulus.png"
    )

    # Per-channel strip panel at full sample resolution.
    band = 48
    rows = []
    for name in ("backscattered", "forwardscattered", "unlitside", "transparency"):
        rows.append(np.repeat(channels[name][None, :, None], band, axis=0) * [1, 1, 1])
    rows.append(np.repeat(channels["color"][None, :, :], band, axis=0))
    rows.append(
        np.repeat(
            (np.clip(lit * PREVIEW_GAIN, 0, 1) ** (1.0 / 2.2))[None, :, :],
            band,
            axis=0,
        )
    )
    panel = np.concatenate(rows, axis=0)
    Image.fromarray((panel * 255.0 + 0.5).clip(0, 255).astype(np.uint8)).save(
        preview_dir / f"{slug}_strips.png"
    )


def preview_bundle(bundle_dir: Path, preview_dir: Path) -> None:
    """Render the same previews from an already-downloaded (measured) bundle,
    so synthetic and measured systems compare like for like."""
    meta = yaml.safe_load((bundle_dir / "ring-metadata.yaml").read_text())
    channels = {
        name: np.loadtxt(bundle_dir / fn) for name, fn in meta["channels"].items()
    }
    render_previews(
        bundle_dir.name,
        PLANET_BY_BODY[meta["body"]],
        int(meta["sample_count"]),
        float(meta["inner_radius_km"]),
        float(meta["outer_radius_km"]),
        channels,
        preview_dir,
        scale=float(meta.get("intensity_scale", 1.0)),
    )


def main() -> None:
    bundles = [
        (catalog.body, bundle, bundle_features(catalog, bundle.name))
        for catalog in RING_CATALOGS.values()
        for bundle in catalog.bundles
    ]

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", type=Path, default=SOURCES_TEXTURES_DIR / "rings")
    ap.add_argument("--preview-dir", type=Path, default=None)
    ap.add_argument("--only", choices=[b.slug for _, b, _ in bundles])
    ap.add_argument(
        "--preview-bundle",
        type=Path,
        help="preview an existing bundle dir instead of generating (needs --preview-dir)",
    )
    args = ap.parse_args()

    if args.preview_bundle:
        if not args.preview_dir:
            ap.error("--preview-bundle requires --preview-dir")
        preview_bundle(args.preview_bundle, args.preview_dir)
        return

    for body, bundle, features in bundles:
        if args.only and bundle.slug != args.only:
            continue
        inner, outer, scale, channels = write_bundle(
            body, bundle, features, args.out_root
        )
        if args.preview_dir:
            render_previews(
                bundle.slug,
                PLANET_BY_BODY[body],
                bundle.sample_count,
                inner,
                outer,
                channels,
                args.preview_dir,
                scale=scale,
            )


if __name__ == "__main__":
    main()
