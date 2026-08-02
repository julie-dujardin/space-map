"""Per-body ring feature tables + render tuning for the synthetic ring bundles.

Boundaries and normal optical depths come from the PDS Ring-Moon Systems Node
"vital statistics" tables, cross-checked against the NSSDCA ring fact sheets
(read from Internet Archive snapshots — nssdc.gsfc.nasa.gov has been offline
since early 2025); disagreements are noted per feature. Opacity is kept
physical: strips store values normalised to the recorded ``intensity_scale``
so 8-bit survives τ ~1e-6, and stored × scale reproduces the cited optical
depths exactly. Only the tints and the dense/dusty channel weights are
artistic.

A body may have several bundles: Saturn's main rings ship as measured Cassini
profiles (download/providers/bjj_rings.py), so its entries here cover only
what that measurement misses — the D ring inside it and the tenuous rings
outside it. Bundles never overlap radially; each carries its own sample
density and intensity/thickness scales, which is what lets one export hold
both a τ~5 B ring and a τ~5e-6 E ring.
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
    # Vertical extent at the outer edge for rings that flare (Saturn's E ring);
    # None = constant thickness_km across the feature.
    thickness_outer_km: float | None = None


class RingSource(NamedTuple):
    """One work a bundle draws on. A bundle usually mixes several — boundaries
    from one table, vertical extents from another — so each states what it
    contributed rather than the bundle claiming a single origin.

    Several bundles of one body routinely cite the same work for different
    things; the credits export merges those into a single row, which is why
    ``contribution`` is a bare noun phrase and the work is named separately.
    """

    url: str
    # Kept short so the same body reads as one name across the credit UI:
    # "NASA", not "NASA PDS Ring-Moon Systems Node / NSSDCA".
    organisation: str
    license: str
    # Title of the work itself, e.g. "NSSDCA Saturnian Rings Fact Sheet".
    work: str
    # Lowercase noun phrase: what this work gave *this* bundle.
    contribution: str


NASA = "NASA"
# Matches the plain wording every other bundle uses; the organisation column
# already carries the "who".
NASA_LICENSE = "Public domain"


class RingSystem(NamedTuple):
    # Directory name under sources/textures/rings/.
    slug: str
    # NAIF id of the host body; several bundles may share one.
    body: str
    # Bundle name within the body, also its export sub-directory. Ordered
    # inner → outer by convention: "inner", "primary", "outer".
    bundle: str
    # Host planet name, for generated attribution/description text.
    planet: str
    # Noun phrase naming what this bundle covers, for the same generated text.
    covers: str
    # Works behind this bundle, carried into ring-metadata.yaml → credits.
    sources: tuple[RingSource, ...]
    features: tuple[RingFeature, ...]
    # Strip resolution. WebP caps dimensions at 16383 px; sub-pixel features
    # keep their equivalent depth via fractional coverage in the generator.
    sample_count: int
    # Default sRGB tint for features without their own.
    tint: tuple[float, float, float]


class ThicknessZone(NamedTuple):
    """A tabulated vertical extent over a radial span of a *measured* bundle,
    which carries no feature table of its own."""

    name: str
    inner_km: float
    outer_km: float
    thickness_m: float


def _span(mid_km: float, width_km: float) -> tuple[float, float]:
    """The PDS Uranus/Neptune tables give mid radius + width; keep those
    source numbers verbatim and derive strip boundaries here."""
    return mid_km - width_km / 2.0, mid_km + width_km / 2.0


RING_SYSTEMS: dict[str, RingSystem] = {
    # PDS Jupiter table (De Pater et al. 2018 values); NSSDCA 2015 sheet noted
    # where it disagrees. All τ ≤ 8e-6 — visibility is entirely tuning.
    "jupiter": RingSystem(
        slug="jupiter",
        body="naif-599",
        bundle="primary",
        planet="Jupiter",
        covers="rings",
        sources=(
            RingSource(
                "https://pds-rings.seti.org/jupiter/jupiter_rings_table.html",
                NASA,
                NASA_LICENSE,
                "PDS Ring-Moon Systems Node vital-statistics table",
                "ring boundaries, normal optical depths and vertical extents "
                "(De Pater et al. 2018 values)",
            ),
            RingSource(
                "https://web.archive.org/web/20240624063359/https://nssdc.gsfc.nasa.gov/planetary/factsheet/jupringfact.html",
                NASA,
                NASA_LICENSE,
                "NSSDCA Jovian Rings Fact Sheet",
                "cross-checked boundaries, main-ring optical depth and particle albedo",
            ),
        ),
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
    # Saturn's D ring, inside the measured strip's 74,510 km inner edge.
    "saturn-inner": RingSystem(
        slug="saturn-inner",
        body="naif-699",
        bundle="inner",
        planet="Saturn",
        covers="D ring, inside the measured main-ring strip",
        sources=(
            RingSource(
                "https://pds-rings.seti.org/saturn/saturn_rings_table.html",
                NASA,
                NASA_LICENSE,
                "PDS Ring-Moon Systems Node vital-statistics table",
                "D ring boundaries, its optical depth range and the radii of "
                "the D68 and D72 ringlets",
            ),
            RingSource(
                "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
                NASA,
                NASA_LICENSE,
                "NSSDCA Saturnian Rings Fact Sheet",
                "cross-checked D ring edges",
            ),
        ),
        features=(
            # D ring: 66,900-74,491 km (PDS; NSSDCA outer edge 74,510),
            # τ 1e-5 to 1e-3 (PDS). The ramp puts the high end against the C
            # ring, reproducing the outward brightening rather than a flat mean.
            RingFeature("D Ring", 66_900, 74_491, 1e-3, "dusty", "fade_inner"),
            # "Contains narrow ringlets at 67,580 and 71,710 km" (PDS) — D68
            # and D72. Neither width nor τ is tabulated anywhere: nominal
            # 100 km / τ 1e-3 (the D ring's high end) stand-ins.
            RingFeature("D68 Ringlet", *_span(67_580, 100), 1e-3, "dusty"),
            RingFeature("D72 Ringlet", *_span(71_710, 100), 1e-3, "dusty"),
        ),
        # ~3.7 km/px; the nominal 100 km ringlets span ~27 px.
        sample_count=2_048,
        tint=(0.92, 0.90, 0.86),
    ),
    # Saturn's tenuous rings, outside the measured strip's 140,390 km edge.
    # The Roche Division and F ring fall inside the measured span and are not
    # repeated here.
    "saturn-outer": RingSystem(
        slug="saturn-outer",
        body="naif-699",
        bundle="outer",
        planet="Saturn",
        covers="tenuous outer rings, beyond the measured main-ring strip",
        sources=(
            RingSource(
                "https://pds-rings.seti.org/saturn/saturn_rings_table.html",
                NASA,
                NASA_LICENSE,
                "PDS Ring-Moon Systems Node vital-statistics table",
                "boundaries and normal optical depths of the Janus/Epimetheus, "
                "G and E rings, and the E ring's maximum vertical extent",
            ),
            RingSource(
                "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
                NASA,
                NASA_LICENSE,
                "NSSDCA Saturnian Rings Fact Sheet",
                "G and E ring vertical extents",
            ),
        ),
        features=(
            RingFeature("Janus/Epimetheus Ring", 149_000, 154_000, 1e-7, "dusty"),
            # Thickness 1e5 m (NSSDCA); at this bundle's 30,000 km thickness
            # scale an 8-bit row resolves it to ~118 km.
            RingFeature("G Ring", 166_000, 173_200, 1e-6, "dusty", thickness_km=100),
            # E ring: 180,000-480,000 km, τ 5e-6 (PDS), fed by and densest at
            # Enceladus' orbit (238,020 km) — split there so τ peaks at the
            # source moon instead of mid-ring. Fresh water-ice grains → the
            # bluish tint. Vertical extent 1e7 m (NSSDCA) flaring to "up to
            # ~30,000 km" (PDS) at the outer edge; the inward flare has no
            # tabulated figure, so that half holds the NSSDCA value.
            RingFeature(
                "E Ring (inner)",
                180_000,
                238_020,
                5e-6,
                "dusty",
                "fade_inner",
                tint=(0.85, 0.90, 1.00),
                thickness_km=10_000,
            ),
            RingFeature(
                "E Ring (outer)",
                238_020,
                480_000,
                5e-6,
                "dusty",
                "fade_outer",
                tint=(0.85, 0.90, 1.00),
                thickness_km=10_000,
                thickness_outer_km=30_000,
            ),
            # Absent by design: the Methone/Anthe/Pallene ring arcs (τ ~1e-7,
            # no tabulated widths, and azimuthal arcs a radial strip cannot
            # carry — they sit inside the 50× brighter E ring anyway), and the
            # Phoebe ring (7,720,000-12,500,000 km), which lies in Phoebe's
            # orbital plane rather than Saturn's equator, so the equatorial
            # annulus this pipeline builds would place it wrongly.
        ),
        # ~21 km/px; the narrowest feature is the 5,000 km Janus/Epimetheus ring.
        sample_count=16_000,
        tint=(0.88, 0.91, 0.96),
    ),
    # PDS Uranus table (Nicholson et al. 2018 values), mid radius ± width/2.
    # Narrow-ring widths are the PDS single figure; the eccentric rings vary
    # (NSSDCA: Alpha 4-10 km, Epsilon 20-96 km). Particles are charcoal-dark
    # (geometric albedo ~0.015-0.018, NSSDCA) → near-neutral tint.
    "uranus": RingSystem(
        slug="uranus",
        body="naif-799",
        bundle="primary",
        planet="Uranus",
        covers="rings",
        sources=(
            RingSource(
                "https://pds-rings.seti.org/uranus/uranus_rings_table.html",
                NASA,
                NASA_LICENSE,
                "PDS Ring-Moon Systems Node vital-statistics table",
                "ring mid-radii, widths and normal optical depths (Nicholson et "
                "al. 2018 values)",
            ),
            RingSource(
                "https://web.archive.org/web/20241013202357/https://nssdc.gsfc.nasa.gov/planetary/factsheet/uranringfact.html",
                NASA,
                NASA_LICENSE,
                "NSSDCA Uranian Rings Fact Sheet",
                "cross-checked radii, eccentric-ring width ranges and particle albedos",
            ),
        ),
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
    "neptune": RingSystem(
        slug="neptune",
        body="naif-899",
        bundle="primary",
        planet="Neptune",
        covers="rings",
        sources=(
            RingSource(
                "https://pds-rings.seti.org/neptune/neptune_rings_table.html",
                NASA,
                NASA_LICENSE,
                "PDS Ring-Moon Systems Node vital-statistics table",
                "ring mid-radii, widths and normal optical depths",
            ),
            RingSource(
                "https://web.archive.org/web/20240808174508/https://nssdc.gsfc.nasa.gov/planetary/factsheet/nepringfact.html",
                NASA,
                NASA_LICENSE,
                "NSSDCA Neptunian Rings Fact Sheet",
                "cross-checked radii and optical depths",
            ),
        ),
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


# Vertical extent of Saturn's *measured* main-ring bundle, which has no
# feature table to hang thickness_km on. All figures from the NSSDCA
# Saturnian Rings Fact Sheet "Thickness (m)" column; where it gives a range
# (B 5-10 m, A 10-30 m) the midpoint stands in, since the spread is spatial
# variation within the region rather than measurement uncertainty. Radii not
# covered here (the Roche Division and F ring past the A ring's outer edge)
# have no tabulated thickness and render flat.
SATURN_MEASURED_THICKNESS: tuple[ThicknessZone, ...] = (
    ThicknessZone("C Ring", 74_658, 91_975, 5.0),
    ThicknessZone("B Ring", 91_975, 117_507, 7.5),
    ThicknessZone("Cassini Division", 117_507, 122_340, 20.0),
    ThicknessZone("A Ring", 122_340, 136_780, 20.0),
)
