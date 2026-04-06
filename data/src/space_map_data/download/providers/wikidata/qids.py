from space_map_data.models.object.sbdb import OrbitClass

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
