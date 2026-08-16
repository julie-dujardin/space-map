/**
 * Per-body atmospheric scattering parameters, fetched once from
 * `/data/v1/atmospheres.json`. Bodies absent from the file get no scattering
 * shell, so a failed fetch degrades to airless rendering rather than
 * breaking the scene.
 */

import type {
	AtmosphereParams,
	AtmosphereSeasonalTable
} from '$lib/scene/objects/surface/atmosphere';
import { DATA_BASE } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

interface SeasonalEntry {
	ls_deg: number[];
	dust_tau_factor: number[];
	dust_scale_height_km: number[];
	pressure_factor: number[];
}

interface AtmosphereBodyEntry {
	top_altitude_km: number;
	rayleigh_scatter_per_km: [number, number, number];
	rayleigh_scale_height_km: number;
	mie_scatter_per_km: [number, number, number];
	mie_absorption_per_km: [number, number, number];
	mie_scale_height_km: number;
	/** Key into the file's shared `phases` table — bodies with the same
	 *  aerosol assumption share one LUT. */
	phase: string;
	absorption_per_km: [number, number, number];
	absorption_center_km: number;
	absorption_width_km: number;
	baked_compensation: number;
	multi_scatter_gain: number;
	sun_intensity: number;
	refractivity?: [number, number, number];
	ground_albedo?: number;
	/** `profile_n` Mie densities over [0, top_altitude_km] (layered bodies). */
	mie_profile?: number[];
	seasonal?: SeasonalEntry;
	realistic_sun_always?: boolean;
}

interface AtmospheresFile {
	phase_n: number;
	phases: Record<string, number[]>;
	profile_n?: number;
	sun?: { limb_darkening_alpha: [number, number, number] };
	bodies: Record<string, AtmosphereBodyEntry>;
}

const params = new Map<string, AtmosphereParams>();
let sunLimbAlpha: [number, number, number] | null = null;
let loadPromise: Promise<void> | null = null;

function seasonalTable(entry: SeasonalEntry | undefined): AtmosphereSeasonalTable | undefined {
	if (!entry) return undefined;
	const n = entry.ls_deg.length;
	if (
		n < 2 ||
		entry.dust_tau_factor.length !== n ||
		entry.dust_scale_height_km.length !== n ||
		entry.pressure_factor.length !== n
	) {
		console.warn('atmospheres: malformed seasonal table — ignored');
		return undefined;
	}
	return {
		lsDeg: entry.ls_deg,
		dustTauFactor: entry.dust_tau_factor,
		dustScaleHeightKm: entry.dust_scale_height_km,
		pressureFactor: entry.pressure_factor
	};
}

export function loadAtmospheres(): Promise<void> {
	if (loadPromise) return loadPromise;
	const p = (async () => {
		const r = await fetchWithTimeout(`${DATA_BASE}/v1/atmospheres.json`);
		if (!r.ok) {
			console.warn(`atmospheres: fetch failed (${r.status}) — rendering without shells`);
			return;
		}
		const raw = (await r.json()) as AtmospheresFile;
		sunLimbAlpha = raw.sun?.limb_darkening_alpha ?? null;
		for (const [id, entry] of Object.entries(raw.bodies)) {
			const phase = raw.phases[entry.phase];
			if (!phase || phase.length !== 3 * raw.phase_n) {
				console.warn(`atmospheres: ${id} has bad phase table "${entry.phase}" — skipped`);
				continue;
			}
			let mieProfile = entry.mie_profile;
			if (mieProfile && mieProfile.length !== raw.profile_n) {
				console.warn(`atmospheres: ${id} has a bad mie profile — falling back to exponential`);
				mieProfile = undefined;
			}
			params.set(id, {
				topAltitudeKm: entry.top_altitude_km,
				rayleighScatterPerKm: entry.rayleigh_scatter_per_km,
				rayleighScaleHeightKm: entry.rayleigh_scale_height_km,
				mieScatterPerKm: entry.mie_scatter_per_km,
				mieAbsorptionPerKm: entry.mie_absorption_per_km,
				mieScaleHeightKm: entry.mie_scale_height_km,
				miePhase: phase,
				absorptionPerKm: entry.absorption_per_km,
				absorptionCenterKm: entry.absorption_center_km,
				absorptionWidthKm: entry.absorption_width_km,
				bakedCompensation: entry.baked_compensation,
				multiScatterGain: entry.multi_scatter_gain,
				sunIntensity: entry.sun_intensity,
				sunColor: [1, 1, 1],
				realisticSunAlways: entry.realistic_sun_always,
				refractivity: entry.refractivity,
				groundAlbedo: entry.ground_albedo,
				mieProfile,
				seasonal: seasonalTable(entry.seasonal)
			});
		}
	})();
	// Evict on rejection so a boot-time blip doesn't leave the sky airless all
	// session — the next load attempt refetches.
	p.catch(() => {
		if (loadPromise === p) loadPromise = null;
	});
	loadPromise = p;
	return p;
}

export function getAtmosphereParams(id: string): AtmosphereParams | undefined {
	return params.get(id);
}

/** Per-channel solar limb-darkening exponents (Hestroffer & Magnan power
 *  law), or null before the file lands / on an old file. */
export function getSunLimbAlpha(): [number, number, number] | null {
	return sunLimbAlpha;
}

/** Ids that have an atmosphere entry (debug tuner body list). */
export function atmosphereBodyIds(): string[] {
	return [...params.keys()];
}
