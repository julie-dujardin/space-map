"""Selector + wiring tests for the 2026-06 rocket-family batch. Exercises
the real matching logic against verbatim CelesTrak SATCAT names, not the
live CSV, so it stays deterministic."""

from space_map_data.constants.earth_sats.constellations import slug_from_name
from space_map_data.ingest.providers.objects.enrichment import (
    resolve_constellation,
    resolve_manufacturer_qids,
    resolve_operator_qids,
)


def _resolve(name, owner="CIS"):
    return resolve_constellation(1, name, owner, set())


class TestSheldonSplit:
    """Each SL-N designator resolves to its own launch-vehicle family; a bare
    SL- prefix used to lump them all under soyuz-rocket."""

    def test_each_designator(self):
        cases = {
            "SL-1 R/B": "sputnik-rocket",
            "SL-3 R/B": "vostok-rocket",
            "SL-4 R/B": "soyuz-rocket",
            "SL-5 R/B": "polyot",
            "SL-6 DEB": "molniya-rocket",
            "SL-7 R/B": "kosmos-2i",
            "SL-8 R/B": "kosmos-3m",
            "SL-9 R/B": "proton-rocket",
            "SL-11 R/B": "tsyklon-2",
            "SL-12 R/B": "proton-rocket",
            "SL-13 R/B": "proton-rocket",
            "SL-14 R/B": "tsyklon-3",
            "SL-16 R/B": "zenit",
            "SL-18 DEB": "start-1",
            "SL-19 R/B": "rokot",
            "SL-21 R/B": "shtil",
            "SL-23 R/B": "zenit",
            "SL-24 R/B": "dnepr",
            "SL-25 R/B": "proton-rocket",
            "SL-26 R/B": "soyuz-rocket",
        }
        for name, slug in cases.items():
            assert slug_from_name(name) == slug, name

    def test_sl1_not_shadowed_by_longer_designators(self):
        # Longest-first matching keeps "SL-1" distinct from SL-12/SL-16/SL-18.
        assert slug_from_name("SL-1 R/B") == "sputnik-rocket"
        assert slug_from_name("SL-12 DEB") == "proton-rocket"

    def test_named_russian_variants(self):
        assert slug_from_name("DNEPR 1 R/B") == "dnepr"
        assert slug_from_name("START 1 DEB") == "start-1"


class TestProtonDisambiguation:
    """Proton rocket bodies use the SL- designators; the bare PROTON token is
    the Soviet science-satellite series."""

    def test_rocket_vs_science_payload(self):
        assert slug_from_name("SL-12 R/B(AUX MOTOR)") == "proton-rocket"
        assert slug_from_name("PROTON 1") == "proton"  # SCIENCE payload
        assert slug_from_name("BREEZE-M R/B") == "proton-m"  # Briz upper stage


class TestThorStack:
    """Thor/Thorad booster stacks resolve to thor-rocket; the Agena and Burner
    stages get their own entries; THOR 5/6/7 are Telenor comsats."""

    def test_booster_combos(self):
        assert slug_from_name("THOR ABLESTAR R/B") == "thor-rocket"
        assert slug_from_name("THOR ABLE R/B") == "thor-rocket"
        assert slug_from_name("THOR ALTAIR DEB") == "thor-rocket"
        assert slug_from_name("THOR DELTA 1 R/B") == "thor-rocket"
        assert slug_from_name("THORAD DELTA 1 R/B") == "thor-rocket"

    def test_agena_stage_across_boosters(self):
        # Thor/Thorad-Agena and the standalone target vehicle resolve to the
        # stage; Atlas-/Titan-Agena stay with their booster (prefix wins).
        assert slug_from_name("THORAD AGENA D R/B") == "agena"
        assert slug_from_name("THOR AGENA B R/B") == "agena"
        assert slug_from_name("AGENA TARGET") == "agena"
        assert slug_from_name("TITAN 3B AGENA D R/B") == "titan-rocket"

    def test_burner_stage(self):
        assert slug_from_name("THOR BURNER 2 R/B") == "burner"

    def test_telenor_comsats_not_stolen(self):
        assert slug_from_name("THOR 5") == "thor"
        assert slug_from_name("THOR 7") == "thor"
        assert slug_from_name("THOR II") == "thor"


class TestUpperStages:
    """Cross-family upper stages; Centaur stays with its booster (every SATCAT
    Centaur is ATLAS/TITAN/VULCAN-prefixed)."""

    def test_pam_and_motors(self):
        assert slug_from_name("SBS 1 R/B [PAM-D]") == "pam-star"

    def test_iabs_and_volga(self):
        assert slug_from_name("IABS R/B") == "iabs"
        assert slug_from_name("VOLGA R/B") == "volga"

    def test_centaur_resolves_to_booster(self):
        assert slug_from_name("ATLAS CENTAUR R/B") == "atlas"
        assert slug_from_name("TITAN 4 CENTAUR R/B") == "titan-rocket"
        assert slug_from_name("VULCAN CENTAUR R/B") == "vulcan"
        # The CENTAURI cubesats must never be confused with the stage.
        assert slug_from_name("CENTAURI-1") != "centaur"


