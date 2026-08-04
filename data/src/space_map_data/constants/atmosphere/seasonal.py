"""Mars seasonal climatology vs solar longitude L_s.

Sampled on a 30° L_s grid; the export interpolates nothing — the frontend
lerps with wrap-around and computes L_s from the simulation clock (Allison &
McEwen 2000). Storm years are excluded: dust is climatological background, so
the rendered Mars is a typical year, never a global-storm one.
"""

# 12-point L_s grid, degrees. Every array below samples at these points.
MARS_SEASON_LS_DEG: tuple[float, ...] = tuple(float(ls) for ls in range(0, 360, 30))

# Column visible dust optical depth, non-storm climatology: aphelion clear
# season ~0.15, dusty season (L_s 180-330) peaks ~0.4 with the solsticial
# pause near L_s 270 — Montabone et al. 2015 (Icarus 251, 65) 9.3 µm CDOD
# maps scaled to visible, staying inside the 0.15-0.4 clear-conditions range
# aerosols.py cites.
MARS_DUST_TAU_VIS: tuple[float, ...] = (
    0.17,
    0.15,
    0.15,
    0.15,
    0.16,
    0.20,
    0.25,
    0.40,
    0.42,
    0.32,
    0.42,
    0.28,
)

# The clear-season baseline aerosols.py's mars_dust column encodes — the
# exported seasonal factors are relative to it.
MARS_DUST_TAU_CLEAR = 0.15

# Surface pressure, mbar: smoothed VL1-shaped annual CO₂ condensation cycle
# (Tillman et al. 1993, JGR 98, 10963) — deep minimum near L_s 150 (southern
# cap growth), primary maximum near L_s 270, secondary extremes from the
# northern cap. Peak-to-trough ~25% of the mean, matching NSSDCA's seasonal
# range; exported as factors on the annual mean so the datum stays 636 Pa.
MARS_PRESSURE_MBAR: tuple[float, ...] = (
    7.75,
    8.1,
    8.3,
    8.0,
    7.2,
    6.75,
    7.1,
    7.9,
    8.55,
    8.8,
    8.4,
    7.9,
)
