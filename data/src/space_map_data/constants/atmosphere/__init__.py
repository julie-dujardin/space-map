"""Curated atmospheric constants feeding `export/atmospheres/`.

Split by concern: `gases` (optical constants per gas), `bodies` (per-body
composition + reference-level conditions + render tuning), `aerosols`
(per-body haze microphysics + column optics). Every measured value carries its
citation next to it; derived rendering parameters live in the export code, and
`tests/export/test_atmospheres.py` checks the derivations against published
reference numbers (measured Rayleigh cross sections, NSSDCA scale heights).

`facts` and `structure` are the panel's pair — one states the conditions at a
single level, the other the named layers that level sits on. Neither feeds
rendering.

Banked for the future high/ultra shader work (no consumer yet): `layers`
(piecewise vertical aerosol structure), `spectra` (band absorption cross
sections beyond the RGB triplets), `photometry` (ground albedos for sky
coupling + solar limb darkening). Refraction needs no extra data — bend rays
with (n-1) from `gases` dispersion scaled by the local density from `bodies`
conditions; checks: Earth's standard horizon refraction is 34′ (USNO), and
Venus turns critically refractive below ~35 km (Mariner V profiles, Fjeldbo
et al. 1971).
"""
