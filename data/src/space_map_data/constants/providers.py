from enum import StrEnum


class PROVIDERS(StrEnum):
    CELESTRAK = "celestrak"
    GCAT = "gcat"
    GCAT_DEEP = "gcat_deep"
    SBDB = "sbdb"
    SBDB_MOONS = "sbdb_moons"
    ASTERSAT = "astersat"
    JOHNSTON = "johnston"
    SSODNET = "ssodnet"
    JPL_SATELLITE_DISCOVERY = "jpl_satellite_discovery"
    EXOPLANET_ARCHIVE = "exoplanet_archive"
    EXOPLANET_EU = "exoplanet_eu"
    OPEN_EXOPLANET_CATALOGUE = "open_exoplanet_catalogue"
    EXOPLANET_SIMBAD = "exoplanet_simbad"
    EXOPLANET_GAIA = "exoplanet_gaia"
    SPACETRACK = "spacetrack"
    SPICE = "spice"
    SPICE_PROBES = "spice_probes"
    SPICE_PROBES_PROPAGATION = "spice_probes_propagation"
    SPICE_SMALL_BODY_CHEBYSHEV = "spice_small_body_chebyshev"
    SPICE_DEEPCAT = "spice_deepcat"
    SPICE_HORIZONS_SYNTH = "spice_horizons_synth"
    SPICE_SPACETRACK_TLE = "spice_spacetrack_tle"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"
    COMMONS = "commons"
    EARTH_CLOUDS = "earth_clouds"
    EARTH_WATER = "earth_water"
    IAU_NOMENCLATURE = "iau_nomenclature"
    GVP = "gvp"
    TEXTURE_SOURCES = "texture_sources"
    TEXTURE_FILES = "texture_files"
    BJJ_RINGS = "bjj_rings"
    LAUNCH_PERFORMANCE = "launch_performance"
    PSG_ATMOSPHERE = "psg_atmosphere"
    NASA_3D = "nasa_3d"
    ESA_3D = "esa_3d"
    BODY_SHAPES = "body_shapes"
    DAMIT = "damit"
    GAIA_SOURCE = "gaia_source"
    GAIA_ASTROPHYSICAL_PARAMETERS = "gaia_astrophysical_parameters"
    GAIA_CROSS_MATCH = "gaia_cross_match"
    CDS_STAR_CATALOGUES = "cds_star_catalogues"
    IAU_STAR_NAMES = "iau_star_names"
    GALAXY_CATALOGUES = "galaxy_catalogues"
    STAR_CLUSTER_CATALOGUES = "star_cluster_catalogues"
    NEBULA_CATALOGUES = "nebula_catalogues"
    STELLAR_REMNANT_CATALOGUES = "stellar_remnant_catalogues"
    BLACK_HOLE_CATALOGUES = "black_hole_catalogues"
    TRANSIENT_CATALOGUES = "transient_catalogues"
    SIMBAD_OBJECTS = "simbad_objects"
    WIKIDATA_SIMBAD_IDS = "wikidata_simbad_ids"
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
