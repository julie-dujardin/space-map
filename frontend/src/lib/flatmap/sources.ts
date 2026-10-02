/**
 * Finding the pictures a body has. Everything drawable about a surface —
 * the map itself, the cloud snapshots over it, the lights on its night side —
 * is exported as a separate equirectangular bundle; this reads which ones
 * exist and turns them into URLs and credits.
 */

import { dataBase, versionedUrl } from '$lib/fetch/data-base';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { pickTexture, type TextureDistribution } from '$lib/host';
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
	/** Who may serve it; absent where anyone may. */
	distribution?: TextureDistribution;
	type: string;
	attribution?: string;
	description?: string;
}

/** Resolution tiers, coarsest first. */
const TIER_ORDER = ['low', 'medium', 'high'];

/** The kinds of picture a body's surface is exported as, each its own bundle. */
export type BundleKind = 'surface' | 'clouds' | 'night';

/** The bundles behind one body's flat map. `monthlyFrames` only ever arrives on
 *  a seasonal surface, but the kinds are otherwise one shape. */
export type BodySources = {
	[K in BundleKind]?: BundleMeta & { monthlyFrames?: number };
} & {
	/** Mean radius in kilometres, where the export states the body's figure.
	 *  Lets a distance along the surface be turned into an angle. */
	radiusKm?: number;
};

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

/** One body as the export's system file writes it, which is not quite how the
 *  flat map wants it: the surface bundle is called `texture` and counts its
 *  frames rather than naming them, so that one is mapped across by hand. */
interface SystemEntry {
	tiers?: string[];
	/** Triaxial radii in kilometres, along the body-fixed axes. */
	radii?: { a: number; b: number; c: number };
	texture?: Omit<BundleMeta, 'id' | 'tiers'> & { frames?: number };
	/** Maps ranked below `texture`, best first, each its own bundle. */
	alternates?: (BundleMeta & { frames?: number })[];
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

/** What a body's own record says of its map: the same blocks a system file
 *  carries, less the tiers. */
export interface StandaloneRecord {
	map_texture_available?: boolean;
	texture?: Still;
	alternates?: (Still & { id: string; tiers: string[] })[];
	radii?: { a: number; b: number; c: number };
}

/** A map as a record describes it: frames counted, as a system file has them. */
type Still = Omit<BundleMeta, 'id' | 'tiers' | 'frames'> & { frames?: number };

/** The tiers a bundle was written at, coarsest first. Nothing published says,
 *  so each file is asked after. */
async function tiersOf(bundleId: string): Promise<string[]> {
	const found = await Promise.all(
		TIER_ORDER.map((tier) =>
			fetch(versionedUrl(`/v1/textures/${bundleId}/${tier}.webp`, 'textures'), { method: 'HEAD' })
				.then((response) => response.ok)
				.catch(() => false)
		)
	);
	return TIER_ORDER.filter((_, i) => found[i]);
}

/**
 * The map of a body that appears in no system file — Ceres, Vesta, the small
 * bodies a probe has mapped — read off its own record. `tiers` answers for a
 * bundle the record does not list them for, which is the body's own.
 */
export async function fromRecord(
	bodyId: string,
	record: StandaloneRecord | null | undefined,
	tiers: (bundleId: string) => Promise<string[]> = tiersOf
): Promise<BodySources> {
	if (!record?.map_texture_available || !record.texture) return {};
	// The same walk the system file gets: the best map this viewer may serve.
	const surface = pickTexture([
		{ ...record.texture, id: bodyId, tiers: undefined as string[] | undefined },
		...(record.alternates ?? [])
	]);
	if (!surface) return {};
	const written = surface.tiers ?? (await tiers(surface.id));
	if (written.length === 0) return {};
	const { frames, ...bundle } = surface;
	const radii = record.radii;
	return {
		surface: { ...bundle, tiers: written, monthlyFrames: frames },
		radiusKm: radii ? (radii.a + radii.b + radii.c) / 3 : undefined
	};
}

async function fromBundle(bodyId: string): Promise<BodySources> {
	const detail = await fetchObjectDetail(bodyId, false).catch(() => null);
	return fromRecord(bodyId, detail?.global);
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
	// The best map this viewer may serve. The best one there is comes first and
	// is the body's own bundle; a fallback brings its own id and tiers.
	const best = { ...entry.texture, id: bodyId, tiers: entry.tiers };
	const surface = pickTexture([best, ...(entry.alternates ?? [])]);
	if (!surface) return fromBundle(bodyId);
	const { frames, ...bundle } = surface;
	const radii = entry.radii;
	return {
		surface: { ...bundle, monthlyFrames: frames },
		clouds: entry.clouds,
		night: entry.night,
		radiusKm: radii ? (radii.a + radii.b + radii.c) / 3 : undefined
	};
}

/** The maximum width of each tier. The export makes a picture smaller when it
 *  does not compress to the file size limit. No file is wider than its tier. */
export const TIER_WIDTH: Record<string, number> = { low: 2048, medium: 8192, high: 16383 };

/** The smallest tier with `width` pixels across the world, or the largest
 *  tier. A larger tier than the view can draw only costs memory. */
export function tierForWidth(width: number): string {
	return TIER_ORDER.find((tier) => TIER_WIDTH[tier] >= width) ?? TIER_ORDER[TIER_ORDER.length - 1];
}

/** The lesser of two tiers. */
export function lowerTier(a: string, b: string): string {
	return TIER_ORDER.indexOf(a) <= TIER_ORDER.indexOf(b) ? a : b;
}

/** The best tier a bundle ships at or below `wanted`, so a request never asks
 *  for a file that was never written. */
export function bestTier(tiers: readonly string[], wanted: string): string {
	const cap = TIER_ORDER.indexOf(wanted);
	for (let i = cap < 0 ? TIER_ORDER.length - 1 : cap; i >= 0; i--) {
		if (tiers.includes(TIER_ORDER[i])) return TIER_ORDER[i];
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
