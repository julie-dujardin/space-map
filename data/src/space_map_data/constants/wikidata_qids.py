"""Hand-curated mappings from internal codes to Wikidata QIDs.

Both maps target encyclopedic entries that exist in many language editions
so the frontend can pull localized labels/descriptions from the Wikidata
download cache instead of carrying English-only constants.
"""

from space_map_data.models.object.sbdb import OrbitClass

# IAU feature type code -> Wikidata QID, used to localize the nomenclature
# popover (label + description) in the frontend. Sourced via SPARQL
# `?item wdt:P361 wd:Q1463003` (planetary nomenclature). Four codes
# (CL, LF, LO, ST) have no matching Wikidata entry — those keep their
# English-only constants in the frontend.
FEATURE_TYPE_QIDS: dict[str, str | None] = {
    "AA": "Q55818",  # Crater → impact crater
    "AL": "Q1051581",  # Albedo feature
    "AR": "Q20743937",  # Arcus
    "CA": "Q498794",  # Catena → crater chain
    "CB": "Q358877",  # Cavus
    "CH": "Q2419662",  # Chaos → chaos terrain
    "CL": None,  # Collum (bilobed-asteroid neck) — no Wikidata entry
    "CM": "Q1068071",  # Chasma
    "CO": "Q2983016",  # Collis
    "CR": "Q1134503",  # Corona
    "DO": "Q667575",  # Dorsum
    "ER": "Q20743938",  # Eruptive center
    "FA": "Q128952",  # Facula
    "FE": "Q3746596",  # Flexus
    "FL": "Q1058792",  # Fluctus
    "FM": "Q3074486",  # Flumen
    "FO": "Q1439394",  # Fossa
    "FR": "Q526644",  # Farrum → pancake dome
    "FT": "Q20743940",  # Fretum
    "IN": "Q2402047",  # Insula
    "LA": "Q3214330",  # Labes
    "LB": "Q3214576",  # Labyrinthus
    "LC": "Q3215913",  # Lacus
    "LF": None,  # Astronaut-named feature — no Wikidata entry
    "LG": "Q3077423",  # Large ringed feature
    "LI": "Q3832650",  # Linea
    "LN": "Q512573",  # Lingula
    "LO": None,  # Lobus (bilobed-asteroid lobe) — no Wikidata entry
    "LU": "Q20743942",  # Lacuna
    "MA": "Q1413444",  # Macula
    "ME": "Q3290341",  # Mare (generic; Q180874 is Moon-only)
    "MN": "Q3306046",  # Mensa
    "MO": "Q429088",  # Mons
    "OC": "Q3880745",  # Oceanus
    "PA": "Q948516",  # Palus
    "PE": "Q5259261",  # Patera
    "PL": "Q3391469",  # Planitia
    "PM": "Q7708397",  # Planum
    "PR": "Q3922925",  # Promontorium
    "PU": "Q3906785",  # Plume
    "RE": "Q3423535",  # Regio
    "RI": "Q1432092",  # Rima → rille
    "RU": "Q2066176",  # Rupes
    "SA": "Q64744256",  # Saxum
    "SC": "Q3476035",  # Scopulus
    "SE": "Q20743944",  # Serpens
    "SF": "Q20743939",  # Satellite feature
    "SI": "Q3961951",  # Sinus
    "ST": None,  # Statio (spacecraft landing site) — no Wikidata entry
    "SU": "Q96406679",  # Sulcus
    "TA": "Q3518514",  # Terra
    "TE": "Q3519009",  # Tessera
    "TH": "Q956300",  # Tholus
    "UN": "Q20743921",  # Unda
    "VA": "Q2249285",  # Vallis
    "VI": "Q20743945",  # Virga
    "VS": "Q3555010",  # Vastitas
}


# Asteroid orbit class -> Wikidata QIDs
# All have wikipedia pages in many languages
ORBIT_CLASS_QIDS = {
    OrbitClass.IEO: "Q1347759",
    OrbitClass.ATE: "Q1048390",
    OrbitClass.APO: "Q207391",
    OrbitClass.AMO: "Q1048303",
    OrbitClass.MCA: "Q777140",
    OrbitClass.IMB: "Q2179",  # Q15102625: stub, wikipedia doesn't have the inner/outer main belt distinction
    OrbitClass.MBA: "Q2179",
    OrbitClass.OMB: "Q2179",  # Q15122026: stub
    OrbitClass.TJN: "Q8101032",
    OrbitClass.AST: "Q3863",  # Generic page for generid class, only a hundred or so asteroids in this range anyway
    OrbitClass.CEN: "Q10734",
    OrbitClass.TNO: "Q6592",
    OrbitClass.PAA: None,  # No object, no page. Q2247097: parabolic trajectory
    OrbitClass.HYA: "Q53151979",  # Q2755058: hyperbolic trajectory
    OrbitClass.ETc: "Q11741558",
    OrbitClass.JFc: "Q11741557",
    OrbitClass.JFC: "Q11741557",  # Same page for Levison & Duncan / classical
    OrbitClass.CTc: "Q11741556",
    OrbitClass.HTC: "Q11741560",
    OrbitClass.PAR: "Q25036733",  # No wikipedia page
    OrbitClass.HYP: "Q20717849",  # No wikipedia page
    OrbitClass.COM: "Q3559",  # Generic page for generid class, about 700 in this range
}
