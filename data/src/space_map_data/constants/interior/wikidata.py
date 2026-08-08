"""Wikidata topic pages behind the interior panel.

The thinnest section of the four. English Wikipedia has a dedicated
interior article for Earth and the Moon only; Italian carries a
"Struttura interna di X" series that covers seven more bodies and nothing
else does.

That series predates Juno, InSight and Margot 2021, so on the giants it
describes a layering our own cross-section declines to draw. It ships anyway:
it is the right kind of article, and no amount of curation here keeps a
Wikipedia lead current.

Values are tuples because one topic occasionally splits across two Wikidata
items with disjoint sitelinks — no single item covers every language. Nothing
resolves to English when a locale is missing: a reader either gets the article
in the language they are reading in, or no link at all, so the coverage
comment on each row is the whole story about where a link will appear.

Locale codes follow ``constants.providers.LANGUAGES``; "all 12" means every
one of them. Coverage was read off Wikidata and drifts as articles are
written or merged — treat the comments as of 2026-07-31.
"""

# Keyed by body id. Io, Europa, Callisto, Enceladus, Dione, Triton, Charon,
# Ceres and Vesta have no interior article anywhere, which leaves 10 of the 31
# bodies the Structure tab draws a cutaway for.
INTERIOR_PAGES: dict[str, tuple[str, ...]] = {
    "naif-10": ("Q619448",),  # solar core — en fr ja zh ar ru pt it es he
    "naif-199": ("Q3976185",),  # internal structure of Mercury — it
    "naif-299": ("Q3976190",),  # internal structure of Venus — it
    # internal structure of the Moon — en fr zh ar pt it es
    "naif-301": ("Q1358214",),
    # internal structure of Earth — en fr ja zh ar ru pt de it es he
    "naif-399": ("Q1664027",),
    "naif-499": ("Q3976184",),  # struttura interna di Marte — it
    "naif-503": ("Q3976183",),  # internal structure of Ganymede — it
    "naif-599": ("Q3976182",),  # internal structure of Jupiter — it
    "naif-699": ("Q3976188",),  # internal structure of Saturn — it
    "naif-799": ("Q3976189",),  # internal structure of Uranus — it
    "naif-899": ("Q3976186",),  # internal structure of Neptune — it
}

# Three articles are deliberately absent, each contentless in every language it
# has rather than merely dated, so a link would spend the reader's click on a
# sentence they already have. Re-check before re-adding, not after:
#   Q5156794 composition of Mars (en zh ar ru es) — "the composition of Mars
#     covers the branch of the geology of Mars that describes the make-up of
#     the planet Mars", and nothing more, in all five.
#   Q63523002 struttura interna di Titano (it) — says only that Cassini-Huygens
#     improved our understanding of it.
#   Q3976187 struttura interna di Plutone (it) — the same sentence, for
#     New Horizons.

# Keyed by the material vocabulary in ``constants.interior.schema``. These are
# the closest standing article to each bucket, not a definition of it —
# heavy_elements points at the ice-giant article because that is where the
# rock-or-ice ambiguity is actually discussed.
MATERIAL_PAGES: dict[str, tuple[str, ...]] = {
    "metal": ("Q903965",),  # iron-nickel alloy — en fr ja de he
    "sulfide": ("Q6073081",),  # iron sulfide — en fr ja ar ru de es pl
    "silicate": ("Q7130787",),  # silicate — en fr ja zh ar ru pt es he pl
    "water": ("Q125745585",),  # phases of ice — en
    "volatile": ("Q1306723",),  # volatiles — en fr zh ar pt es
    "organic": ("Q73017",),  # tholin — en fr ja zh ar ru pt de it es pl
    "hydrogen": ("Q428895",),  # metallic hydrogen — en fr ja zh ar ru pt de it es pl
    "helium": ("Q560",),  # helium — all 12
    "heavy_elements": ("Q1319599",),  # ice giant — en fr ja zh ar ru pt de it es he
}

# Keyed by ``ClassComposition.analogue`` in ``constants.interior.taxonomy``.
ANALOGUE_PAGES: dict[str, tuple[str, ...]] = {
    # ordinary chondrite — en fr ja zh ar ru pt de it es pl
    "ordinary_chondrite": ("Q1195475",),
    # carbonaceous chondrite — en fr ja zh ar pt de pl
    "carbonaceous_chondrite": ("Q1062169",),
    # mineral hydration — en fr zh ar pt it
    "hydrated_carbonaceous_chondrite": ("Q20396016",),
    # carbonaceous chondrite — en fr ja zh ar pt de pl
    "cv_co_chondrite": ("Q1062169",),
    "hed_achondrite": ("Q536491",),  # HED meteorite — en fr ja zh ar pt it es pl
    "iron_with_silicate": ("Q1067440",),  # pallasite — en fr ja zh ar ru de it es pl
    "aubrite": ("Q781004",),  # aubrite — en fr ja zh ar pt
    "olivine_achondrite": ("Q22693",),  # olivine — en fr ja zh ar ru pt it es he pl
}

