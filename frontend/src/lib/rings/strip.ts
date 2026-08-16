/**
 * The rendered rings' own radial profiles, read back for the Rings tab chart.
 *
 * Reuses the scene's `v1/rings/{body}/{bundle}/strip.webp` textures (one row
 * per channel across the annulus) so the chart shows the rings as they look,
 * not as flat optical-depth bands. Only radii a bundle covers get a profile;
 * elsewhere the chart falls back to the catalogue (e.g. Saturn's Phoebe ring,
 * catalogued but never rendered).
 */

import { versionedUrl } from '$lib/fetch/data-base';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';

export interface RingStripProfile {
	inner: number;
	outer: number;
	/** Normal optical depth per sample, inner → outer. */
	tau: Float32Array;
	/** sRGB tint per sample (3 bytes each), normalised to the bundle's brightest sample. */
	rgb: Uint8ClampedArray;
}

interface StripMeta {
	strip: string;
	inner_radius_km: number;
	outer_radius_km: number;
	intensity_scale: number;
	strip_rows: Record<string, number>;
}

/** Decoded profiles per body id — a Saturn strip is 13,177 samples wide, and
 *  the panel opens/closes far more often than the body changes. */
const cache = new Map<string, Promise<RingStripProfile[]>>();

function luminance(r: number, g: number, b: number): number {
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function decode(bodyId: string, meta: StripMeta): Promise<RingStripProfile | null> {
	const rows = meta.strip_rows;
	if (rows.transparency === undefined || rows.color === undefined) {
		console.warn(
			`Ring strip ${bodyId}/${meta.strip} has no transparency or color row, no profile drawn:`,
			rows
		);
		return null;
	}
	const response = await fetch(versionedUrl(`/v1/rings/${bodyId}/${meta.strip}`, 'rings'));
	if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
	const bitmap = await createImageBitmap(await response.blob());
	const canvas = document.createElement('canvas');
	canvas.width = bitmap.width;
	canvas.height = bitmap.height;
	const ctx = canvas.getContext('2d', { willReadFrequently: true });
	if (!ctx) {
		console.warn(`Ring strip ${bodyId}/${meta.strip}: no 2D context, no profile drawn`);
		return null;
	}
	ctx.drawImage(bitmap, 0, 0);
	const n = bitmap.width;
	const pixels = ctx.getImageData(0, 0, n, bitmap.height).data;
	bitmap.close();

	const scale = meta.intensity_scale || 1;
	const tau = new Float32Array(n);
	const rgb = new Uint8ClampedArray(n * 3);
	const back = rows.backscattered ?? rows.color;
	const brightness = new Float32Array(n);
	let peak = 0;
	for (let i = 0; i < n; i++) {
		const t = (rows.transparency * n + i) * 4;
		const b = (back * n + i) * 4;
		// Stored transparency is exp(-tau) normalised to the bundle's range; undo
		// it to recover physical τ, the unit the chart and catalogue both use.
		const opacity = Math.min(1, (1 - pixels[t] / 255) * scale);
		tau[i] = opacity >= 1 ? Infinity : -Math.log(1 - opacity);
		brightness[i] = luminance(pixels[b], pixels[b + 1], pixels[b + 2]) / 255;
		if (brightness[i] > peak) peak = brightness[i];
	}
	// Brightness relative to the bundle's brightest sample, lifted off a floor —
	// Uranus' ε ring outshines its dust sheet by two orders of magnitude, and a
	// literal reproduction would draw the sheet as empty. Opacity still carries
	// how substantial the material is.
	const FLOOR = 0.35;
	for (let i = 0; i < n; i++) {
		const c = (rows.color * n + i) * 4;
		const lit = peak > 0 ? FLOOR + (1 - FLOOR) * (brightness[i] / peak) : 1;
		rgb[i * 3] = pixels[c] * lit;
		rgb[i * 3 + 1] = pixels[c + 1] * lit;
		rgb[i * 3 + 2] = pixels[c + 2] * lit;
	}

	return {
		inner: meta.inner_radius_km,
		outer: meta.outer_radius_km,
		tau,
		rgb
	};
}

async function load(bodyId: string): Promise<RingStripProfile[]> {
	// The body's own bundles, not its system file's — ringed small bodies
	// belong to no system, and the detail fetch is free here (already needed to render).
	const detail = await fetchObjectDetail(bodyId, false);
	const bundles = (detail.global?.rings ?? []) as StripMeta[];
	// No render bundles means a stale export, not a ringless body — the
	// catalogue is what put the panel on screen.
	if (!bundles.length) console.warn(`Ring strips for ${bodyId}: no ring bundles on the object`);
	const profiles: RingStripProfile[] = [];
	for (const bundle of bundles) {
		try {
			const profile = await decode(bodyId, bundle);
			if (profile) profiles.push(profile);
		} catch (err) {
			// Optical-depth bands cover this range anyway — missing detail, not correctness.
			console.warn(`Ring strip ${bodyId}/${bundle.strip} unavailable:`, err);
		}
	}
	return profiles;
}

/** Profile across a radius interval (one chart pixel can swallow hundreds of
 *  samples). Densest sample wins, not the mean — averaging would erase a
 *  narrow ring like Uranus' ε (a dozen τ≈1 samples among a hundred of dust).
 *  Null where no bundle covers the interval. */
export function sampleProfiles(
	profiles: readonly RingStripProfile[],
	lo: number,
	hi: number
): { rgb: [number, number, number]; tau: number } | null {
	let covered = false;
	let tau = -1;
	let red = 0;
	let green = 0;
	let blue = 0;
	for (const profile of profiles) {
		const n = profile.tau.length;
		const perKm = (n - 1) / (profile.outer - profile.inner);
		const first = Math.round((Math.max(lo, profile.inner) - profile.inner) * perKm);
		const last = Math.round((Math.min(hi, profile.outer) - profile.inner) * perKm);
		if (last < first || first >= n || last < 0) continue;
		covered = true;
		for (let i = Math.max(0, first); i <= Math.min(n - 1, last); i++) {
			// Clamp opaque (τ=∞) samples to a comparable value past the densest measured ring.
			const sample = Number.isFinite(profile.tau[i]) ? profile.tau[i] : 10;
			if (sample <= tau) continue;
			tau = sample;
			red = profile.rgb[i * 3];
			green = profile.rgb[i * 3 + 1];
			blue = profile.rgb[i * 3 + 2];
		}
	}
	return covered ? { rgb: [red, green, blue], tau } : null;
}

export function loadRingStrips(bodyId: string): Promise<RingStripProfile[]> {
	let pending = cache.get(bodyId);
	if (!pending) {
		pending = load(bodyId).catch((err) => {
			console.warn(`Ring strips for ${bodyId} unavailable:`, err);
			cache.delete(bodyId);
			return [];
		});
		cache.set(bodyId, pending);
	}
	return pending;
}
