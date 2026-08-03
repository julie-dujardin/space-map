"""Hand-curated Wikidata QIDs for small-body classifications.

Targets encyclopedic entries that exist in many language editions so the
frontend can pull localized labels/descriptions from the Wikidata download
cache instead of carrying English-only constants.
"""

from space_map_data.models.object.sbdb import OrbitClass

# Asteroid/comet orbit class -> Wikidata QID. All have Wikipedia pages in
# many languages.
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
    OrbitClass.AST: None,  # Catch-all "unclassified asteroid" bucket; the generic "asteroid" page misrepresents it
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
    OrbitClass.COM: None,  # Catch-all "unclassified comet" bucket; the generic "comet" page misrepresents it
}

# A new OrbitClass member must take a stance here — even an explicit None —
# or its group page silently ships without a QID.
assert set(ORBIT_CLASS_QIDS) == set(OrbitClass), (
    "ORBIT_CLASS_QIDS out of sync with OrbitClass"
)
