"""Named ring features of the four ringed giants — the one table behind both
the ring panel and the synthetic ring strips.

Rows follow the PDS Ring-Moon Systems Node "vital statistics" tables: every
named ring, division, gap, ringlet, structural region and arc those tables
carry, with the boundaries, optical depths and descriptive notes verbatim.
Official names and provisional designations are cross-checked against the IAU
Gazetteer's ring page. Only obvious typos in the PDS notes are corrected.

Each row doubles as the render manifest: `render` carries the strip
generator's tuning where the strips draw the feature (the τ picked from a
published range or limit, stand-in widths where only a radius is tabulated,
profiles, tints). Rows without it are catalogue-only — features the renderer
deliberately omits (Saturn's Phoebe ring sits in Phoebe's orbital plane rather
than Saturn's equator; Neptune's arcs are azimuthal structure a radial strip
cannot carry; everything inside Saturn's measured main-ring strip ships as
Cassini data instead). Each body also carries its strip `bundles` — the
per-bundle parameters (resolution, default tint, credited works) —
and `bundle_features` resolves what a bundle draws for
`scripts/generate_ring_profiles.py`; `tests/constants/test_ring_catalog.py`
asserts the explicit picks stay inside what is catalogued.

Geometry is stored the way its source tabulates it — inner/outer boundaries
for Jupiter and Saturn, mid radius + width for Uranus and Neptune — rather
than normalised here; `feature_span` and `feature_width` derive the other
form.
"""

from typing import Literal, NamedTuple

from space_map_data.constants.rings.attribution import (
    IAU,
    IAU_LICENSE,
    NASA,
    NASA_LICENSE,
    RingSource,
)

# What a feature *is*, in nomenclature terms — drives how the panel groups and
# counts children ("4 gaps · 4 ringlets"). "division" is reserved for the broad
# separations between named rings (Cassini, Roche); "gap" is a narrow clearing
# inside one. "region" marks the unnamed structural subdivisions of the B ring,
# "dust" the diffuse bands and extensions that carry no formal name.
FeatureKind = Literal["ring", "division", "gap", "ringlet", "region", "arc", "dust"]


class OpticalDepth(NamedTuple):
    """Normal optical depth as the source states it, which is rarely a single
    number: gaps are "~0", the Jovian main ring is an upper limit, and broad
    rings vary by an order of magnitude across their width."""

    low: float
    # None for a single stated value.
    high: float | None = None
    # Source wrote "~": the value is a round order-of-magnitude estimate.
    approximate: bool = False
    # Source wrote "<": `low` bounds the value from above.
    upper_limit: bool = False


class Render(NamedTuple):
    """Strip-generator tuning for a drawn feature. The row supplies geometry,
    τ and particle regime; fields here pick a value where the row has a range
    or a gap, or shape how the strip draws it."""

    # Bundle drawing this feature (`RingCatalog.bundles`); Saturn splits
    # around the measured main-ring strip.
    bundle: str = "primary"
    # τ pick where the row has a range, an upper limit or no figure.
    tau: float | None = None
    # Particle regime where the source states only a shape.
    particles: Literal["dense", "dusty"] | None = None
    # Radial shape: flat | fade_inner (ramps up toward the outer edge) |
    # fade_outer (decays toward the outer edge) | peak (triangular, mid-ring).
    profile: Literal["flat", "fade_inner", "fade_outer", "peak"] = "flat"
    # sRGB tint override for the color channel; None = bundle tint.
    tint: tuple[float, float, float] | None = None
    # Stand-in width where the row tabulates only a radius.
    width_km: float | None = None
    # Explicit boundaries, for drawing part of a feature (the E ring halves).
    span_km: tuple[float, float] | None = None
    # Vertical-extent overrides; None = the row's figure, or flat.
    thickness_km: float | None = None
    thickness_outer_km: float | None = None


# The plain case: drawn as catalogued, nothing to pick.
RENDERED: tuple[Render, ...] = (Render(),)


class CatalogFeature(NamedTuple):
    # Stable key, unique within the body: kebab-case, used for i18n keys,
    # Wikidata lookups (constants/rings/wikidata.py) and panel URLs.
    slug: str
    # English display name: the PDS Feature column, except that the Uranian
    # rings take the Greek letter or numeral everyone writes them with (PDS
    # spells them out because its table is ASCII). This *is* the English name
    # the panel shows — Wikidata labels are used only for other locales, since
    # theirs are translations of fr/it article titles and would rename the
    # IAU's "Huygens Gap" to "Huygens Division" in English.
    name: str
    kind: FeatureKind
    # Slug of the feature this one belongs to. Gaps, ringlets, regions and arcs
    # are radially contained by their parent; dust bands are named as
    # extensions of a ring they sit beside rather than inside.
    parent: str | None = None
    # Jupiter/Saturn tabulate boundaries…
    inner_km: float | None = None
    outer_km: float | None = None
    # …Uranus/Neptune a mid radius and a width. A few features have only a
    # radius: the ring is a moon's orbit and no width is published.
    mid_km: float | None = None
    width_km: float | None = None
    # Source wrote "~" on the radius (the co-orbital rings, where the figure
    # is the moon's semi-major axis).
    radius_approximate: bool = False
    optical_depth: OpticalDepth | None = None
    # Full vertical extent, where a source tabulates one.
    thickness_km: float | None = None
    # Uranus only, and only for the narrow rings whose shapes are fitted.
    eccentricity: float | None = None
    inclination_deg: float | None = None
    # Pre-IAU or provisional designation still in common use ("1986 U2R").
    designation: str | None = None
    # Particle regime from the PDS "Type" column: dense (macroscopic, back-
    # scatter bright) vs dusty (µm grains, forward-scatter bright). None where
    # the source states only a shape ("Narrow", "Faint, wide").
    particles: Literal["dense", "dusty"] | None = None
    # Shepherds, embedded moons and sources — PDS "Associated Moons", by name;
    # the export resolves them to object ids.
    moons: tuple[str, ...] = ()
    # PDS "Comments", verbatim. English only: there is no translated source,
    # so a locale either has a Wikipedia article for the feature or gets this.
    description: str | None = None
    # How the strip generator draws this feature; empty = catalogue-only.
    render: tuple[Render, ...] = ()


