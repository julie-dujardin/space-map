/**
 * The dust nest (`docs/export-format/dust.md`): Sun-centred textures of the
 * extinction density, on Galactic axes in pc. This module fetches them and
 * reads them on the CPU.
 *
 * The CPU read keeps the order of the shader: it filters the codes, then it
 * decodes. The build sets the codes for that order.
 */

import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import {
	extrasolarAllowed,
	extrasolarBase,
	fetchExtrasolarFile,
	type ExtrasolarCredit
} from '$lib/fetch/extrasolar/files';
import { DUST_NEAR_PC, rayThroughBox, type RaySpan } from './layout';
import type { Vec3 } from './octahedral';

export const DUST_FORMAT = 1;

/** The nest is not in a form this code reads. A retry reads the same. */
export class NestFormatError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'NestFormatError';
	}
}

export type NestTier = 'high' | 'low';
export type Mat3Rows = [Vec3, Vec3, Vec3];

export interface NestFile {
	path: string;
	size: Vec3;
	bytes: number;
}

export interface NestLevelEntry {
	level: number;
	half_extent_pc: Vec3;
	floor: number;
	top: number;
	high: NestFile;
	low: NestFile;
}

export interface NestCredit {
	key: string;
	name: string;
	citation: string;
	source: string;
	attribution?: string;
	license: string | null;
	distribution: string;
}

export interface NestMetadata {
	format: number;
	token: string;
	distribution: string;
	frame: { rotation_to_icrs: Mat3Rows };
	levels: NestLevelEntry[];
	credits: NestCredit[];
}

/** One level of the nest in memory. */
export interface NestLevel {
	half: Vec3;
	floor: number;
	/** log(1 + top / floor). */
	span: number;
	size: Vec3;
	codes: Uint8Array;
}

/** Request Timeout and Too Many Requests: a later try can pass. */
const RETRYABLE = new Set([408, 429]);

type Stored = { format: number; distribution?: string };

async function loadStoredMetadata<T extends Stored>(
	url: string,
	prefix: string,
	format: number
): Promise<T | null> {
	if (extrasolarBase() === '') return null;
	const res = await fetchWithTimeout(url, { cache: 'no-cache' });
	// A host with no such export draws the stars as they are.
	if (res.status === 404) return null;
	// A refusal or a page that is no such export reads the same on a retry. A
	// timeout, a rate limit, a 5xx or a dropped connection may not.
	if (res.status >= 400 && res.status < 500 && !RETRYABLE.has(res.status)) {
		throw new NestFormatError(`${prefix} metadata.json returned ${res.status}`);
	}
	if (!res.ok) throw new Error(`${prefix} metadata.json returned ${res.status}`);
	const meta = (await res.json().catch((e: unknown) => {
		if (e instanceof SyntaxError) throw new NestFormatError(`${prefix} metadata.json is not JSON`);
		throw e;
	})) as T;
	if (meta.format !== format) {
		throw new NestFormatError(`${prefix} format ${meta.format}, this code reads ${format}`);
	}
	return extrasolarAllowed(meta) ? meta : null;
}

/** Metadata by URL, on its way or in. */
const metadata = new Map<string, Promise<unknown>>();

/**
 * A stored export's metadata, once per base URL, or null where this host may
 * not draw it. The scene and /credits share it. A failure is not kept, so the
 * next call tries again.
 */
export function fetchStoredMetadata<T extends Stored>(
	prefix: string,
	format: number
): Promise<T | null> {
	const url = `${extrasolarBase()}/v1/${prefix}/metadata.json`;
	const kept = metadata.get(url);
	if (kept) return kept as Promise<T | null>;
	const p = loadStoredMetadata<T>(url, prefix, format);
	metadata.set(url, p);
	p.catch(() => {
		if (metadata.get(url) === p) metadata.delete(url);
	});
	return p;
}

/** The nest's metadata, or null where this host may not draw it. */
export const fetchNestMetadata = (): Promise<NestMetadata | null> =>
	fetchStoredMetadata<NestMetadata>('dust', DUST_FORMAT);

/** The authors and year of a citation. An author list can hold commas. */
function citedWork(citation: string): string {
	return /^.*?\b\d{4}\b/.exec(citation)?.[0] ?? citation;
}

/**
 * The nest's sources as export credits. A source goes by its citation, which
 * makes it a paper for `inSceneCredits`, so it stays off the credit bar. A
 * source that asks for its own attribution keeps its name, so the popover
 * names it; the bar shows only licensed credits.
 */
export function nestCredits(meta: NestMetadata): ExtrasolarCredit[] {
	return meta.credits.map((credit) => ({
		name: credit.name,
		organisation: credit.attribution ? credit.name : citedWork(credit.citation),
		source: credit.source,
		citation: credit.citation,
		license: credit.license ?? undefined,
		attribution: credit.attribution
	}));
}

/** The nest's credits for /credits; none where this host may not draw it. */
export async function fetchNestCredits(): Promise<ExtrasolarCredit[]> {
	const meta = await fetchNestMetadata().catch((e: unknown) => {
		console.warn('[credits] dust metadata did not load:', e);
		return null;
	});
	return meta ? nestCredits(meta) : [];
}

