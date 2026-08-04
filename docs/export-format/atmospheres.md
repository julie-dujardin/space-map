# Atmospheres

`v1/atmospheres.json` (not gzipped) — per-body atmospheric-scattering
parameters for the frontend's shell shader, plus the shared aerosol phase
LUTs. Always-loaded like `systems/global.json`: fetched once at boot
(`frontend/src/lib/fetch/atmospheres.ts`), awaited before the major bodies
land so shells can build synchronously with each body mesh. Bodies absent from
the file get no shell; a failed fetch degrades to airless rendering.

Every value is derived by `data/src/space_map_data/export/atmospheres/` from
the cited constants in `data/src/space_map_data/constants/atmosphere/` — gas
refractivity dispersion + King factors, reference-level conditions (P, T, g),
and aerosol microphysics. Derivations are checked against published values
(Bruneton's Earth Rayleigh betas, NSSDCA scale heights) in
`data/tests/export/test_atmospheres.py`.

```typescript
interface AtmospheresFile {
	// Samples per channel in each phase LUT (128).
	phase_n: number;
	// Aerosol phase LUTs keyed by aerosol name; bodies with the same aerosol
	// assumption share one entry. 3×phase_n floats (R, G, B blocks), sampled
	// at θ = π·(i/(phase_n−1))² — quadratic warp concentrating samples on the
	// forward peak — each channel normalised to integrate to 1 over the
	// sphere. Spherical aerosols come from Mie theory over a log-normal size
	// distribution; irregular particles (Mars dust, Titan aggregates) from
	// published double-Henyey-Greenstein fits.
	phases: Record<string, number[]>;
	// Samples in each layered `mie_profile` LUT (128).
	profile_n: number;
	// Solar-disc photometry: per-channel exponents of the Hestroffer &
	// Magnan limb-darkening power law I(μ) = μ^α at the render wavelengths.
	sun: { limb_darkening_alpha: [number, number, number] };
	// Keyed by object id (`naif-399`).
	bodies: Record<string, AtmosphereBody>;
}

interface AtmosphereBody {
	// Shell top above the reference radius, km: max(8·H_Rayleigh, 6·H_Mie),
	// where the optical contribution dies — raised where a mie_profile holds
	// higher structure (Titan: 600 km for the detached layer).
	top_altitude_km: number;
	// Rayleigh scattering coefficient at the reference level, per km, at the
	// render wavelengths (680, 550, 440 nm). Derived from composition,
	// per-gas refractivity dispersion and King factors, and the reference
	// number density P/kT. The reference level is what the rendered sphere
	// shows: the surface for terrestrial bodies, the cloud tops for Venus,
	// above 1 bar for the giants (their textures show the visible deck).
	rayleigh_scatter_per_km: [number, number, number];
	// Isothermal scale height kT/(mg) at the reference level, km.
	rayleigh_scale_height_km: number;
	// Aerosol scattering / pure-absorption coefficients at the reference
	// level, per km, per channel — aerosols are big enough to colour the
	// light (Mars dust, tholins), unlike the grey-Mie textbook shortcut.
	// Curated per-body from mission literature (see constants/atmosphere/
	// aerosols.py for citations); extinction = scatter + absorption.
	mie_scatter_per_km: [number, number, number];
	mie_absorption_per_km: [number, number, number];
	mie_scale_height_km: number;
	// Key into `phases`.
	phase: string;
	// Absorber band (ozone on Earth), modelled as a linear density tent
	// centred at absorption_center_km, falling to 0 at ±absorption_width_km.
	// Coefficients derived from the absorber's column density × cross
	// sections. Zeros (width 1 as divide-by-zero guard) when absent.
	absorption_per_km: [number, number, number];
	absorption_center_km: number;
	absorption_width_km: number;
	// Artistic knobs, curated in constants/atmosphere/bodies.py:
	// fraction of a vertical column already baked into the surface texture,
	baked_compensation: number;
	// gain on the isotropic multiple-scattering ambient term,
	multi_scatter_gain: number;
	// linear gain on in-scattered radiance (~22 ≈ physical 1-AU irradiance
	// in the shader's calibration; per-body deviations are taste),
	sun_intensity: number;
	// apply inverse-square solar irradiance even with realistic lighting off
	// (far-out wisps tuned at physical intensity — Pluto, Triton).
	realistic_sun_always?: boolean;
	// (n − 1) of the gas mixture at the reference level per channel — the
	// frontend's astronomical-refraction lift of the Sun near the horizon.
	refractivity: [number, number, number];
	// Albedo of what the shell sits above (Bond; Earth uses the clear-sky
	// surface value) — boosts the multiple-scatter ambient near the ground.
	// Absent for bodies without a curated value.
	ground_albedo?: number;
	// Layered Mie density LUT (Venus decks, Titan's detached haze):
	// profile_n densities at equal altitude steps over [0, top_altitude_km],
	// 0 at the top, normalised so the LUT's vertical column equals the
	// exponential's mie_scale_height_km column (the cited optical depths
	// anchor β·H, so disc opacity matches across tiers). Only on bodies with
	// published vertical structure; the shader's high/ultra tiers sample it,
	// other tiers keep the mie_scale_height_km exponential.
	mie_profile?: number[];
	// Mars only: seasonal climatology on a wrap-around solar-longitude grid
	// (piecewise-linear in L_s, computed client-side from the sim clock).
	// dust_tau_factor scales the dust column (1 = the clear-season baseline
	// the mie_* coefficients encode), dust_scale_height_km replaces
	// mie_scale_height_km (Conrath-ν confinement), pressure_factor scales
	// the Rayleigh column around the annual-mean datum.
	seasonal?: {
		ls_deg: number[];
		dust_tau_factor: number[];
		dust_scale_height_km: number[];
		pressure_factor: number[];
	};
}
```