INTERIOR_CONCEPT_PAGES: dict[str, tuple[str, ...]] = {
    "planetary_core": ("Q742129",),  # planetary core — en fr ja zh ar ru it es pl
    "planetary_mantle": ("Q4364434",),  # planetary mantle — en fr zh ar ru es
    # planetary differentiation — en fr zh ar ru pt de it es he
    "planetary_differentiation": ("Q910022",),
    "earth_crust": ("Q15316",),  # Earth's crust — all 12
    "earth_mantle": ("Q101949",),  # mantle — all 12
    "earth_core": ("Q193927",),  # Earth's core — en fr zh ru pt de it es pl
    "inner_core": ("Q394352",),  # inner core — en fr ja zh ar ru pt de it es he
    "outer_core": ("Q857867",),  # outer core — en fr ja zh ar ru pt de it es
    "magma_ocean": ("Q12034896",),  # magma ocean — en fr ar es
    "lunar_magma_ocean": ("Q3039909",),  # lunar magma ocean — en fr zh ar es
    "subsurface_ocean": ("Q19595959",),  # planetary oceanography — en ar ru de
    # Ocean world (Q1045138) was dropped rather than moved: cat-oceans took the
    # list article (Q139377044) instead, because this item's non-English
    # articles are about a hypothetical water-covered exoplanet rather than
    # about the subsurface oceans it is cited for here.
    "ocean_world_list": ("Q139377044",),  # list of ocean worlds — en
    "rubble_pile": ("Q462326",),  # rubble pile — en fr ja ar ru de it es
    "gas_giant": ("Q121750",),  # gas giant — all 12
    # moment of inertia factor — en fr ar he
    "moment_of_inertia_factor": ("Q17144845",),
    "hydrostatic_equilibrium": ("Q208641",),  # hydrostatic equilibrium — all 12
    # degenerate matter — en fr ja zh ar ru pt de it es pl
    "degenerate_matter": ("Q51368",),
    "equation_of_state": ("Q214967",),  # equation of state — all 12
    "dynamo_theory": ("Q1269129",),  # dynamo theory — en ja zh ar ru pt de es he
    "seismic_wave": ("Q186167",),  # seismic wave — all 12
    "nuclear_fusion": ("Q13082",),  # nuclear fusion — all 12
    "proton_proton_chain": ("Q223073",),  # proton-proton chain — all 12
    "radiative_zone": ("Q127922",),  # radiation zone — en fr ja zh ar ru pt it es pl
    # convection zone — en fr ja zh ar ru pt it es pl
    "convection_zone": ("Q128034",),
    "tachocline": ("Q31767",),  # tachocline — en fr ja zh ar ru pt de it es
    "iron": ("Q677",),  # iron — all 12
    "nickel": ("Q744",),  # nickel — all 12
    "sulfur": ("Q682",),  # sulfur — all 12
    "chondrite": ("Q48361",),  # chondrite — all 12
    "iron_meteorite": ("Q827989",),  # iron meteorite — en fr ja zh ar pt de it es pl
    "pyroxene": ("Q192880",),  # pyroxene — all 12
    "troilite": ("Q425316",),  # troilite — en fr ja zh ar pt de it es he pl
    "serpentinite": ("Q737339",),  # serpentinite — en fr ja zh ar ru pt de it es pl
    "silicate_perovskite": ("Q22998485",),  # silicate perovskite — en ja zh ar de
    "post_perovskite": ("Q3399734",),  # post-perovskite — en fr ja
    # asteroid spectral type — en fr ja zh ar ru pt it es pl
    "asteroid_spectral_type": ("Q1750705",),
    # C-type asteroid — en fr ja zh ar ru pt it es pl
    "c_type_asteroid": ("Q729623",),
    # S-type asteroid — en fr ja zh ar ru pt it es he pl
    "s_type_asteroid": ("Q543157",),
    # M-type asteroid — en fr ja zh ar ru pt it es pl
    "m_type_asteroid": ("Q847310",),
    "v_type_asteroid": ("Q1400344",),  # V-type asteroid — en fr ja zh ar ru pt it pl
}
