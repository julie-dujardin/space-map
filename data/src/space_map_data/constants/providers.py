from enum import StrEnum


class PROVIDERS(StrEnum):
    HORIZONS = "horizons"
    CELESTRAK = "celestrak"
    SBDB = "sbdb"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"


class ID_TYPES(StrEnum):
    NAIF = "naif"
    SPKID = "spkid"
    MPC_DESIGNATION = "mpc_designation"
    NORAD_SATCAT = "norad_satcat"
    COSPAR = "cospar"
    PROVISIONAL_DESIGNATION = "provisional_designation"


ID_TYPE_TO_WIKIDATA_PID = {
    ID_TYPES.NAIF: "P2956",
    ID_TYPES.SPKID: "P716",
    ID_TYPES.MPC_DESIGNATION: "P5736",
    ID_TYPES.NORAD_SATCAT: "P377",
    ID_TYPES.COSPAR: "P247",
    ID_TYPES.PROVISIONAL_DESIGNATION: "P490",
}
