from enum import StrEnum


class PROVIDERS(StrEnum):
    HORIZONS = "horizons"
    CELESTRAK = "celestrak"
    SBDB = "sbdb"
    SBDB_MOONS = "sbdb_moons"
    SPICE = "spice"
    SPICE_PROBES = "spice_probes"
    SPICE_HORIZONS_SYNTH = "spice_horizons_synth"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"
    COMMONS = "commons"
    EARTH_CLOUDS = "earth_clouds"
    IAU_NOMENCLATURE = "iau_nomenclature"
    TEXTURE_SOURCES = "texture_sources"
    BJJ_RINGS = "bjj_rings"
    DEEPL = "deepl"


class ID_TYPES(StrEnum):
    NAIF = "naif"
    SPKID = "spkid"
    SBDB_MOON = "sbdb_moon"
    MPC_DESIGNATION = "mpc_designation"
    NORAD_SATCAT = "norad_satcat"
    COSPAR = "cospar"
    PROVISIONAL_DESIGNATION = "provisional_designation"
    IAU_FEATURE_ID = "iau_feature_id"
    NAME = "name"
    PROBE = "probe"  # synthetic ID for spacecraft (inception date + dedupe)


def make_object_id(id_type: ID_TYPES, value: int | str) -> str:
    """Build a canonical object ID, e.g. ``make_object_id(ID_TYPES.NAIF, 399)`` → ``'naif-399'``."""
    return f"{id_type}-{value}"


ID_TYPE_TO_WIKIDATA_PID = {
    ID_TYPES.NAIF: "P2956",
    ID_TYPES.SPKID: "P716",
    ID_TYPES.MPC_DESIGNATION: "P5736",
    ID_TYPES.NORAD_SATCAT: "P377",
    ID_TYPES.COSPAR: "P247",
    ID_TYPES.PROVISIONAL_DESIGNATION: "P490",
    ID_TYPES.IAU_FEATURE_ID: "P2824",
}
LANGUAGES = ("en", "fr", "ja", "zh", "ar", "ru")
