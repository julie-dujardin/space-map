"""Curated small-body rendezvous/flyby targets for the `small-bodies` zone.

Heliocentric zone membership is per-target: a probe within
`SMALL_BODY_ZONE_RADIUS_KM` of any target belongs to the zone, and its fit
center is the nearest target (see `fit_centers.small_body_candidates` and
`fit.py`). The list is curated rather than derived because each entry needs
a SPICE ephemeris furnished at fit time — mission kernels or
`spk/small-bodies/` generics — and a GM in the PCK pool.
"""

# Membership + fit-center-attachment radius. Sized for the fastest flybys:
# classification samples at 1-day cadence, and Giotto/Vega cross Halley at
# ~68 km/s, so anything under ~3e6 km can fall between samples and drop the
# encounter. Approach legs of slow rendezvous get correspondingly longer
# coverage, which is what the zone is for anyway.
SMALL_BODY_ZONE_RADIUS_KM = 4.0e6

# NAIF IDs of every small body a probe on disk has met or will meet within
# its kernel coverage. Bodies without SPK coverage at encounter epochs are
# harmless here — distance samples fail and no interval is emitted.
SMALL_BODY_TARGET_NAIF_IDS: tuple[int, ...] = (
    2000001,  # Ceres — Dawn
    2000004,  # Vesta — Dawn
    2000016,  # Psyche — Psyche (arrival 2029)
    2000021,  # Lutetia — Rosetta flyby 2010
    2000253,  # Mathilde — NEAR flyby 1997
    2000433,  # Eros — NEAR rendezvous 2000-2001
    2101955,  # Bennu — OSIRIS-REx 2018-2021
    2099942,  # Apophis — OSIRIS-APEX (2029)
    2162173,  # Ryugu — Hayabusa2 2018-2019
    2025143,  # Itokawa — Hayabusa 2005
    2486958,  # Arrokoth — New Horizons flyby 2019
    20065803,  # Didymos — DART 2022, Hera 2026
    1000012,  # 67P/Churyumov-Gerasimenko — Rosetta 2014-2016
    1000036,  # 1P/Halley — Giotto + Vega 1/2 1986
    1000093,  # 9P/Tempel 1 — Deep Impact 2005
    20152830,  # Dinkinesh — Lucy flyby 2023
    20052246,  # Donaldjohanson — Lucy flyby 2025
    20003548,  # Eurybates — Lucy 2027
    20015094,  # Polymele — Lucy 2027
    20011351,  # Leucus — Lucy 2028
    20021900,  # Orus — Lucy 2028
    20000617,  # Patroclus — Lucy 2033
)
