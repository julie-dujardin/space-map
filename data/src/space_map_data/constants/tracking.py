"""Ground-station codes mapped to the objects they track.

Neither network publishes an identifier we hold: a DSN target is a short code
like ``VGR1``, an ESTRACK mission a four-letter one like ``JUIC``, and the only
other thing either offers is a display name. Name matching gets most of the way
and then lands on the wrong object — "M20" is also a Gonets satellite, "DART"
is both the 2005 rendezvous demonstrator and the asteroid impactor — so the
crosswalk is curated and nothing derives it at run time.

A code absent here is reported as unresolved rather than guessed; new codes
appear on the networks every few weeks.
"""

# Targets that are the network doing something other than talking to a
# spacecraft, kept out of the unresolved report because they will never resolve.
DSN_NON_SPACECRAFT = frozenset(
    {
        "GBRA",  # Ground-based radio astronomy.
        "HCRA",  # Host-country radio astronomy.
    }
)

# Two codes here come only from the bot's record and stay unresolved: AGM1 is
# Astrobotic's Griffin lander, and B101 is not in the feed's dictionary at all.
DSN_OBJECT_IDS: dict[str, str] = {
    "ACE": "probe-78942208",
    "BEPI": "probe-110526464",
    "BIOS": "probe-116686848",
    "CAPS": "probe-116109312",
    "CGO": "probe-120958978",
    "CHDR": "norad_satcat-25867",  # Chandra, catalogued under CXO.
    "DSCO": "probe-105070592",
    "EM2": "probe-121737217",  # Artemis II, under test rather than flying.
    "EMM": "probe-113205248",
    "ESCB": "probe-121163777",
    "ESCG": "probe-121163776",
    "EURC": "probe-119541760",
    "HYB2": "probe-112156672",
    "IM2": "probe-120098816",
    "IMAP": "probe-120958977",
    "JNO": "probe-107159552",
    "JWST": "probe-115347456",
    "KPLO": "probe-116260864",
    "LRO": "probe-96616448",
    "LTB": "probe-120102913",
    "LUCY": "probe-120614912",
    "M01O": "probe-84353024",
    "M20": "probe-113246208",  # The rover, not the cruise stage.
    "MEX": "probe-93536256",
    "MMS1": "norad_satcat-40482",
    "MMS2": "norad_satcat-40483",
    "MMS3": "norad_satcat-40484",
    "MMS4": "norad_satcat-40485",
    "MMX": "probe-121724928",
    "MRO": "probe-90857472",
    "MSL": "probe-100265984",
    "MVN": "probe-120983552",
    "NHPC": "probe-104804352",
    "ORX": "probe-107429888",  # OSIRIS-REx, still the DSN code under APEX.
    "PSYC": "probe-118050816",
    "RST": "probe-122601472",
    "SOHO": "probe-76357632",
    "SPP": "probe-110309376",
    "STA": "probe-92659712",
    "SWFO": "probe-120958976",
    "TD10": "norad_satcat-27566",
    "TDR5": "norad_satcat-21639",
    "TDR8": "norad_satcat-26388",
    "TESS": "probe-109834240",
    "TGO": "probe-109281280",
    "THB": "probe-93134849",
    "THC": "probe-93134848",
    "VGR1": "probe-49065984",
    "VGR2": "probe-49000448",
    "WIND": "probe-74735616",
    "XMM": "norad_satcat-25989",
}

# Left unresolved deliberately, so the report stays a list of things to do:
# CAE6 and PR3C name several spacecraft flying together (Chang'e 6's orbiter,
# lander and returner; Proba-3's coronagraph and occulter), MTP/SEN/SWARM name
# whole constellations, GIO reads "Galileo" for what ESA tracks as navigation
# satellites rather than the Jupiter orbiter, and EXMC/FLEX/FOX1/GNYA/KX06/PLTO
# /SCI1 are codes we hold no object for.
ESTRACK_OBJECT_IDS: dict[str, str] = {
    "ADIT": "probe-117874688",
    "BEPI": "probe-110526464",  # The stack's surviving half, the MPO.
    "CRY": "norad_satcat-36508",
    "DART": "probe-115220480",
    "ECAR": "norad_satcat-59908",
    "EUCL": "probe-117612544",
    "EURC": "probe-119541760",
    "EXM": "probe-109281280",  # ExoMars 2016 is the Trace Gas Orbiter.
    "GAIA": "probe-103354368",
    "HERA": "probe-119513088",
    "IMAP": "probe-120958977",
    "INT": "norad_satcat-27540",
    "JUIC": "probe-117293056",
    "MEX": "probe-93536256",
    "NST": "probe-109899776",  # Listed as "Mars Insight Mission".
    "RST": "probe-122601472",
    "SMIL": "probe-122064896",
    "SOLO": "probe-112545792",
    "XMM": "norad_satcat-25989",
}
