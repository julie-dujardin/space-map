from enum import StrEnum


class PROVIDERS(StrEnum):
    HORIZONS = "horizons"
    CELESTRAK = "celestrak"
    SBDB = "sbdb"
    WIKIDATA = "wikidata"
    WIKIPEDIA = "wikipedia"


class ID_TYPES(StrEnum):
    NAIF = "naif"  # wikidata: P2956
    SPKID = "spkid"  # wikidata: P716
    MPC_DESIGNATION = "mpc_designation"  # wikidata: P5736
    NORAD_SATCAT = "norad_satcat"  # wikidata: P377
    COSPAR = "cospar"  # wikidata: P247
