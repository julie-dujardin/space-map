"""Per-body ring feature tables + render tuning for the tenuous ring systems.

Boundaries and normal optical depths come from the PDS Ring-Moon Systems Node
"vital statistics" tables, cross-checked against the NSSDCA ring fact sheets
(read from Internet Archive snapshots — nssdc.gsfc.nasa.gov has been offline
since early 2025); disagreements are noted per feature. Opacity is kept
physical: strips store values normalised to the recorded ``intensity_scale``
so 8-bit survives τ ~1e-6, and stored × scale reproduces the cited optical
depths exactly. Only the tints and the dense/dusty channel weights are
artistic.

Saturn is absent by design — its rings ship as measured radial profiles with
their own geometry constants (download/providers/bjj_rings.py).
"""

from typing import Literal, NamedTuple


class RingFeature(NamedTuple):
    name: str
    inner_km: float
    outer_km: float
    # Normal optical depth. Features may overlap radially (Jupiter's gossamer
    # rings nest inside the main ring span); the generator sums overlaps.
    optical_depth: float
    # "dense" = macroscopic particles (backscatter-bright); "dusty" = µm dust
    # (forward-scatter-bright). Drives per-channel weights only.
    kind: Literal["dense", "dusty"]
    # Radial shape: flat | fade_inner (ramps up toward the outer edge) |
    # fade_outer (decays toward the outer edge) | peak (triangular, mid-ring).
    profile: Literal["flat", "fade_inner", "fade_outer", "peak"] = "flat"
    # sRGB tint override for the color channel; None = system tint.
    tint: tuple[float, float, float] | None = None
    # Full vertical extent. 0 = not tabulated / negligible — rendered flat.
    thickness_km: float = 0.0


class RingSystem(NamedTuple):
    # Directory name under sources/textures/rings/, mirroring "saturn".
    slug: str
    # Canonical source page, carried into ring-metadata.yaml → credits.
    source: str
    features: tuple[RingFeature, ...]
    # Strip resolution. WebP caps dimensions at 16383 px; sub-pixel features
    # keep their equivalent depth via fractional coverage in the generator.
    sample_count: int
    # Default sRGB tint for features without their own.
    tint: tuple[float, float, float]


def _span(mid_km: float, width_km: float) -> tuple[float, float]:
    """The PDS Uranus/Neptune tables give mid radius + width; keep those
    source numbers verbatim and derive strip boundaries here."""
    return mid_km - width_km / 2.0, mid_km + width_km / 2.0


