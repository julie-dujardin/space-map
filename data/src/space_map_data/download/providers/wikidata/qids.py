from space_map_data.models.object.sbdb import OrbitClass

# Asteroid orbit class -> Wikidata QIDs
# All have wikipedia pages in many languages
ORBIT_CLASS_QIDS = {
    OrbitClass.Atira: "Q1347759",
    OrbitClass.Aten: "Q1048390",
    OrbitClass.Apollo: "Q207391",
    OrbitClass.Amor: "Q1048303",
    OrbitClass.MarsCrossing: "Q777140",
    OrbitClass.InnerMainBelt: "Q2179",  # Q15102625: stub, wikipedia doesn't have the inner/outer main belt distinction
    OrbitClass.MainBelt: "Q2179",
    OrbitClass.OuterMainBelt: "Q2179",  # Q15122026: stub
    OrbitClass.JupiterTrojan: "Q8101032",
    OrbitClass.Asteroid: "Q3863",  # Generic page for generid class, only a hundred or so asteroids in this range anyway
    OrbitClass.Centaur: "Q10734",
    OrbitClass.TransNeptunian: "Q6592",
    OrbitClass.ParabolicAsteroid: None,  # No object, no page. Q2247097: parabolic trajectory
    OrbitClass.HyperbolicAsteroid: "Q53151979",  # Q2755058: hyperbolic trajectory
    OrbitClass.EnckeType: "Q11741558",
    OrbitClass.JupiterFamilyLD: "Q11741557",
    OrbitClass.JupiterFamilyC: "Q11741557",  # Same page for Levison & Duncan / classical
    OrbitClass.ChironType: "Q11741556",
    OrbitClass.HalleyType: "Q11741560",
    OrbitClass.ParabolicComet: "Q25036733",  # No wikipedia page
    OrbitClass.HyperbolicComet: "Q20717849",  # No wikipedia page
    OrbitClass.Comet: "Q3559",  # Generic page for generid class, about 700 in this range
}