class TestNewLaunchVehicles:
    """Prefix selectors validated against the live catalogue, tolerant of the
    SATCAT hyphen/space inconsistency."""

    def test_china(self):
        assert slug_from_name("CERES-1 R/B") == "ceres-1"
        # Bare "CERES 1" is a French ELINT satellite, not the Chinese rocket.
        assert slug_from_name("CERES 1") != "ceres-1"
        assert slug_from_name("ZHUQUE-2 R/B") == "zhuque-2"
        assert slug_from_name("ZQ-2E R/B") == "zhuque-2"
        assert slug_from_name("SQX-1 R/B") == "hyperbola-1"
        assert slug_from_name("GRAVITY-1 R/B") == "gravity-1"

    def test_india(self):
        assert slug_from_name("SLV-3 R/B") == "slv-3"
        assert slug_from_name("ASLV-D4 R/B") == "aslv"
        assert slug_from_name("LVM3 R/B") == "lvm3"
        assert slug_from_name("VTM R/B") == "sslv"  # SSLV terminal stage

    def test_korea_and_dprk(self):
        assert slug_from_name("KSLV-1 R/B") == "naro"
        assert slug_from_name("KSLV-II R/B") == "nuri"
        assert slug_from_name("UNHA 3 R/B") == "unha"
        assert slug_from_name("CHOLLIMA-1 R/B") == "chollima-1"

    def test_iran(self):
        assert slug_from_name("QASED R/B") == "qased"
        assert slug_from_name("QAEM 100 R/B") == "qaem-100"

    def test_japan_n_series(self):
        assert slug_from_name("N-1 R/B") == "n-1-japan"
        assert slug_from_name("N-2 R/B(1)") == "n-2-japan"
        assert slug_from_name("H-3 R/B") == "h3"

    def test_black_arrow_rocket_vs_payload(self):
        assert slug_from_name("BLACK ARROW R/B") == "black-arrow"
        assert slug_from_name("PROSPERO (BLACK ARROW)") != "black-arrow"


class TestPrefixGuards:
    """Longer/anchored prefixes keep look-alikes apart."""

    def test_minotaur_c_beats_minotaur(self):
        assert slug_from_name("MINOTAUR-C R/B") == "taurus-minotaur-c"
        assert slug_from_name("MINOTAUR 4 R/B") == "minotaur"
        assert slug_from_name("TAURUS R/B") == "taurus-minotaur-c"
        # The Chinese TAURUS-1 satellite is not the US rocket.
        assert slug_from_name("TAURUS-1 (JINNIUZUO 1)") != "taurus-minotaur-c"

    def test_juno_ii_excludes_jupiter_probe(self):
        assert slug_from_name("JUNO II R/B") == "juno-ii"
        assert slug_from_name("JUNO") != "juno-ii"  # 2011 NASA Jupiter orbiter

    def test_athena_excludes_payloads(self):
        assert slug_from_name("ATHENA 1 R/B(OAM)") == "athena"
        assert slug_from_name("ATHENA-FIDUS") != "athena"
        assert slug_from_name("ATHENA EPIC") != "athena"


class TestVanguardSplit:
    """Exact list separates the Vanguard rocket bodies from the satellites."""

    def test_rocket_vs_satellite(self):
        assert slug_from_name("VANGUARD R/B") == "vanguard-rocket"
        assert slug_from_name("VANGUARD DEB") == "vanguard-rocket"
        assert slug_from_name("VANGUARD 1") == "vanguard"


class TestRocketWiring:
    """New families route to the expected operator / manufacturer."""

    def test_isro_indian_launchers(self):
        for slug in ("slv-3", "aslv", "lvm3", "sslv"):
            assert "Q229058" in resolve_operator_qids(None, slug)
            assert "Q229058" in resolve_manufacturer_qids(slug)

    def test_jaxa_japanese_launchers(self):
        for slug in ("h3", "n-1-japan", "n-2-japan"):
            assert "Q179103" in resolve_operator_qids(None, slug)
            assert "Q648280" in resolve_manufacturer_qids(slug)  # MHI

    def test_commercial_providers(self):
        assert "Q104635667" in resolve_operator_qids(None, "ceres-1")  # Galactic Energy
        assert "Q48772158" in resolve_operator_qids(None, "zhuque-2")  # LandSpace
        assert "Q28939648" in resolve_operator_qids(None, "launcherone")  # Virgin Orbit

    def test_korea_iran_dprk_agencies(self):
        assert "Q494948" in resolve_operator_qids(None, "nuri")  # KARI
        assert "Q4410582" in resolve_operator_qids(None, "qased")  # IRGC ASF
        assert "Q17124852" in resolve_operator_qids(None, "unha")  # NADA

    def test_proton_and_zenit_manufacturers(self):
        assert "Q1197016" in resolve_manufacturer_qids("proton-rocket")  # Khrunichev
        assert "Q851367" in resolve_manufacturer_qids("zenit")  # Yuzhmash
        assert "Q763402" in resolve_manufacturer_qids("vostok-rocket")  # RSC Energia
