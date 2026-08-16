"""Curated atmospheric constants feeding `export/atmospheres/`.

Split by concern: `gases` (optical constants), `bodies` (composition +
reference conditions + render tuning), `aerosols` (haze microphysics + column
optics). Every measured value carries its citation; `tests/export/test_atmospheres.py`
checks derivations against published references (Rayleigh cross sections,
NSSDCA scale heights).

`facts` + `structure` are the panel's pair — conditions at one level, and the
named layers it sits on. Neither feeds rendering.

Banked for future shader work, no consumer yet: `layers` (vertical aerosol
structure), `spectra` (band absorption beyond the RGB triplets), `photometry`
(ground albedos + limb darkening). Refraction needs no extra data — bend rays
with (n-1) from `gases` scaled by density from `bodies`; checks: Earth's
horizon refraction is 34′ (USNO), Venus turns critically refractive below
~35 km (Fjeldbo et al. 1971).
"""