RING_SYSTEMS: dict[str, RingSystem] = {
    # PDS Jupiter table (De Pater et al. 2018 values); NSSDCA 2015 sheet noted
    # where it disagrees. All τ ≤ 8e-6 — visibility is entirely tuning.
    "naif-599": RingSystem(
        slug="jupiter",
        source="https://pds-rings.seti.org/jupiter/jupiter_rings_table.html",
        features=(
            # Halo: 100,000-122,400 km, τ ~1e-6 (PDS; NSSDCA: 89,400-123,000,
            # τ 3e-6). A vertically thick torus (~10,000 km, PDS/NSSDCA) that
            # brightens toward the main ring. Sub-µm grains → bluish tint.
            RingFeature(
                "Halo",
                100_000,
                122_400,
                1e-6,
                "dusty",
                "fade_inner",
                tint=(0.72, 0.80, 1.00),
                thickness_km=10_000,
            ),
            # Main ring: 122,400-129,100 km (PDS; NSSDCA 123,000-128,940).
            # τ 5e-6 (NSSDCA; PDS "<8e-6"); particle albedo ~0.015 (NSSDCA)
            # → dark red-brown. Thickness 100 km (PDS; NSSDCA "<~100").
            RingFeature(
                "Main Ring",
                122_400,
                129_100,
                5e-6,
                "dense",
                tint=(1.00, 0.83, 0.68),
                thickness_km=100,
            ),
            # The gossamer rings overlap: each spans from the ill-defined
            # inner boundary (PDS lists 122,400 for both) out to its source
            # moon's orbit; summing overlaps reproduces the observed
            # staircase profile. τ per PDS (NSSDCA: 1e-7 for both).
            # Thickness per PDS/NSSDCA: set by each moon's orbital inclination.
            RingFeature(
                "Amalthea Gossamer Ring",
                122_400,
                181_350,
                5e-7,
                "dusty",
                thickness_km=2_600,
            ),
            RingFeature(
                "Thebe Gossamer Ring",
                122_400,
                221_900,
                1e-7,
                "dusty",
                thickness_km=8_800,
            ),
            # Faint decay past Thebe's orbit, τ ~1e-9 (PDS, out to 270,000 km;
            # NSSDCA 280,000). Same vertical extent as the Thebe ring (PDS).
            RingFeature(
                "Thebe Extension",
                221_900,
                270_000,
                1e-9,
                "dusty",
                "fade_outer",
                thickness_km=8_800,
            ),
        ),
        # ~21 km/px; nothing narrower than the 6,700 km main ring.
        sample_count=8_192,
        tint=(1.00, 0.88, 0.78),
    ),
    # PDS Uranus table (Nicholson et al. 2018 values), mid radius ± width/2.
    # Narrow-ring widths are the PDS single figure; the eccentric rings vary
    # (NSSDCA: Alpha 4-10 km, Epsilon 20-96 km). Particles are charcoal-dark
    # (geometric albedo ~0.015-0.018, NSSDCA) → near-neutral tint.
    "naif-799": RingSystem(
        slug="uranus",
        source="https://pds-rings.seti.org/uranus/uranus_rings_table.html",
        features=(
            # Inner dust: zeta (1986U2R) + its inward extensions, and the
            # broad sheet permeating the classical system (τ 0.005, PDS).
            RingFeature("Zeta CC", *_span(30_863, 8_050), 1e-4, "dusty"),
            RingFeature("Zeta C", *_span(36_639, 2_960), 5e-4, "dusty"),
            RingFeature("Dust sheet", *_span(38_440, 23_200), 0.005, "dusty"),
            RingFeature("Zeta", *_span(39_600, 3_500), 0.0045, "dusty"),
            RingFeature("Six", *_span(41_838, 1.53), 0.3, "dense"),
            RingFeature("Five", *_span(42_234, 2.28), 0.5, "dense"),
            RingFeature("Four", *_span(42_571, 2.33), 0.3, "dense"),
            RingFeature("Alpha-4", *_span(43_027, 3_353), 0.002, "dusty"),
            RingFeature("Alpha", *_span(44_718, 8.46), 0.4, "dense"),
            RingFeature("Beta-Alpha", *_span(44_879, 312), 0.002, "dusty"),
            RingFeature("Beta", *_span(45_661, 9.49), 0.3, "dense"),
            RingFeature("Eta", *_span(47_176, 1.6), 0.4, "dense"),
            RingFeature("Eta C", *_span(47_201, 40), 0.02, "dusty"),
            RingFeature("Gamma", *_span(47_627, 2.15), 0.3, "dense"),
            RingFeature("Delta C", *_span(48_289, 15), 0.03, "dusty"),
            RingFeature("Delta", *_span(48_300, 4.6), 0.5, "dense"),
            RingFeature("Lambda C", *_span(49_936, 3.1), 0.15, "dusty"),
            RingFeature("Lambda", *_span(50_024, 2.3), 0.1, "dusty"),
            # τ 0.5-2.3 across its eccentric orbit (PDS); geometric mean ≈1.1.
            RingFeature("Epsilon", *_span(51_149, 58.1), 1.1, "dense"),
            # Outer dust pair, both peaked (µ at Mab's orbit). Colors from
            # de Pater et al. 2006: ν red, µ blue.
            RingFeature(
                "Nu",
                *_span(67_300, 3_800),
                5.6e-6,
                "dusty",
                "peak",
                tint=(1.00, 0.80, 0.70),
            ),
            RingFeature(
                "Mu",
                *_span(97_700, 17_000),
                8.5e-6,
                "dusty",
                "peak",
                tint=(0.65, 0.78, 1.00),
            ),
        ),
        # ~5 km/px: the classical narrow rings land on ~1 px each.
        sample_count=16_000,
        tint=(0.88, 0.89, 0.92),
    ),
    # PDS Neptune table, mid radius ± width/2. The system is dust-dominated
    # → slightly reddish tint.
    "naif-899": RingSystem(
        slug="neptune",
        source="https://pds-rings.seti.org/neptune/neptune_rings_table.html",
        features=(
            RingFeature("Galle", *_span(42_000, 2_000), 1e-4, "dusty"),
            # Width "<100" (PDS/NSSDCA) — 100 used. τ 0.003 (PDS; NSSDCA ~0.01).
            RingFeature("Le Verrier", *_span(53_200, 100), 0.003, "dense"),
            RingFeature("Lassell", *_span(55_200, 4_000), 1e-4, "dusty"),
            # "Brightness enhancement at Lassell's outer edge" (PDS): no width
            # or τ tabulated anywhere — nominal 100 km / τ 1e-4 stand-ins.
            RingFeature("Arago", *_span(57_200, 100), 1e-4, "dusty"),
            # Dust co-orbital with Galatea (PDS "Unnamed"): no width or τ
            # tabulated — nominal 50 km / τ 1e-4 stand-ins.
            RingFeature("Galatea co-orbital dust", *_span(61_953, 50), 1e-4, "dusty"),
            # Continuous ring τ 0.003 (PDS; NSSDCA 0.01-0.1 incl. arcs). The
            # five arcs (τ ~0.1, ~15 km) are azimuthal structure a radial
            # strip cannot carry.
            RingFeature("Adams", *_span(62_933, 15), 0.003, "dense"),
        ),
        # ~2.7 km/px; Adams (15 km) spans ~6 px.
        sample_count=8_192,
        tint=(1.00, 0.92, 0.86),
    ),
}
