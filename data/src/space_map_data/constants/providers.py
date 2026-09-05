from enum import StrEnum


class PROVIDERS(StrEnum):
    CELESTRAK = "celestrak"
    GCAT = "gcat"
    GCAT_DEEP = "gcat_deep"
    SBDB = "sbdb"
    SBDB_MOONS = "sbdb_moons"
    SSODNET = "ssodnet"
    JPL_SATELLITE_DISCOVERY = "jpl_satellite_discovery"
    SPACETRACK = "spacetrack"
    SPICE = "spice"
    SPICE_PROBES = "spice_probes"
    SPICE_PROBES_PROPAGATION = "spice_probes_propagation"
    SPICE_DEEPCAT = "spice_deepcat"
    SPICE_HORIZONS_SYNTH = "spice_horizons_synth"
    SPICE_SPACETRACK_TLE = "spice_spacetrack_tle"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"
    COMMONS = "commons"
    EARTH_CLOUDS = "earth_clouds"
    IAU_NOMENCLATURE = "iau_nomenclature"
    GVP = "gvp"
    TEXTURE_SOURCES = "texture_sources"
    BJJ_RINGS = "bjj_rings"
    LAUNCH_PERFORMANCE = "launch_performance"
    PSG_ATMOSPHERE = "psg_atmosphere"
    NASA_3D = "nasa_3d"
    ESA_3D = "esa_3d"
    BODY_SHAPES = "body_shapes"
    DAMIT = "damit"
    MANUAL = "manual"


class ID_TYPES(StrEnum):
    NAIF = "naif"
    SPKID = "spkid"
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
LANGUAGES = ("en", "fr", "ja", "zh", "ar", "ru", "pt", "de", "it", "es", "he", "pl")

# The locale the export writes first and the others fall back to; also the
# locale that takes the IAU spelling of a feature name over Wikidata's.
BASE_LOCALE = "en"
