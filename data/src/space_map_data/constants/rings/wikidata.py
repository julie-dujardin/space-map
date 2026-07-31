"""Wikidata topic pages behind the ring panel.

The four system articles are the best-covered pages in this whole set,
and the individual rings are the worst: English Wikipedia folds every
named ring into "Rings of X", so not one feature row below has an
English article. French and Italian have essentially the full set.

Values are tuples because one topic occasionally splits across two Wikidata
items with disjoint sitelinks — no single item covers every language. Nothing
resolves to English when a locale is missing: a reader either gets the article
in the language they are reading in, or no link at all, so the coverage
comment on each row is the whole story about where a link will appear.

Locale codes follow ``constants.providers.LANGUAGES``; "all 12" means every
one of them. Coverage was read off Wikidata and drifts as articles are
written or merged — treat the comments as of 2026-07-31.
"""

# Keyed to the host body, matching ``RingSystem.body``.
RING_SYSTEM_PAGES: dict[str, tuple[str, ...]] = {
    "naif-599": ("Q3060",),  # rings of Jupiter — all 12
    "naif-699": ("Q194",),  # rings of Saturn — all 12
    "naif-799": ("Q171473",),  # rings of Uranus — all 12
    "naif-899": ("Q48400",),  # rings of Neptune — all 12
}

# Keyed "<RingSystem.slug>/<RingFeature.name>". Features absent here have no
# Wikidata entity — mostly the unnamed dust bands and ringlets.
RING_FEATURE_PAGES: dict[str, tuple[str, ...]] = {
    # Jupiter (bundle "primary"). Both gossamer entries and the Thebe
    # extension share one article.
    "jupiter/Halo": ("Q945984",),  # halo ring — fr it
    "jupiter/Main Ring": ("Q378590",),  # main ring — fr it
    "jupiter/Amalthea Gossamer Ring": ("Q3680049",),  # gossamer rings — fr it
    "jupiter/Thebe Gossamer Ring": ("Q3680049",),  # gossamer rings — fr it
    "jupiter/Thebe Extension": ("Q3680049",),  # gossamer rings — fr it
    # Saturn. The D68/D72 ringlets have no entity of their own.
    "saturn-inner/D Ring": ("Q2851405",),  # D ring — fr it
    "saturn-outer/Janus/Epimetheus Ring": ("Q18221522",),  # R/2006 S 1 — fr
    "saturn-outer/G Ring": ("Q1133273",),  # G ring — fr it
    "saturn-outer/E Ring (inner)": ("Q1109971",),  # E ring — fr it es
    "saturn-outer/E Ring (outer)": ("Q1109971",),  # E ring — fr it es
    # Uranus. The dust bands (Zeta C/CC, Alpha-4, Beta-Alpha, Eta C,
    # Delta C, Lambda C, Dust sheet) are unnamed on Wikidata.
    "uranus/Zeta": ("Q3616611",),  # ζ ring — it
    "uranus/Six": ("Q2851401",),  # 6 ring — fr it
    "uranus/Five": ("Q2851398",),  # 5 ring — fr it
    "uranus/Four": ("Q2851399",),  # 4 ring — fr it
    "uranus/Alpha": ("Q3680062",),  # α ring — fr it
    "uranus/Beta": ("Q615967",),  # β ring — fr it
    "uranus/Eta": ("Q2851444",),  # η ring — fr it
    "uranus/Gamma": ("Q2851426",),  # γ ring — fr it
    "uranus/Delta": ("Q2851408",),  # δ ring — fr it
    "uranus/Lambda": ("Q2851428",),  # λ ring — fr it
    "uranus/Epsilon": ("Q511479",),  # ε ring — fr it
    "uranus/Nu": ("Q628325",),  # ν ring — fr it
    "uranus/Mu": ("Q1132027",),  # μ ring — fr it
    # Neptune. The Galatea co-orbital dust has no entity.
    "neptune/Galle": ("Q3094782",),  # Galle ring — fr it
    "neptune/Le Verrier": ("Q3228065",),  # Le Verrier ring — fr it
    "neptune/Lassell": ("Q3218345",),  # Lassell ring — fr it
    "neptune/Arago": ("Q2859429",),  # Arago ring — fr de it
    "neptune/Adams": ("Q2824069",),  # Adams ring — fr de it
}

# Rings that exist as articles but not as rows in our feature tables.
RING_EXTRA_PAGES: dict[str, tuple[str, ...]] = {
    # Saturn's main rings arrive as measured Cassini profiles rather than
    # feature rows, so they have no key above.
    "saturn_a_ring": ("Q2739023",),  # A ring — fr it es
    "saturn_b_ring": ("Q2738054",),  # B ring — fr it es
    "saturn_c_ring": ("Q2257686",),  # C ring — fr it es
    "saturn_f_ring": ("Q2528985",),  # F ring — fr it es
    # Rings we deliberately do not render, kept so the panel can still name
    # them: Phoebe's ring is off Saturn's equator, the arcs are azimuthal.
    "saturn_phoebe_ring": ("Q19606402",),  # Phoebe ring — fr de
    "saturn_r2004_s1": ("Q2247392",),  # R/2004 S1 — fr it es
    "saturn_r2004_s2": ("Q3414984",),  # R/2004 S2 — fr it
    "neptune_arc_courage": ("Q3616602",),  # Courage — it
    "neptune_arc_liberte": ("Q3616607",),  # Liberté — it
    "neptune_arc_egalite_1": ("Q3616604",),  # Égalité 1 — it
    "neptune_arc_egalite_2": ("Q3616603",),  # Égalité 2 — it
    "neptune_arc_fraternite": ("Q3616605",),  # Fraternité — it
    # Ring systems on bodies we hold no ring geometry for.
    "chariklo": ("Q15981112",),  # rings of Chariklo — en fr zh ar ru pt it
    "rhea": ("Q2331877",),  # rings of Rhea — en fr zh ar ru pt es he pl
    "mercury_dust_ring": ("Q65154163",),  # Mercury's dust ring — fr
}

RING_CONCEPT_PAGES: dict[str, tuple[str, ...]] = {
    "ring_system": ("Q28951811",),  # ring system — en zh ar es
    "roche_limit": ("Q232086",),  # Roche limit — all 12
    "shepherd_moon": ("Q512492",),  # shepherd moon — all 12
    "optical_depth": ("Q890809",),  # optical depth — en fr ja zh ar ru pt de it es pl
    # The asteroid belt (Q2179) is already a group QID via ORBIT_CLASS_QIDS
    # (class-IMB/MBA/OMB), so it resolves through those pages.
}
