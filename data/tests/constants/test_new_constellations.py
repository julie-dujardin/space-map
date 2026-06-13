"""Selector + disambiguation tests for the 2026-06 constellation batch.

These exercise the real matching logic (``slug_from_name`` / ``resolve_constellation``)
rather than the live satcat.csv, so they stay deterministic. Names are taken
verbatim from CelesTrak SATCAT.
"""

from space_map_data.constants.earth_sats.constellations import slug_from_name
from space_map_data.ingest.providers.objects.enrichment import (
    resolve_constellation,
    resolve_manufacturer_qids,
    resolve_operator_qids,
)


def _resolve(name, owner="US"):
    return resolve_constellation(1, name, owner, set())


class TestPrefixMatches:
    """Clean prefix-based constellations match their fleet."""

    def test_simple_prefixes(self):
        assert slug_from_name("GORIZONT 12") == "gorizont"
        assert slug_from_name("RADUGA-1M 3") == "raduga"
        assert slug_from_name("EKRAN 5") == "ekran"
        assert slug_from_name("EXPRESS-AM22 (SESAT 2)") == "ekspress"
        assert slug_from_name("SKYNET 4C") == "skynet"
        assert slug_from_name("KINEIS-3C") == "kineis"
        assert slug_from_name("ASTROCAST-0203") == "astrocast"
        assert slug_from_name("CARTOSAT-2F") == "cartosat"
        assert slug_from_name("RISAT-2BR1") == "risat"
        assert slug_from_name("QPS-SAR-9 (SUSANOO-I)") == "qps-sar"
        assert slug_from_name("SAR-LUPE 3") == "sar-lupe"
        assert slug_from_name("SARAH-1") == "sarah"
        assert slug_from_name("TIANZHOU-7") == "tianzhou"
        assert slug_from_name("TIANWEN-1") == "tianwen"
        assert slug_from_name("ZOND 5") == "zond"

    def test_multi_token_prefix_families(self):
        # IRNSS + 2nd-gen NVS both feed NavIC.
        assert slug_from_name("IRNSS-1G") == "irnss-navic"
        assert slug_from_name("NVS-02 (IRNSS-1K)") == "irnss-navic"
        # Optical OFEQ + SAR TECSAR.
        assert slug_from_name("OFEQ 9") == "ofeq"
        assert slug_from_name("TECSAR") == "ofeq"
        # First-gen COSMO-SKYMED + second-gen CSG.
        assert slug_from_name("COSMO-SKYMED 2") == "cosmo-skymed"
        assert slug_from_name("CSG-2") == "cosmo-skymed"

    def test_shenzhou_capsule_and_modules(self):
        assert slug_from_name("SHENZHOU-7 (SZ-7)") == "shenzhou"
        assert slug_from_name("SZ-2 MODULE") == "shenzhou"

    def test_change_keeps_apostrophe(self):
        assert slug_from_name("CHANG'E-6") == "change"

    def test_himawari_not_bare_gms(self):
        assert slug_from_name("HIMAWARI-8 (GMS-8)") == "himawari"
        # The unrelated German "GMS-T" must not be caught.
        assert slug_from_name("GMS-T") != "himawari"


class TestDisambiguationGuards:
    """Trailing-space / trailing-hyphen anchors keep look-alikes out."""

    def test_kepler_hyphen_excludes_telescope(self):
        assert slug_from_name("KEPLER-1 (CASE)") == "kepler-communications"
        assert slug_from_name("KEPLER") != "kepler-communications"  # NASA telescope

    def test_global_hyphen_excludes_globalstar(self):
        assert slug_from_name("GLOBAL-2") == "blacksky"
        assert slug_from_name("GLOBALSTAR M001") == "globalstar"

    def test_gemini_trailing_space_excludes_pollux(self):
        assert slug_from_name("GEMINI 7") == "gemini"
        assert slug_from_name("GEMINI-POLLUX") != "gemini"

    def test_mercury_atlas_excludes_mercury_one(self):
        assert slug_from_name("MERCURY ATLAS 6") == "mercury-crewed"
        assert slug_from_name("MERCURY ONE (M1)") != "mercury-crewed"

    def test_luna_trailing_space_excludes_lookalikes(self):
        assert slug_from_name("LUNA 9") == "luna"
        assert slug_from_name("LUNA 25") == "luna"
        assert slug_from_name("LUNAH-MAP") != "luna"

    def test_nusat_hyphen_excludes_unrelated_us_sats(self):
        assert slug_from_name("NUSAT-1 (FRESCO)") == "nusat-satellogic"
        # 1985 US "NUSAT 1" (space) and unrelated "NEWSAT-1" must not match.
        assert slug_from_name("NUSAT 1") != "nusat-satellogic"
        assert slug_from_name("NEWSAT-1 (PALAPA B2R)") != "nusat-satellogic"

    def test_strix_hyphen_scopes_to_sar_fleet(self):
        assert slug_from_name("STRIX-1") == "strix-synspective"
        assert slug_from_name("STRIX-BETA") == "strix-synspective"

    def test_umbra_sar_fleet(self):
        assert slug_from_name("UMBRA-04") == "umbra-sar"


