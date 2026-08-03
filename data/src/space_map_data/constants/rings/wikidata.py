"""Wikidata topic pages behind the ring panel.

The four system articles are the best-covered pages in this whole set,
and the individual rings are the worst: English Wikipedia folds every
named ring into "Rings of X", so of every feature row below only the
Cassini Division has an English article. French and Italian have
essentially the full set. Features with no article at all fall back to
the PDS note carried on their catalogue row.

Values are tuples because one topic occasionally splits across two Wikidata
items with disjoint sitelinks — no single item covers every language. Nothing
resolves to English when a locale is missing: a reader either gets the article
in the language they are reading in, or no link at all, so the coverage
comment on each row is the whole story about where a link will appear.

Locale codes follow ``constants.providers.LANGUAGES``; "all 12" means every
one of them. Coverage was read off Wikidata and drifts as articles are
written or merged — treat the comments as of 2026-08-02.
"""

# Keyed to the host body, matching ``RingCatalog.body``.
RING_SYSTEM_PAGES: dict[str, tuple[str, ...]] = {
    "naif-599": ("Q3060",),  # rings of Jupiter — all 12
    "naif-699": ("Q194",),  # rings of Saturn — all 12
    "naif-799": ("Q171473",),  # rings of Uranus — all 12
    "naif-899": ("Q48400",),  # rings of Neptune — all 12
}

# Keyed "<body>/<CatalogFeature.slug>". Features absent here have no Wikidata
# entity — the gaps and ringlets resolved by Cassini occultations, the unnamed
# dust bands, and the B ring's structural regions.
RING_FEATURE_PAGES: dict[str, tuple[str, ...]] = {
    # Jupiter. Both gossamer rings and the Thebe extension share one article.
    "naif-599/halo": ("Q945984",),  # halo ring — fr it
    "naif-599/main-ring": ("Q378590",),  # main ring — fr it
    "naif-599/amalthea-gossamer-ring": ("Q3680049",),  # gossamer rings — fr it
    "naif-599/thebe-gossamer-ring": ("Q3680049",),  # gossamer rings — fr it
    "naif-599/thebe-extension": ("Q3680049",),  # gossamer rings — fr it
    # Saturn. The gaps that have articles carry them under the "division"
    # name French, Italian and Spanish use for them.
    "naif-699/d-ring": ("Q2851405",),  # D ring — fr it
    "naif-699/c-ring": ("Q2257686",),  # C ring — fr it es
    "naif-699/colombo-gap": ("Q927220",),  # Division de Colombo — fr it es
    "naif-699/maxwell-gap": ("Q3032379",),  # Division de Maxwell — fr it
    "naif-699/b-ring": ("Q2738054",),  # B ring — fr it es
    "naif-699/cassini-division": ("Q508315",),  # en fr ja ar ru de it es pl
    "naif-699/huygens-gap": ("Q3032373",),  # Division de Huygens — fr it
    "naif-699/a-ring": ("Q2739023",),  # A ring — fr it es
    "naif-699/encke-gap": ("Q2426816",),  # Encke Gap — fr ja de it es pl
    "naif-699/keeler-gap": ("Q3268408",),  # Division de Keeler — fr ja it es pl
    "naif-699/roche-division": ("Q3680178",),  # Roche Division — fr it
    "naif-699/f-ring": ("Q2528985",),  # F ring — fr it es
    "naif-699/janus-epimetheus-ring": ("Q18221522",),  # R/2006 S 1 — fr
    "naif-699/g-ring": ("Q1133273",),  # G ring — fr it
    "naif-699/e-ring": ("Q1109971",),  # E ring — fr it es
    "naif-699/phoebe-ring": ("Q19606402",),  # Phoebe ring — fr de
    # Uranus. The dust bands (Zeta C/CC, Alpha-4, Beta-Alpha, Eta C, Delta C,
    # Lambda C, dust sheet) are unnamed on Wikidata.
    "naif-799/zeta": ("Q3616611",),  # ζ ring — it
    "naif-799/six": ("Q2851401",),  # 6 ring — fr it
    "naif-799/five": ("Q2851398",),  # 5 ring — fr it
    "naif-799/four": ("Q2851399",),  # 4 ring — fr it
    "naif-799/alpha": ("Q3680062",),  # α ring — fr it
    "naif-799/beta": ("Q615967",),  # β ring — fr it
    "naif-799/eta": ("Q2851444",),  # η ring — fr it
    "naif-799/gamma": ("Q2851426",),  # γ ring — fr it
    "naif-799/delta": ("Q2851408",),  # δ ring — fr it
    "naif-799/lambda": ("Q2851428",),  # λ ring — fr it
    "naif-799/epsilon": ("Q511479",),  # ε ring — fr it
    "naif-799/nu": ("Q628325",),  # ν ring — fr it
    "naif-799/mu": ("Q1132027",),  # μ ring — fr it
    # Neptune. The Galatea co-orbital dust has no entity; each arc does.
    "naif-899/galle": ("Q3094782",),  # Galle ring — fr it
    "naif-899/le-verrier": ("Q3228065",),  # Le Verrier ring — fr it
    "naif-899/lassell": ("Q3218345",),  # Lassell ring — fr it
    "naif-899/arago": ("Q2859429",),  # Arago ring — fr de it
    "naif-899/adams": ("Q2824069",),  # Adams ring — fr de it
    "naif-899/fraternite": ("Q3616605",),  # Fraternité — it
    "naif-899/egalite-1": ("Q3616604",),  # Égalité 1 — it
    "naif-899/egalite-2": ("Q3616603",),  # Égalité 2 — it
    "naif-899/liberte": ("Q3616607",),  # Liberté — it
    "naif-899/courage": ("Q3616602",),  # Courage — it
}

# Rings that exist as articles but not as rows in the catalogue, kept so the
# panel can still name them.
RING_EXTRA_PAGES: dict[str, tuple[str, ...]] = {
    # Faint Saturnian rings announced in IAU circulars, carried by neither the
    # PDS table nor the IAU ring page.
    "saturn_r2004_s1": ("Q2247392",),  # R/2004 S1 — fr it es
    "saturn_r2004_s2": ("Q3414984",),  # R/2004 S2 — fr it
    # A Voyager-era name for a C ring feature, dropped by both the PDS table
    # and the IAU ring page but still carried by fr/it Wikipedia.
    "saturn_guerin_division": ("Q3032372",),  # Division de Guérin — fr it
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