class RingBundle(NamedTuple):
    """One synthetic strip bundle: the per-bundle parameters for the rows
    whose ``Render.bundle`` names it. Bundles never overlap radially; each
    carries its own sample density and intensity/thickness scales, which is
    what lets one export hold both a τ~5 B ring and a τ~5e-6 E ring."""

    # Name within the body (what ``Render.bundle`` references), also its
    # export sub-directory. Ordered inner → outer by convention:
    # "inner", "primary", "outer".
    name: str
    # Directory name under sources/textures/rings/.
    slug: str
    # Noun phrase naming what this bundle covers, for generated
    # attribution/description text.
    covers: str
    # Works behind this bundle, carried into ring-metadata.yaml → credits.
    sources: tuple[RingSource, ...]
    # Strip resolution. WebP caps dimensions at 16383 px; sub-pixel features
    # keep their equivalent depth via fractional coverage in the generator.
    sample_count: int
    # Default sRGB tint for features without their own.
    tint: tuple[float, float, float]


class RingCatalog(NamedTuple):
    body: str
    sources: tuple[RingSource, ...]
    # Synthetic strip bundles; Saturn's main rings are measured Cassini data
    # (download/providers/bjj_rings.py), so its bundles skirt the measured
    # span.
    bundles: tuple[RingBundle, ...]
    features: tuple[CatalogFeature, ...]


def _pds_source(planet: str, url: str, contribution: str) -> RingSource:
    return RingSource(
        url,
        NASA,
        NASA_LICENSE,
        f"PDS Ring-Moon Systems Node vital statistics for {planet}'s rings",
        contribution,
    )


_IAU_RINGS = RingSource(
    "https://planetarynames.wr.usgs.gov/Page/Rings",
    IAU,
    IAU_LICENSE,
    "Gazetteer of Planetary Nomenclature, ring and ring gap nomenclature",
    "the official ring and gap names, and the provisional designations still "
    "in common use",
)

_PDS_FEATURES = (
    "boundaries, normal optical depths, associated moons and descriptive "
    "notes for every named ring, gap, ringlet and arc"
)