/** The levels of one tier, fine levels last, as the metadata lists them. */
export async function fetchNestLevels(meta: NestMetadata, tier: NestTier): Promise<NestLevel[]> {
	return Promise.all(
		meta.levels.map(async (entry) => {
			const file = entry[tier];
			const container = await fetchExtrasolarFile(file.path, meta.token, {
				prefix: 'dust',
				priority: 'low'
			});
			if (container.kind !== KIND_VOLUME) {
				throw new NestFormatError(`dust ${file.path}: kind ${container.kind}, not a volume`);
			}
			const codes = container.uint8('codes');
			if (codes.length !== file.size[0] * file.size[1] * file.size[2]) {
				throw new NestFormatError(`dust ${file.path}: texel count`);
			}
			return {
				half: entry.half_extent_pc,
				floor: entry.floor,
				span: Math.log1p(entry.top / entry.floor),
				size: file.size,
				codes
			};
		})
	);
}

/** The rows of `rotation_to_icrs`, transposed: tree axes to nest axes. */
export function treeToNest(rotation: Mat3Rows, v: readonly [number, number, number]): Vec3 {
	return [
		rotation[0][0] * v[0] + rotation[1][0] * v[1] + rotation[2][0] * v[2],
		rotation[0][1] * v[0] + rotation[1][1] * v[1] + rotation[2][1] * v[2],
		rotation[0][2] * v[0] + rotation[1][2] * v[1] + rotation[2][2] * v[2]
	];
}

/** The filtered code at a point of a level's box, as `LINEAR` reads it. */
function filteredCode(level: NestLevel, x: number, y: number, z: number): number {
	const [nx, ny, nz] = level.size;
	const [hx, hy, hz] = level.half;
	const gx = Math.min(Math.max(((x + hx) / (2 * hx)) * nx - 0.5, 0), nx - 1);
	const gy = Math.min(Math.max(((y + hy) / (2 * hy)) * ny - 0.5, 0), ny - 1);
	const gz = Math.min(Math.max(((z + hz) / (2 * hz)) * nz - 0.5, 0), nz - 1);
	const ix = Math.min(gx | 0, nx - 2);
	const iy = Math.min(gy | 0, ny - 2);
	const iz = Math.min(gz | 0, nz - 2);
	const fx = gx - ix;
	const fy = gy - iy;
	const fz = gz - iz;
	const c = level.codes;
	const row = nx;
	const plane = nx * ny;
	const at = ix + row * iy + plane * iz;
	const c00 = c[at] + (c[at + 1] - c[at]) * fx;
	const c10 = c[at + row] + (c[at + row + 1] - c[at + row]) * fx;
	const c01 = c[at + plane] + (c[at + plane + 1] - c[at + plane]) * fx;
	const c11 = c[at + plane + row] + (c[at + plane + row + 1] - c[at + plane + row]) * fx;
	const c0 = c00 + (c10 - c00) * fy;
	const c1 = c01 + (c11 - c01) * fy;
	return c0 + (c1 - c0) * fz;
}

/** Extinction density (mag/pc) at a point on nest axes, from the finest level
 *  that holds it. `levels` run from coarse to fine. */
export function densityAt(levels: readonly NestLevel[], x: number, y: number, z: number): number {
	const ax = Math.abs(x);
	const ay = Math.abs(y);
	const az = Math.abs(z);
	for (let i = levels.length - 1; i >= 0; i--) {
		const level = levels[i];
		if (ax > level.half[0] || ay > level.half[1] || az > level.half[2]) continue;
		const code = filteredCode(level, x, y, z);
		return level.floor * Math.expm1((code / 255) * level.span);
	}
	return 0;
}

/** Steps of a CPU ray. */
const CPU_STEPS = 48;

/**
 * The column (mag at 550 nm) from `from` to `to`, on nest axes, with steps that
 * grow with distance as the map's do. The same two points give the same value
 * to the last bit, so a difference of two rays from one origin is exact.
 */
export function columnBetween(
	levels: readonly NestLevel[],
	from: Vec3,
	to: Vec3,
	steps = CPU_STEPS
): number {
	const dx = to[0] - from[0];
	const dy = to[1] - from[1];
	const dz = to[2] - from[2];
	const r = Math.hypot(dx, dy, dz);
	if (r === 0) return 0;
	const d: Vec3 = [dx / r, dy / r, dz / r];
	const span: RaySpan = rayThroughBox(from, d);
	const end = Math.min(span.far, r);
	if (end <= span.near) return 0;
	const scale = Math.max(DUST_NEAR_PC, span.near);
	const lnq = Math.log1p((end - span.near) / scale) / steps;
	const q = Math.exp(lnq);
	let e = scale * Math.exp(0.5 * lnq);
	let sum = 0;
	for (let i = 0; i < steps; i++) {
		const t = span.near + e - scale;
		sum += densityAt(levels, from[0] + d[0] * t, from[1] + d[1] * t, from[2] + d[2] * t) * e * lnq;
		e *= q;
	}
	return sum;
}
