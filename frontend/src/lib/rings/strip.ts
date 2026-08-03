/**
 * The rendered rings' own radial profiles, read back for the Rings tab chart.
 *
 * The scene loads `v1/rings/{body}/{bundle}/strip.webp` — one row per channel
 * across the annulus — to texture the ring mesh. The chart draws the same
 * strips, so the panel shows the rings as they look rather than as flat
 * optical-depth bands. Only radii a bundle covers get a profile; the chart
 * falls back to the catalogue's optical depths elsewhere (Saturn's Phoebe ring
 * is catalogued and never drawn).
 */

import { DATA_BASE, versionedUrl } from '$lib/fetch/data-base';

export interface RingStripProfile {
	inner: number;
	outer: number;
	/** Normal optical depth per sample, inner → outer. */
	tau: Float32Array;
	/** sRGB tint per sample (3 bytes each), normalised so the bundle's
	 *  brightest sample reads at full brightness. */
	rgb: Uint8ClampedArray;
}

interface StripMeta {
	strip: string;
	inner_radius_km: number;
	outer_radius_km: number;
	intensity_scale: number;
	strip_rows: Record<string, number>;
}

/** Decoded profiles per body id — a Saturn strip is 13,177 samples wide and
 *  the panel is opened and closed far more often than the body changes. */
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
		// Stored transparency is exp(-tau) normalised to the bundle's own range;
		// undo the normalisation to recover the physical optical depth, which is
		// what the chart's ramp and the catalogue's numbers both speak in.
		const opacity = Math.min(1, (1 - pixels[t] / 255) * scale);
		tau[i] = opacity >= 1 ? Infinity : -Math.log(1 - opacity);
		brightness[i] = luminance(pixels[b], pixels[b + 1], pixels[b + 2]) / 255;
		if (brightness[i] > peak) peak = brightness[i];
	}
	// Brightness relative to the bundle's own brightest sample, lifted off the
	// floor: Uranus' ε ring outshines the dust sheet beside it by two orders of
	// magnitude, and a chart that reproduced that would draw the sheet as empty
	// space. The opacity the chart pairs this with still carries how
	// substantial the material is.
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

async function load(bodyId: string, systemId: string): Promise<RingStripProfile[]> {
	const response = await fetch(`${DATA_BASE}/v1/systems/${systemId}.json`);
	if (!response.ok) {
		console.warn(
			`Ring strips for ${bodyId}: systems/${systemId}.json returned ${response.status}, falling back to catalogue bands`
		);
		return [];
	}
	const meta: Record<string, { rings?: StripMeta[] }> = await response.json();
	const bundles = meta[bodyId]?.rings ?? [];
	// A ringed body with no render bundles is the export being stale, not a
	// body without rings — the catalogue is what put the panel on screen.
	if (!bundles.length)
		console.warn(`Ring strips for ${bodyId}: systems/${systemId}.json lists no ring bundles`);
	const profiles: RingStripProfile[] = [];
	for (const bundle of bundles) {
		try {
			const profile = await decode(bodyId, bundle);
			if (profile) profiles.push(profile);
		} catch (err) {
			// The chart's optical-depth bands cover this radius range anyway, so
			// a missing strip costs detail, not correctness.
			console.warn(`Ring strip ${bodyId}/${bundle.strip} unavailable:`, err);
		}
	}
	return profiles;
}

export function loadRingStrips(bodyId: string, systemId: string): Promise<RingStripProfile[]> {
	const key = `${systemId}/${bodyId}`;
	let pending = cache.get(key);
	if (!pending) {
		pending = load(bodyId, systemId).catch((err) => {
			console.warn(`Ring strips for ${bodyId} unavailable:`, err);
			cache.delete(key);
			return [];
		});
		cache.set(key, pending);
	}
	return pending;
}