RING_CATALOGS: dict[str, RingCatalog] = {
    "naif-599": RingCatalog(
        body="naif-599",
        sources=(
            _pds_source(
                "Jupiter",
                "https://pds-rings.seti.org/jupiter/jupiter_rings_table.html",
                _PDS_FEATURES + ", and vertical thickness",
            ),
            _IAU_RINGS,
        ),
        bundles=(
            RingBundle(
                name="primary",
                slug="jupiter",
                covers="rings",
                sources=(
                    RingSource(
                        "https://pds-rings.seti.org/jupiter/jupiter_rings_table.html",
                        NASA,
                        NASA_LICENSE,
                        "PDS Ring-Moon Systems Node vital-statistics table",
                        "ring boundaries, normal optical depths and vertical "
                        "extents (De Pater et al. 2018 values)",
                    ),
                    RingSource(
                        "https://web.archive.org/web/20240624063359/https://nssdc.gsfc.nasa.gov/planetary/factsheet/jupringfact.html",
                        NASA,
                        NASA_LICENSE,
                        "NSSDCA Jovian Rings Fact Sheet",
                        "cross-checked boundaries, main-ring optical depth and "
                        "particle albedo",
                    ),
                ),
                # ~21 km/px; nothing narrower than the 6,700 km main ring.
                sample_count=8_192,
                tint=(1.00, 0.88, 0.78),
            ),
        ),
        features=(
            CatalogFeature(
                "halo",
                "Halo",
                "ring",
                inner_km=100_000,
                outer_km=122_400,
                optical_depth=OpticalDepth(1e-6, approximate=True),
                thickness_km=10_000,
                designation="1979 J1R",
                particles="dusty",
                description="Densest in a central core less than 1,000 km thick.",
                # Brightens toward the main ring; sub-µm grains scatter blue.
                render=(Render(profile="fade_inner", tint=(0.72, 0.80, 1.00)),),
            ),
            CatalogFeature(
                "main-ring",
                "Main Ring",
                "ring",
                inner_km=122_400,
                outer_km=129_100,
                optical_depth=OpticalDepth(8e-6, upper_limit=True),
                thickness_km=100,
                designation="1979 J2R",
                particles="dusty",
                moons=("Metis", "Adrastea"),
                description="Metis and Adrastea orbit near its outer edge.",
                # τ 5e-6 (NSSDCA) inside the PDS bound; particle albedo ~0.015
                # (NSSDCA) → dark red-brown tint.
                render=(Render(tau=5e-6, tint=(1.00, 0.83, 0.68)),),
            ),
            # The gossamer rings overlap: PDS gives both the same ill-defined
            # inner boundary, each running out to its source moon's orbit.
            # The IAU lists them as one feature, 1979 J3R.
            CatalogFeature(
                "amalthea-gossamer-ring",
                "Amalthea Gossamer Ring",
                "ring",
                inner_km=122_400,
                outer_km=181_350,
                optical_depth=OpticalDepth(5e-7, approximate=True),
                thickness_km=2_600,
                designation="1979 J3R",
                particles="dusty",
                moons=("Amalthea",),
                description=(
                    "Inner component of the Gossamer Ring, bounded by the orbit "
                    "of Amalthea. Inner boundary is not well defined."
                ),
                # Summing the overlapping gossamer rings in the strip
                # reproduces the observed staircase profile.
                render=RENDERED,
            ),
            CatalogFeature(
                "thebe-gossamer-ring",
                "Thebe Gossamer Ring",
                "ring",
                inner_km=122_400,
                outer_km=221_900,
                optical_depth=OpticalDepth(1e-7, approximate=True),
                thickness_km=8_800,
                designation="1979 J3R",
                particles="dusty",
                moons=("Thebe",),
                description=(
                    "Outer component of the Gossamer Ring, bounded by the orbit "
                    "of Thebe."
                ),
                render=RENDERED,
            ),
            CatalogFeature(
                "thebe-extension",
                "Thebe Extension",
                "dust",
                parent="thebe-gossamer-ring",
                inner_km=221_900,
                outer_km=270_000,
                optical_depth=OpticalDepth(1e-9, approximate=True),
                thickness_km=8_800,
                particles="dusty",
                moons=("Thebe",),
                description="A very faint outward extension to the Thebe Ring.",
                render=(Render(profile="fade_outer"),),
            ),
        ),
    ),
    "naif-699": RingCatalog(
        body="naif-699",
        sources=(
            _pds_source(
                "Saturn",
                "https://pds-rings.seti.org/saturn/saturn_rings_table.html",
                _PDS_FEATURES,
            ),
            _IAU_RINGS,
        ),
        bundles=(
            # The D ring, inside the measured strip's 74,510 km inner edge.
            RingBundle(
                name="inner",
                slug="saturn-inner",
                covers="D ring, inside the measured main-ring strip",
                sources=(
                    RingSource(
                        "https://pds-rings.seti.org/saturn/saturn_rings_table.html",
                        NASA,
                        NASA_LICENSE,
                        "PDS Ring-Moon Systems Node vital-statistics table",
                        "D ring boundaries, its optical depth range and the "
                        "radii of the D68 and D72 ringlets",
                    ),
                    RingSource(
                        "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
                        NASA,
                        NASA_LICENSE,
                        "NSSDCA Saturnian Rings Fact Sheet",
                        "cross-checked D ring edges",
                    ),
                ),
                # ~3.7 km/px; the nominal 100 km ringlets span ~27 px.
                sample_count=2_048,
                tint=(0.92, 0.90, 0.86),
            ),
            # The tenuous rings outside the measured strip's 140,390 km edge.
            # The Roche Division and F ring fall inside the measured span and
            # are not drawn here.
            RingBundle(
                name="outer",
                slug="saturn-outer",
                covers="tenuous outer rings, beyond the measured main-ring strip",
                sources=(
                    RingSource(
                        "https://pds-rings.seti.org/saturn/saturn_rings_table.html",
                        NASA,
                        NASA_LICENSE,
                        "PDS Ring-Moon Systems Node vital-statistics table",
                        "boundaries and normal optical depths of the "
                        "Janus/Epimetheus, G and E rings, and the E ring's "
                        "maximum vertical extent",
                    ),
                    RingSource(
                        "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
                        NASA,
                        NASA_LICENSE,
                        "NSSDCA Saturnian Rings Fact Sheet",
                        "G and E ring vertical extents",
                    ),
                ),
                # ~21 km/px; the narrowest feature is the 5,000 km
                # Janus/Epimetheus ring.
                sample_count=16_000,
                tint=(0.88, 0.91, 0.96),
            ),
        ),
        features=(
            CatalogFeature(
                "d-ring",
                "D Ring",
                "ring",
                inner_km=66_900,
                outer_km=74_491,
                optical_depth=OpticalDepth(1e-5, 1e-3),
                particles="dusty",
                description="Contains narrow ringlets at 67,580 and 71,710 km.",
                # The ramp puts the τ range's high end against the C ring,
                # reproducing the outward brightening rather than a flat mean.
                render=(Render(bundle="inner", tau=1e-3, profile="fade_inner"),),
            ),
            # PDS gives the two D-ring ringlets only as radii inside the note
            # above; D68/D72 are the names the Cassini literature uses for them.
            CatalogFeature(
                "d68-ringlet",
                "D68 Ringlet",
                "ringlet",
                parent="d-ring",
                mid_km=67_580,
                particles="dusty",
                # Neither width nor τ is tabulated anywhere: nominal 100 km
                # and the D ring's high end stand in.
                render=(Render(bundle="inner", tau=1e-3, width_km=100),),
            ),
            CatalogFeature(
                "d72-ringlet",
                "D72 Ringlet",
                "ringlet",
                parent="d-ring",
                mid_km=71_710,
                particles="dusty",
                render=(Render(bundle="inner", tau=1e-3, width_km=100),),
            ),
            # From here to the F ring the strips are measured Cassini data
            # (download/providers/bjj_rings.py): nothing to synthesise.
            CatalogFeature(
                "c-ring",
                "C Ring",
                "ring",
                inner_km=74_491,
                outer_km=91_975,
                optical_depth=OpticalDepth(0.05, 0.35),
                particles="dense",
                description=(
                    "Contains isolated “plateaus” among a surrounding, fainter ring."
                ),
            ),
            CatalogFeature(
                "colombo-gap",
                "Colombo Gap",
                "gap",
                parent="c-ring",
                inner_km=77_748,
                outer_km=77_926,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "titan-ringlet",
                "Titan Ringlet",
                "ringlet",
                parent="colombo-gap",
                inner_km=77_867,
                outer_km=77_890,
                optical_depth=OpticalDepth(4.0, approximate=True),
                particles="dense",
                moons=("Titan",),
                description=(
                    "Ringlet that occupies the outer third of the Colombo Gap. "
                    "Also known as the Colombo Ringlet."
                ),
            ),
            CatalogFeature(
                "maxwell-gap",
                "Maxwell Gap",
                "gap",
                parent="c-ring",
                inner_km=87_343,
                outer_km=87_610,
                optical_depth=OpticalDepth(0.0, approximate=True),
                description="Widest gap in the C Ring.",
            ),
            CatalogFeature(
                "maxwell-ringlet",
                "Maxwell Ringlet",
                "ringlet",
                parent="maxwell-gap",
                inner_km=87_480,
                outer_km=87_539,
                optical_depth=OpticalDepth(1.0, 3.0),
                particles="dense",
                description="A narrow, eccentric ringlet inside a gap in the C Ring.",
            ),
            CatalogFeature(
                "bond-gap",
                "Bond Gap",
                "gap",
                parent="c-ring",
                inner_km=88_686,
                outer_km=88_723,
                optical_depth=OpticalDepth(0.0, approximate=True),
                description="Gap due to second-order resonance with Mimas.",
            ),
            CatalogFeature(
                "bond-ringlet",
                "Bond Ringlet",
                "ringlet",
                parent="bond-gap",
                inner_km=88_702,
                outer_km=88_719,
                optical_depth=OpticalDepth(1.0, approximate=True),
                particles="dense",
                description=(
                    "A narrow, sharp-edged ringlet inside a gap in the C Ring."
                ),
            ),
            # Sits against the Dawes Gap's inner edge rather than inside it —
            # hence a child of the C ring, unlike the other named ringlets.
            CatalogFeature(
                "dawes-ringlet",
                "Dawes Ringlet",
                "ringlet",
                parent="c-ring",
                inner_km=90_138,
                outer_km=90_200,
                optical_depth=OpticalDepth(0.2, 1.0),
                particles="dense",
                description=(
                    "This feature has been referred to as a ringlet, but it is "
                    "not detached from the rest of the C ring."
                ),
            ),
            CatalogFeature(
                "dawes-gap",
                "Dawes Gap",
                "gap",
                parent="c-ring",
                inner_km=90_200,
                outer_km=90_221,
                optical_depth=OpticalDepth(0.0, approximate=True),
                description="Very narrow gap.",
            ),
            CatalogFeature(
                "b-ring",
                "B Ring",
                "ring",
                inner_km=91_975,
                outer_km=117_570,
                optical_depth=OpticalDepth(0.4, 5.0),
                particles="dense",
                description=(
                    "Contains fine structure on all scales. The most opaque of "
                    "Saturn's rings."
                ),
            ),
            CatalogFeature(
                "region-b1",
                "Region B1",
                "region",
                parent="b-ring",
                inner_km=91_975,
                outer_km=99_000,
                optical_depth=OpticalDepth(1.1, 1.5),
                particles="dense",
                description=(
                    "Innermost region of the B Ring. Characterized by "
                    "undulations in optical depth and I/F."
                ),
            ),
            # PDS: "1.5 and >4" — the two zones, not a continuous range.
            CatalogFeature(
                "region-b2",
                "Region B2",
                "region",
                parent="b-ring",
                inner_km=99_000,
                outer_km=104_000,
                optical_depth=OpticalDepth(1.5, 4.0),
                particles="dense",
                description=(
                    "Central region of the B Ring. Characterized by alternating "
                    "zones of high and low optical depth."
                ),
            ),
            CatalogFeature(
                "region-b3",
                "Region B3",
                "region",
                parent="b-ring",
                inner_km=104_000,
                outer_km=110_000,
                optical_depth=OpticalDepth(1.0, 5.0),
                particles="dense",
                description=(
                    "Central region of the B Ring. Characterized by high optical "
                    "depth. Median optical depth is 3.6, the highest of any "
                    "region in the rings."
                ),
            ),
            CatalogFeature(
                "region-b4",
                "Region B4",
                "region",
                parent="b-ring",
                inner_km=110_000,
                outer_km=116_500,
                optical_depth=OpticalDepth(2.0, 3.0),
                particles="dense",
                description=(
                    "Outer region of the B Ring. Here the optical depth "
                    "gradually decreases, but in an irregular way."
                ),
            ),
            # PDS: "0.5 to >5".
            CatalogFeature(
                "region-b5",
                "Region B5",
                "region",
                parent="b-ring",
                inner_km=116_500,
                outer_km=117_500,
                optical_depth=OpticalDepth(0.5, 5.0),
                particles="dense",
                moons=("Mimas",),
                description=(
                    "Outermost region of the B Ring, affected by its highly "
                    "variable outer edge."
                ),
            ),
            CatalogFeature(
                "cassini-division",
                "Cassini Division",
                "division",
                inner_km=117_500,
                outer_km=122_050,
                optical_depth=OpticalDepth(0.0, 0.2),
                particles="dense",
                description=(
                    "The prominent gap between the A and B Rings. It contains "
                    "several features of low optical depth."
                ),
            ),
            CatalogFeature(
                "huygens-gap",
                "Huygens Gap",
                "gap",
                parent="cassini-division",
                inner_km=117_500,
                outer_km=117_930,
                optical_depth=OpticalDepth(0.0, approximate=True),
                moons=("Mimas",),
            ),
            CatalogFeature(
                "huygens-ringlet",
                "Huygens Ringlet",
                "ringlet",
                parent="huygens-gap",
                inner_km=117_806,
                outer_km=117_824,
                optical_depth=OpticalDepth(1.0, 2.0),
                particles="dense",
            ),
            CatalogFeature(
                "strange-ringlet",
                "Strange Ringlet",
                "ringlet",
                parent="huygens-gap",
                inner_km=117_907,
                outer_km=117_909,
                particles="dense",
            ),
            # PDS notes these boundaries are approximate (its Table 3).
            CatalogFeature(
                "herschel-gap",
                "Herschel Gap",
                "gap",
                parent="cassini-division",
                inner_km=118_188,
                outer_km=118_284,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "herschel-ringlet",
                "Herschel Ringlet",
                "ringlet",
                parent="herschel-gap",
                inner_km=118_234,
                outer_km=118_263,
                optical_depth=OpticalDepth(0.1, approximate=True),
                particles="dense",
                description=(
                    "A narrow, eccentric, inclined ringlet near the inner edge "
                    "of the Cassini Division."
                ),
            ),
            CatalogFeature(
                "russell-gap",
                "Russell Gap",
                "gap",
                parent="cassini-division",
                inner_km=118_590,
                outer_km=118_628,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "jeffreys-gap",
                "Jeffreys Gap",
                "gap",
                parent="cassini-division",
                inner_km=118_930,
                outer_km=118_967,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "kuiper-gap",
                "Kuiper Gap",
                "gap",
                parent="cassini-division",
                inner_km=119_402,
                outer_km=119_406,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "laplace-gap",
                "Laplace Gap",
                "gap",
                parent="cassini-division",
                inner_km=119_845,
                outer_km=120_086,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "laplace-ringlet",
                "Laplace Ringlet",
                "ringlet",
                parent="laplace-gap",
                inner_km=120_037,
                outer_km=120_078,
                optical_depth=OpticalDepth(1.0, approximate=True),
                particles="dense",
            ),
            CatalogFeature(
                "bessel-gap",
                "Bessel Gap",
                "gap",
                parent="cassini-division",
                inner_km=120_231,
                outer_km=120_244,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "barnard-gap",
                "Barnard Gap",
                "gap",
                parent="cassini-division",
                inner_km=120_304,
                outer_km=120_316,
                optical_depth=OpticalDepth(0.0, approximate=True),
            ),
            CatalogFeature(
                "a-ring",
                "A Ring",
                "ring",
                inner_km=122_050,
                outer_km=136_770,
                optical_depth=OpticalDepth(0.4, 1.0),
                particles="dense",
                description=(
                    "A fairly uniform ring with many density and bending waves, "
                    "especially near its outer edge."
                ),
            ),
            CatalogFeature(
                "encke-gap",
                "Encke Gap",
                "gap",
                parent="a-ring",
                inner_km=133_423,
                outer_km=133_745,
                optical_depth=OpticalDepth(0.0, approximate=True),
                moons=("Pan",),
                description=(
                    "A gap in the A Ring maintained by the embedded moon Pan. "
                    "One or more faint ringlets are also present."
                ),
            ),
            CatalogFeature(
                "keeler-gap",
                "Keeler Gap",
                "gap",
                parent="a-ring",
                inner_km=136_487,
                outer_km=136_522,
                optical_depth=OpticalDepth(0.0, approximate=True),
                moons=("Daphnis",),
                description=(
                    "A narrow gap in the outer A Ring maintained by the embedded "
                    "moon Daphnis."
                ),
            ),
            CatalogFeature(
                "roche-division",
                "Roche Division",
                "division",
                inner_km=136_770,
                outer_km=139_380,
                optical_depth=OpticalDepth(1e-4, approximate=True),
                particles="dusty",
                moons=("Atlas", "Prometheus"),
                description=(
                    "The separation between the outer edge of the A Ring and the "
                    "F Ring."
                ),
            ),
            CatalogFeature(
                "f-ring",
                "F Ring",
                "ring",
                inner_km=139_826,
                outer_km=140_612,
                optical_depth=OpticalDepth(0.01, 0.2),
                moons=("Prometheus", "Pandora"),
                description=(
                    "A complex, narrow, eccentric, inclined ring with a denser "
                    "core at 140,224 km, demonstrating a wide variety of "
                    "quasi-stable and ephemeral structure."
                ),
            ),
            CatalogFeature(
                "janus-epimetheus-ring",
                "Janus/Epimetheus Ring",
                "ring",
                inner_km=149_000,
                outer_km=154_000,
                optical_depth=OpticalDepth(1e-7),
                particles="dusty",
                moons=("Janus", "Epimetheus"),
                description=(
                    "A narrow, very faint ring in the region occupied by Janus "
                    "and Epimetheus."
                ),
                render=(Render(bundle="outer"),),
            ),
            CatalogFeature(
                "g-ring",
                "G Ring",
                "ring",
                inner_km=166_000,
                outer_km=173_200,
                optical_depth=OpticalDepth(1e-6),
                particles="dusty",
                moons=("Aegaeon",),
                description="A faint, isolated dust ring.",
                # Thickness 1e5 m (NSSDCA, not in the PDS table); at the outer
                # bundle's 30,000 km scale an 8-bit row resolves it to ~118 km.
                render=(Render(bundle="outer", thickness_km=100),),
            ),
            CatalogFeature(
                "e-ring",
                "E Ring",
                "ring",
                inner_km=180_000,
                outer_km=480_000,
                optical_depth=OpticalDepth(5e-6),
                thickness_km=30_000,
                particles="dusty",
                moons=("Enceladus",),
                description=(
                    "A broad, faint dust ring encompassing the orbits of Mimas "
                    "through Dione. Densest near the orbit of Enceladus. Up to "
                    "about 30,000 km in vertical extent."
                ),
                # Split at Enceladus' orbit (238,020 km) so τ peaks at the
                # source moon instead of mid-ring. Fresh water-ice grains →
                # the bluish tint. Vertical extent 1e7 m (NSSDCA) flaring to
                # the tabulated 30,000 km at the outer edge; the inward flare
                # has no figure, so that half holds the NSSDCA value.
                render=(
                    Render(
                        bundle="outer",
                        span_km=(180_000, 238_020),
                        profile="fade_inner",
                        tint=(0.85, 0.90, 1.00),
                        thickness_km=10_000,
                    ),
                    Render(
                        bundle="outer",
                        span_km=(238_020, 480_000),
                        profile="fade_outer",
                        tint=(0.85, 0.90, 1.00),
                        thickness_km=10_000,
                        thickness_outer_km=30_000,
                    ),
                ),
            ),
            # The co-orbital rings: PDS tabulates one radius each, the source
            # moon's orbit, and no width. Not rendered: they sit inside the
            # 50× brighter E ring.
            CatalogFeature(
                "methone-ring",
                "Methone Ring",
                "ring",
                mid_km=194_440,
                radius_approximate=True,
                optical_depth=OpticalDepth(1e-7, approximate=True),
                particles="dusty",
                moons=("Methone",),
                description=(
                    "A narrow, very faint ring in the region occupied by Methone."
                ),
            ),
            CatalogFeature(
                "anthe-ring",
                "Anthe Ring",
                "ring",
                mid_km=197_655,
                radius_approximate=True,
                optical_depth=OpticalDepth(1e-7, approximate=True),
                particles="dusty",
                moons=("Anthe",),
                description="A narrow, very faint ring in the orbit of Anthe.",
            ),
            CatalogFeature(
                "pallene-ring",
                "Pallene Ring",
                "ring",
                mid_km=212_280,
                radius_approximate=True,
                optical_depth=OpticalDepth(1e-7, approximate=True),
                particles="dusty",
                moons=("Pallene",),
                description=(
                    "A narrow, very faint ring in the region occupied by Pallene."
                ),
            ),
            # Not rendered: lies in Phoebe's orbital plane, not Saturn's
            # equator, so the equatorial annulus would place it wrongly.
            CatalogFeature(
                "phoebe-ring",
                "Phoebe Ring",
                "ring",
                inner_km=7_720_000,
                outer_km=12_500_000,
                optical_depth=OpticalDepth(2e-8, approximate=True),
                thickness_km=2_400_000,
                particles="dusty",
                moons=("Phoebe",),
                description=(
                    "A broad, faint ring in the orbit of Phoebe with a vertical "
                    "extent of about 2,400,000 km."
                ),
            ),
        ),
    ),
    "naif-799": RingCatalog(
        body="naif-799",
        sources=(
            _pds_source(
                "Uranus",
                "https://pds-rings.seti.org/uranus/uranus_rings_table.html",
                _PDS_FEATURES + ", and the eccentricities and inclinations of "
                "the narrow rings",
            ),
            _IAU_RINGS,
        ),
        bundles=(
            # Particles are charcoal-dark (geometric albedo ~0.015-0.018,
            # NSSDCA) → near-neutral tint.
            RingBundle(
                name="primary",
                slug="uranus",
                covers="rings",
                sources=(
                    RingSource(
                        "https://pds-rings.seti.org/uranus/uranus_rings_table.html",
                        NASA,
                        NASA_LICENSE,
                        "PDS Ring-Moon Systems Node vital-statistics table",
                        "ring mid-radii, widths and normal optical depths "
                        "(Nicholson et al. 2018 values)",
                    ),
                    RingSource(
                        "https://web.archive.org/web/20241013202357/https://nssdc.gsfc.nasa.gov/planetary/factsheet/uranringfact.html",
                        NASA,
                        NASA_LICENSE,
                        "NSSDCA Uranian Rings Fact Sheet",
                        "cross-checked radii, eccentric-ring width ranges and "
                        "particle albedos",
                    ),
                ),
                # ~5 km/px: the classical narrow rings land on ~1 px each.
                sample_count=16_000,
                tint=(0.88, 0.89, 0.92),
            ),
        ),
        features=(
            CatalogFeature(
                "zeta-cc",
                "ζ CC",
                "dust",
                parent="zeta",
                mid_km=30_863,
                width_km=8_050,
                optical_depth=OpticalDepth(1e-4, approximate=True),
                particles="dusty",
                description="Extension of the ζ ring.",
                render=RENDERED,
            ),
            CatalogFeature(
                "zeta-c",
                "ζ C",
                "dust",
                parent="zeta",
                mid_km=36_639,
                width_km=2_960,
                optical_depth=OpticalDepth(5e-4, approximate=True),
                particles="dusty",
                description="Extension of the ζ ring.",
                render=RENDERED,
            ),
            CatalogFeature(
                "dust-sheet",
                "Dust sheet",
                "dust",
                mid_km=38_440,
                width_km=23_200,
                optical_depth=OpticalDepth(0.005),
                particles="dusty",
                description="A sheet of material that permeates the ring system.",
                render=RENDERED,
            ),
            CatalogFeature(
                "zeta",
                "ζ Ring",
                "ring",
                mid_km=39_600,
                width_km=3_500,
                optical_depth=OpticalDepth(0.0045, approximate=True),
                designation="1986 U2R",
                particles="dusty",
                description=(
                    "The ζ ring is the innermost ring. Wide and diffuse when "
                    "originally observed in Voyager images, its estimated "
                    "optical depth was then much lower than the modern value. "
                    "This may be due to assumptions about particle albedo and "
                    "phase function, or to actual variation of the ring "
                    "properties over time and/or wavelength."
                ),
                render=RENDERED,
            ),
            CatalogFeature(
                "six",
                "6 Ring",
                "ring",
                mid_km=41_838,
                width_km=1.53,
                optical_depth=OpticalDepth(0.3, approximate=True),
                eccentricity=0.00102,
                inclination_deg=0.0607,
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "five",
                "5 Ring",
                "ring",
                mid_km=42_234,
                width_km=2.28,
                optical_depth=OpticalDepth(0.5, approximate=True),
                eccentricity=0.0019,
                inclination_deg=0.0559,
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "four",
                "4 Ring",
                "ring",
                mid_km=42_571,
                width_km=2.33,
                optical_depth=OpticalDepth(0.3, approximate=True),
                eccentricity=0.00106,
                inclination_deg=0.032,
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "alpha-4",
                "α–4",
                "dust",
                mid_km=43_027,
                width_km=3_353,
                optical_depth=OpticalDepth(0.002),
                particles="dusty",
                description="Dust ring between the 4 and α rings.",
                render=RENDERED,
            ),
            CatalogFeature(
                "alpha",
                "α Ring",
                "ring",
                mid_km=44_718,
                width_km=8.46,
                optical_depth=OpticalDepth(0.4, approximate=True),
                eccentricity=0.00076,
                inclination_deg=0.015,
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "beta-alpha",
                "β–α",
                "dust",
                mid_km=44_879,
                width_km=312,
                optical_depth=OpticalDepth(0.002),
                particles="dusty",
                description="Dust ring between the α and β rings.",
                render=RENDERED,
            ),
            CatalogFeature(
                "beta",
                "β Ring",
                "ring",
                mid_km=45_661,
                width_km=9.49,
                optical_depth=OpticalDepth(0.3, approximate=True),
                eccentricity=0.000442,
                inclination_deg=0.005,
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "eta",
                "η Ring",
                "ring",
                mid_km=47_176,
                width_km=1.6,
                optical_depth=OpticalDepth(0.4, approximate=True),
                particles="dense",
                render=RENDERED,
            ),
            CatalogFeature(
                "eta-c",
                "η C",
                "dust",
                parent="eta",
                mid_km=47_201,
                width_km=40,
                optical_depth=OpticalDepth(0.02),
                particles="dusty",
                description="Extension of the η ring.",
                render=RENDERED,
            ),
            CatalogFeature(
                "gamma",
                "γ Ring",
                "ring",
                mid_km=47_627,
                width_km=2.15,
                optical_depth=OpticalDepth(0.3, approximate=True),
                eccentricity=0.001092,
                inclination_deg=0.0,
                particles="dense",
                moons=("Ophelia",),
                description=(
                    "Its shape also contains an m = 0 mode of 5.15 km amplitude."
                ),
                render=RENDERED,
            ),
            CatalogFeature(
                "delta-c",
                "δ C",
                "dust",
                parent="delta",
                mid_km=48_289,
                width_km=15,
                optical_depth=OpticalDepth(0.03),
                particles="dusty",
                description="Extension of the δ ring.",
                render=RENDERED,
            ),
            # PDS leaves the δ ring's eccentricity column blank.
            CatalogFeature(
                "delta",
                "δ Ring",
                "ring",
                mid_km=48_300,
                width_km=4.6,
                optical_depth=OpticalDepth(0.5, approximate=True),
                inclination_deg=0.001,
                particles="dense",
                moons=("Cordelia",),
                description="Its shape is dominated by an m = 2 mode.",
                render=RENDERED,
            ),
            CatalogFeature(
                "lambda-c",
                "λ C",
                "dust",
                parent="lambda",
                mid_km=49_936,
                width_km=3.1,
                optical_depth=OpticalDepth(0.15),
                particles="dusty",
                description="Dust ring interior to the λ ring.",
                render=RENDERED,
            ),
            CatalogFeature(
                "lambda",
                "λ Ring",
                "ring",
                mid_km=50_024,
                width_km=2.3,
                optical_depth=OpticalDepth(0.1, approximate=True),
                eccentricity=0.0,
                inclination_deg=0.0,
                designation="1986 U1R",
                particles="dusty",
                description="Contains clumps.",
                render=RENDERED,
            ),
            CatalogFeature(
                "epsilon",
                "ε Ring",
                "ring",
                mid_km=51_149,
                width_km=58.1,
                optical_depth=OpticalDepth(0.5, 2.3),
                eccentricity=0.00794,
                inclination_deg=0.0,
                particles="dense",
                moons=("Cordelia", "Ophelia"),
                description="Shepherded by Cordelia and Ophelia.",
                # Geometric mean of the 0.5-2.3 range.
                render=(Render(tau=1.1),),
            ),
            CatalogFeature(
                "nu",
                "ν Ring",
                "ring",
                mid_km=67_300,
                width_km=3_800,
                optical_depth=OpticalDepth(5.6e-6),
                eccentricity=0.0,
                inclination_deg=0.0,
                designation="R/2003 U 2",
                particles="dusty",
                moons=("Portia", "Rosalind"),
                description="Very faint; bounded by Portia and Rosalind.",
                # Peaked dust pair with µ; colors from de Pater et al. 2006:
                # ν red, µ blue.
                render=(Render(profile="peak", tint=(1.00, 0.80, 0.70)),),
            ),
            CatalogFeature(
                "mu",
                "μ Ring",
                "ring",
                mid_km=97_700,
                width_km=17_000,
                optical_depth=OpticalDepth(8.5e-6),
                eccentricity=0.0,
                inclination_deg=0.0,
                designation="R/2003 U 1",
                particles="dusty",
                moons=("Mab",),
                description="Very faint; peaks at the orbit of Mab.",
                render=(Render(profile="peak", tint=(0.65, 0.78, 1.00)),),
            ),
        ),
    ),
    "naif-899": RingCatalog(
        body="naif-899",
        sources=(
            _pds_source(
                "Neptune",
                "https://pds-rings.seti.org/neptune/neptune_rings_table.html",
                _PDS_FEATURES,
            ),
            _IAU_RINGS,
        ),
        bundles=(
            # The system is dust-dominated → slightly reddish tint.
            RingBundle(
                name="primary",
                slug="neptune",
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
                # ~2.7 km/px; Adams (15 km) spans ~6 px.
                sample_count=8_192,
                tint=(1.00, 0.92, 0.86),
            ),
        ),
        features=(
            CatalogFeature(
                "galle",
                "Galle",
                "ring",
                mid_km=42_000,
                width_km=2_000,
                optical_depth=OpticalDepth(1e-4),
                designation="1989 N3R",
                description="A faint and poorly understood ring.",
                # PDS states no particle regime for Galle, Le Verrier or
                # Adams; broad and faint → dusty, narrow → dense.
                render=(Render(particles="dusty"),),
            ),
            # PDS gives the width as "<100".
            CatalogFeature(
                "le-verrier",
                "Le Verrier",
                "ring",
                mid_km=53_200,
                width_km=100,
                optical_depth=OpticalDepth(0.003),
                designation="1989 N2R",
                moons=("Despina",),
                description="A narrow, axisymmetric ring.",
                # τ 0.003 (PDS; NSSDCA ~0.01).
                render=(Render(particles="dense"),),
            ),
            CatalogFeature(
                "lassell",
                "Lassell",
                "ring",
                mid_km=55_200,
                width_km=4_000,
                optical_depth=OpticalDepth(1e-4),
                particles="dusty",
                description=(
                    "A uniform, faint ring extending outward from Le Verrier."
                ),
                render=RENDERED,
            ),
            CatalogFeature(
                "arago",
                "Arago",
                "ring",
                parent="lassell",
                mid_km=57_200,
                description="A brightness enhancement at the outer edge of Lassell.",
                # No width or τ tabulated anywhere: nominal 100 km / τ 1e-4.
                render=(Render(tau=1e-4, width_km=100, particles="dusty"),),
            ),
            # PDS lists this as "Unnamed"; it is the dust co-orbital with
            # Galatea, with neither width nor optical depth tabulated.
            CatalogFeature(
                "galatea-ring",
                "Galatea co-orbital dust",
                "dust",
                mid_km=61_953,
                particles="dusty",
                moons=("Galatea",),
                description="A ring of dust in the orbit of Galatea.",
                # No width or τ tabulated: nominal 50 km / τ 1e-4.
                render=(Render(tau=1e-4, width_km=50),),
            ),
            CatalogFeature(
                "adams",
                "Adams",
                "ring",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.003, 0.1),
                designation="1989 N1R",
                moons=("Galatea",),
                description=(
                    "A narrow ring containing the arcs. It shows radial wiggles "
                    "due to perturbations from nearby Galatea."
                ),
                # Continuous-ring τ (NSSDCA's 0.01-0.1 includes the arcs); the
                # arcs themselves are azimuthal structure a radial strip
                # cannot carry.
                render=(Render(tau=0.003, particles="dense"),),
            ),
            # The five arcs share the Adams ring's radius and differ only in
            # longitude, which a radial catalogue cannot express; PDS tabulates
            # Égalité 1 and 2 as one row, and Wikidata keeps them apart. Listed
            # in increasing longitude — the only order they have — which puts
            # Égalité 2 first: PDS anchors it 10.7° ahead of Fraternité and puts
            # Liberté a further 12° ahead of Égalité 1, so 2 is the trailing half
            # of the pair and 1 the leading one.
            CatalogFeature(
                "fraternite",
                "Fraternité",
                "arc",
                parent="adams",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.1, approximate=True),
                moons=("Galatea",),
                description=(
                    "The brightest of the five ring arcs embedded in the Adams "
                    "Ring, Fraternité is the trailing arc."
                ),
            ),
            CatalogFeature(
                "egalite-2",
                "Égalité 2",
                "arc",
                parent="adams",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.1, approximate=True),
                moons=("Galatea",),
                description=(
                    "The trailing half of a double arc in the Adams Ring, located "
                    "10.7 degrees ahead of Fraternité."
                ),
            ),
            CatalogFeature(
                "egalite-1",
                "Égalité 1",
                "arc",
                parent="adams",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.1, approximate=True),
                moons=("Galatea",),
                description=(
                    "The leading half of a double arc in the Adams Ring, with "
                    "Liberté 12 degrees ahead of it."
                ),
            ),
            CatalogFeature(
                "liberte",
                "Liberté",
                "arc",
                parent="adams",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.1, approximate=True),
                moons=("Galatea",),
                description=(
                    "Ring arc in the Adams Ring, between the Égalité and Courage "
                    "arcs and 12 degrees ahead of Égalité 1."
                ),
            ),
            CatalogFeature(
                "courage",
                "Courage",
                "arc",
                parent="adams",
                mid_km=62_933,
                width_km=15,
                optical_depth=OpticalDepth(0.1, approximate=True),
                moons=("Galatea",),
                description=(
                    "The dimmest of the five ring arcs embedded in the Adams "
                    "Ring, about 7.3 degrees ahead of Liberté in longitude."
                ),
            ),
        ),
    ),
}


