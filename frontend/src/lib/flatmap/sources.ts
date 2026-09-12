/**
 * Finding the pictures a body has. Everything drawable about a surface —
 * the map itself, the cloud snapshots over it, the lights on its night side —
 * is exported as a separate equirectangular bundle; this reads which ones
 * exist and turns them into URLs and credits.
 */

import { dataBase, versionedUrl } from '$lib/fetch/data-base';
import { cloudFrameForJd } from '$lib/scene/objects/surface/clouds';
import { textureFrameForJd } from '$lib/scene/objects/body/textures';

/** What every texture bundle in the export says about itself. */
export interface BundleMeta {
	id: string;
	tiers: string[];
	/** Snapshot ids for a bundle that changes with time; absent for a still one.
	 *  Each is the start of the span it covers. */
	frames?: string[];
	/** Runs of real coverage, `[firstSlot, lastSlot]`; between them there is no data. */
	coverage?: [string, string][];
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

/** The bundles behind one body's flat map, in the order they are drawn. */
export interface BodySources {
	surface?: BundleMeta & { monthlyFrames?: number };
	clouds?: BundleMeta;
	night?: BundleMeta;
	/** Mean radius in kilometres, where the export states the body's figure.
	 *  Lets a distance along the surface be turned into an angle. */
	radiusKm?: number;
}

/**
 * Barycenter whose system file describes a body, or null when it has none.
 *
 * A planet or moon's NAIF code is its barycenter's followed by two more
 * digits, so the file is named by the first. Everything else — the Sun, and
 * the small bodies orbiting on their own — is read from its own bundle.
 */
export function systemIdFor(bodyId: string): string | null {
	const match = /^naif-(\d)\d\d$/.exec(bodyId);
	return match ? `naif-${match[1]}` : null;
}

interface SystemEntry {
	tiers?: string[];
	/** Triaxial radii in kilometres, along the body-fixed axes. */
	radii?: { a: number; b: number; c: number };
	texture?: Omit<BundleMeta, 'id' | 'tiers'> & { frames?: number };
	clouds?: BundleMeta;
	night?: BundleMeta;
}

async function fetchJson<T>(url: string): Promise<T | null> {
	try {
		const response = await fetch(url);
		if (!response.ok) return null;
		return (await response.json()) as T;
	} catch {
		return null;
	}
}

/** Read a bundle's own metadata, for the bodies that appear in no system file. */
async function fromBundle(bodyId: string): Promise<BodySources> {
	const meta = await fetchJson<{
		exports?: Record<string, unknown>;
		[key: string]: unknown;
	}>(versionedUrl(`/v1/textures/${bodyId}/metadata.json`, 'textures'));
	if (!meta) return {};
	const tiers = Object.keys(meta.exports ?? {}).filter((k) =>
		['low', 'medium', 'high'].includes(k)
	);
	if (tiers.length === 0) return {};
	return {
		surface: {
			id: bodyId,
			tiers,
			source: String(meta.source ?? ''),
			organisation: String(meta.organisation ?? ''),
			type: String(meta.type ?? 'cylindrical'),
			attribution: meta.attribution as string | undefined,
			description: meta.description as string | undefined,
			license: meta.license as string | undefined
		}
	};
}

/** Every picture the export has of this body's surface. Empty when it has no
 *  map at all, which is most of the catalogue. */
export async function loadBodySources(bodyId: string): Promise<BodySources> {
	const systemId = systemIdFor(bodyId);
	if (!systemId) return fromBundle(bodyId);
	const system = await fetchJson<Record<string, SystemEntry>>(
		`${dataBase()}/v1/systems/${systemId}.json`
	);
	const entry = system?.[bodyId];
	if (!entry?.texture || !entry.tiers?.length) return fromBundle(bodyId);
	const { frames, ...texture } = entry.texture;
	const radii = entry.radii;
	return {
		surface: { id: bodyId, tiers: entry.tiers, ...texture, monthlyFrames: frames },
		clouds: entry.clouds,
		night: entry.night,
		radiusKm: radii ? (radii.a + radii.b + radii.c) / 3 : undefined
	};
}

/** The best tier a bundle ships at or below `wanted`, so a request never asks
 *  for a file that was never written. */
export function bestTier(tiers: readonly string[], wanted: string): string {
	const order = ['low', 'medium', 'high'];
	const cap = order.indexOf(wanted);
	for (let i = cap < 0 ? order.length - 1 : cap; i >= 0; i--) {
		if (tiers.includes(order[i])) return order[i];
	}
	return tiers[0] ?? 'low';
}

/**
 * URL of one picture out of a bundle, at a tier and a moment.
 *
 * Which file that is depends on what changes with time: nothing for most
 * bodies, the month for Earth's seasonal surface, and a dated snapshot for the
 * cloud overlays.
 */
export function bundleUrl(
	bundle: BundleMeta & { monthlyFrames?: number },
	tier: string,
	jd: number
): string {
	const id = bundle.id;
	if (bundle.frames?.length) {
		const frame = cloudFrameForJd(jd, bundle.frames, bundle.coverage);
		if (frame) return versionedUrl(`/v1/textures/${id}/${tier}_${frame}.webp`, 'textures');
	}
	const month = textureFrameForJd(jd, bundle.monthlyFrames);
	if (month !== undefined) {
		const nn = String(month).padStart(2, '0');
		return versionedUrl(`/v1/textures/${id}/${tier}_${nn}.webp`, 'textures');
	}
	return versionedUrl(`/v1/textures/${id}/${tier}.webp`, 'textures');
}
