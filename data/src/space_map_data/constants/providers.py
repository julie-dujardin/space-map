from enum import StrEnum


class PROVIDERS(StrEnum):
    HORIZONS = "horizons"
    CELESTRAK = "celestrak"
    SBDB = "sbdb"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"
    IAU_NOMENCLATURE = "iau_nomenclature"


class ID_TYPES(StrEnum):
    NAIF = "naif"
    SPKID = "spkid"
    MPC_DESIGNATION = "mpc_designation"
    NORAD_SATCAT = "norad_satcat"
    COSPAR = "cospar"
    PROVISIONAL_DESIGNATION = "provisional_designation"
    IAU_FEATURE_ID = "iau_feature_id"


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
