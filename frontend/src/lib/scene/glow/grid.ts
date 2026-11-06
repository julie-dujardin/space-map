/**
 * The catalogue light grid (`docs/export-format/glow.md`): the light of the
 * stars of the render tree, by how faint they are, on nest axes in pc. A cut
 * reads the light of the stars that do not draw as points.
 */

import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { fetchExtrasolarFile } from '$lib/fetch/extrasolar/files';
import { NestFormatError, fetchStoredMetadata } from '$lib/scene/dust/nest';
import { checkEmission, fetchEmission, type EmissionVolume, type GlowEmission } from './emission';
import { fetchFarDust, type FarDust } from './far-dust';
import { cloudBoxes, type CloudBox } from './clouds';
import { checkModel, fetchModelVolume, type GlowModel, type ModelVolume } from './model';
import { prefilterGrid, type CoarseGrid } from './prefilter';

export const GLOW_FORMAT = 1;

export type GlowGridTier = 'high' | 'low';

export interface GlowFile {
	path: string;
	bytes: number;
}

export interface GlowTierEntry {
	size: number;
	shells: number;
	scale_pc: number;
	reach_pc: number;
	files: { a: GlowFile; b: GlowFile };
}

export interface GlowMetadata {
	format: number;
	token: string;
	/** Tokens of the tree and the nest the grid was made from. */
	inputs: { tree: string; dust: string };
	distribution: string;
	texture_scale: number;
	neutral_tint: number;
	table: {
		magnitudes: number[];
		/** For stars that fade in at the limit: the light of the fade's complement. */
		place_soft: number[];
		/** Share of R, G and B. */
		colour: [number, number, number][];
	};
	tiers: Record<GlowGridTier, GlowTierEntry>;
	/** Model light of the whole Galaxy; a host without it draws the grid alone. */
	model?: GlowModel;
	/** Light that is not starlight; a host without it draws starlight alone. */
	emission?: GlowEmission;
}

/** One tier of the grid in memory. Each texture holds uint16 half floats. */
export interface GlowVolume {
	entry: GlowTierEntry;
	a: Uint16Array;
	b: Uint16Array;
	/** Coarse copies of `a` and `b`, read where a sample is wider than a cell. */
	coarse: CoarseGrid | null;
	model: ModelVolume | null;
	/** Boxes of the Magellanic Clouds in the model, where the march takes steps
	 *  of its own. */
	clouds: CloudBox[];
	/** The dust past the nest's box, read where the model widens the first span. */
	far: FarDust | null;
	emission: EmissionVolume | null;
}

/** The first magnitude of the cut table and its step. The march finds an entry
 *  from its index, so the magnitudes must be evenly spaced. */
export function tableAxis(meta: GlowMetadata): { first: number; step: number } {
	const m = meta.table.magnitudes;
	const first = m[0];
	const step = (m[m.length - 1] - first) / (m.length - 1);
	if (!(step > 0) || m.some((x, i) => Math.abs(x - (first + i * step)) > 1e-6 * step)) {
		throw new NestFormatError('glow metadata.json: the cut table is not evenly spaced');
	}
	return { first, step };
}

/** The grid's metadata, or null where this host has none or may not draw it. */
export async function fetchGlowMetadata(): Promise<GlowMetadata | null> {
	const meta = await fetchStoredMetadata<GlowMetadata>('glow', GLOW_FORMAT);
	// A table the march cannot read is a format error, so the load ends here.
	if (meta) tableAxis(meta);
	if (meta?.model) checkModel(meta.model);
	if (meta?.emission) checkEmission(meta.emission);
	return meta;
}

/** One texture of a tier: four half floats a texel. */
async function fetchTexture(
	meta: GlowMetadata,
	entry: GlowTierEntry,
	file: GlowFile
): Promise<Uint16Array> {
	const container = await fetchExtrasolarFile(file.path, meta.token, {
		prefix: 'glow',
		priority: 'low'
	});
	if (container.kind !== KIND_VOLUME) {
		throw new NestFormatError(`glow ${file.path}: kind ${container.kind}, not a volume`);
	}
	const texels = container.uint16('texels');
	if (texels.length !== entry.size * entry.size * entry.shells * 4) {
		throw new NestFormatError(`glow ${file.path}: texel count`);
	}
	return texels;
}

export async function fetchGlowVolume(meta: GlowMetadata, tier: GlowGridTier): Promise<GlowVolume> {
	const entry = meta.tiers[tier];
	const [a, b, model, far, emission] = await Promise.all([
		fetchTexture(meta, entry, entry.files.a),
		fetchTexture(meta, entry, entry.files.b),
		meta.model ? fetchModelVolume(meta.token, meta.model, tier) : null,
		meta.model ? fetchFarDust(tier) : null,
		meta.emission ? fetchEmission(meta.token, meta.emission, tier) : null
	]);
	const clouds = meta.model && model ? cloudBoxes(meta.model, model) : [];
	const coarse = await prefilterGrid(entry.size, entry.shells, a, b, meta.neutral_tint, pacer());
	return { entry, a, b, coarse, model, clouds, far, emission };
}

/** Work (ms) between two pauses of the prefilter: half a frame at 60 Hz. */
const SLICE_MS = 8;

/** A pause after each slice of work, so the page draws. Each pause waits a few
 *  ms, so there is one a slice. */
function pacer(): () => Promise<void> {
	let start = performance.now();
	return async () => {
		if (performance.now() - start < SLICE_MS) return;
		await new Promise((resolve) => setTimeout(resolve, 0));
		start = performance.now();
	};
}

/** The cut table for the march: `place_soft` and the colour, one vec4 an entry. */
export function glowCurve(meta: GlowMetadata): Float32Array {
	const { place_soft: place, colour } = meta.table;
	const out = new Float32Array(place.length * 4);
	place.forEach((value, i) => out.set([value, ...colour[i]], 4 * i));
	return out;
}