def feature_span(feature: CatalogFeature) -> tuple[float, float] | None:
    """Inner/outer boundary in km, derived from mid radius + width when that is
    how the source tabulates the feature. None when only a radius is known."""
    if feature.inner_km is not None and feature.outer_km is not None:
        return feature.inner_km, feature.outer_km
    if feature.mid_km is not None and feature.width_km is not None:
        half = feature.width_km / 2.0
        return feature.mid_km - half, feature.mid_km + half
    return None


def feature_width(feature: CatalogFeature) -> float | None:
    """Radial width in km, as tabulated or derived from the boundaries."""
    if feature.width_km is not None:
        return feature.width_km
    if feature.inner_km is not None and feature.outer_km is not None:
        return feature.outer_km - feature.inner_km
    return None


def feature_mid(feature: CatalogFeature) -> float | None:
    """Mid radius in km, as tabulated or derived from the boundaries."""
    if feature.mid_km is not None:
        return feature.mid_km
    if feature.inner_km is not None and feature.outer_km is not None:
        return (feature.inner_km + feature.outer_km) / 2.0
    return None


class RenderedFeature(NamedTuple):
    """A catalogue row resolved to the values the strip generator rasterises.
    Features may overlap radially (Jupiter's gossamer rings nest inside the
    main ring's span); the generator sums overlaps."""

    slug: str
    inner_km: float
    outer_km: float
    optical_depth: float
    # "dense" = macroscopic particles (backscatter-bright); "dusty" = µm dust
    # (forward-scatter-bright). Drives per-channel weights only.
    kind: Literal["dense", "dusty"]
    profile: Literal["flat", "fade_inner", "fade_outer", "peak"]
    tint: tuple[float, float, float] | None
    # Full vertical extent. 0 = not tabulated / negligible — rendered flat.
    thickness_km: float
    thickness_outer_km: float | None