class TestExactListsOverrideClassified:
    """Classified-named US military comms need exact lists to beat the
    usa-classified / us-ops-classified buckets (which would resolve first)."""

    def test_milstar_beats_usa_classified(self):
        assert _resolve("USA 99 (MILSTAR-1 1)") == "milstar"

    def test_idscs_and_dscs_split(self):
        # IDSCS (phase I) and DSCS-II/III are separate programs.
        assert _resolve("OPS 9311 (IDSCS 1)") == "idscs"
        assert _resolve("OPS 9431 (DSCS 2-1)") == "dscs"
        assert _resolve("DSCS 3-1") == "dscs"

    def test_fltsatcom_beats_ops_classified(self):
        assert _resolve("OPS 6391 (FLTSATCOM 1)") == "fltsatcom"
        assert _resolve("FLTSATCOM 8 (USA 46)") == "fltsatcom"


class TestNossIntruder:
    """NOSS clusters/pairs are catalogued under classified USA/OPS names plus
    obscure first-gen subsat tags; exact list overrides the classified buckets
    and excludes rideshare cubesats sharing a launch."""

    def test_classified_named_members(self):
        assert _resolve("USA 160") == "noss-intruder"  # 3rd-gen Intruder pair
        assert _resolve("USA 498") == "noss-intruder"  # 4th-gen
        assert _resolve("OPS 6431") == "noss-intruder"  # 1st-gen dispenser

    def test_first_gen_subsat_tags(self):
        assert _resolve("SSU 1") == "noss-intruder"
        assert _resolve("EP 2") == "noss-intruder"

    def test_rideshare_cubesats_excluded(self):
        # CubeSats that shared the NROL-36 / NROL-55 launches must not be tagged.
        assert _resolve("CSSWE") != "noss-intruder"
        assert _resolve("BISONSAT") != "noss-intruder"


class TestOscarParentheticalTags:
    """AMSAT designators ride as parenthetical "(xO-NN)" tags; the open-paren
    anchor must not catch RS-/IRS-/GRS- substrings."""

    def test_parenthetical_designators_match(self):
        assert slug_from_name("OSCAR 1") == "oscar"
        assert slug_from_name("FOX-1A (AO-85)") == "oscar"
        assert slug_from_name("UOSAT 2 (UO-11)") == "oscar"
        assert slug_from_name("SAUDISAT 1C (SO-50)") == "oscar"

    def test_does_not_catch_irs_or_grs(self):
        assert slug_from_name("IRS-1A") == "resourcesat-irs"  # not oscar
        assert slug_from_name("AEROS (GRS-B)") != "oscar"


class TestOperatorManufacturerWiring:
    """New constellations route to the expected operator / manufacturer."""

    def test_shenzhou_cnsa_and_cast(self):
        assert "Q320644" in resolve_operator_qids(None, "shenzhou")  # CNSA
        assert "Q5099557" in resolve_manufacturer_qids("shenzhou")  # CAST

    def test_cosmo_skymed_asi_and_thales(self):
        assert "Q392953" in resolve_operator_qids(None, "cosmo-skymed")  # ASI
        assert "Q128356" in resolve_manufacturer_qids("cosmo-skymed")  # Thales Alenia

    def test_milstar_us_space_force(self):
        assert "Q55088961" in resolve_operator_qids(None, "milstar")

    def test_isro_navic_and_eo(self):
        for slug in ("irnss-navic", "cartosat", "risat", "resourcesat-irs"):
            assert "Q229058" in resolve_operator_qids(None, slug)