def resolve_render(row: CatalogFeature, render: Render) -> RenderedFeature:
    span = render.span_km or feature_span(row)
    if span is None:
        mid = feature_mid(row)
        if mid is None or render.width_km is None:
            raise ValueError(f"{row.slug}: no boundaries and no stand-in width")
        span = (mid - render.width_km / 2.0, mid + render.width_km / 2.0)
    tau = render.tau
    if tau is None:
        depth = row.optical_depth
        if depth is None or depth.high is not None or depth.upper_limit:
            raise ValueError(f"{row.slug}: catalogue τ is not a single figure")
        tau = depth.low
    kind = render.particles or row.particles
    if kind is None:
        raise ValueError(f"{row.slug}: no particle regime in the catalogue")
    thickness = render.thickness_km
    if thickness is None:
        thickness = row.thickness_km or 0.0
    return RenderedFeature(
        slug=row.slug,
        inner_km=span[0],
        outer_km=span[1],
        optical_depth=tau,
        kind=kind,
        profile=render.profile,
        tint=render.tint,
        thickness_km=thickness,
        thickness_outer_km=render.thickness_outer_km,
    )


def bundle_features(catalog: RingCatalog, bundle: str) -> tuple[RenderedFeature, ...]:
    """The rows a bundle draws, resolved, in catalogue order."""
    return tuple(
        resolve_render(row, render)
        for row in catalog.features
        for render in row.render
        if render.bundle == bundle
    )


class ThicknessZone(NamedTuple):
    """A tabulated vertical extent over a radial span of the *measured*
    Saturn bundle, which draws no catalogue rows of its own."""

    name: str
    inner_km: float
    outer_km: float
    thickness_m: float


# All figures from the NSSDCA Saturnian Rings Fact Sheet "Thickness (m)"
# column; where it gives a range (B 5-10 m, A 10-30 m) the midpoint stands
# in, since the spread is spatial variation within the region rather than
# measurement uncertainty. Radii not covered here (the Roche Division and F
# ring past the A ring's outer edge) have no tabulated thickness and render
# flat.
SATURN_MEASURED_THICKNESS: tuple[ThicknessZone, ...] = (
    ThicknessZone("C Ring", 74_658, 91_975, 5.0),
    ThicknessZone("B Ring", 91_975, 117_507, 7.5),
    ThicknessZone("Cassini Division", 117_507, 122_340, 20.0),
    ThicknessZone("A Ring", 122_340, 136_780, 20.0),
)
