/**
 * The glow's credits for /credits: the papers and datasets of the model and of
 * the emission, in the shape of the nest's credits. The grid reads only the tree
 * and the nest, which credit themselves.
 */

import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
import {
	fetchStoredMetadata,
	nestCredits,
	type NestCredit,
	type NestMetadata
} from '$lib/scene/dust/nest';
import { GLOW_FORMAT } from './grid';

interface GlowCreditsMetadata {
	format: number;
	distribution?: string;
	credits: readonly NestCredit[];
}

/** The glow's credits, as the nest's are mapped. */
export function glowCredits(meta: Pick<GlowCreditsMetadata, 'credits'>): ExtrasolarCredit[] {
	// `nestCredits` reads the credits alone.
	return nestCredits(meta as NestMetadata);
}

/** The glow's credits for /credits; none where this host has no glow, or may not draw it. */
export async function fetchGlowCredits(): Promise<ExtrasolarCredit[]> {
	const meta = await fetchStoredMetadata<GlowCreditsMetadata>('glow', GLOW_FORMAT).catch(
		(e: unknown) => {
			console.warn('[credits] glow metadata did not load:', e);
			return null;
		}
	);
	return meta ? glowCredits(meta) : [];
}

/** The first credit of each source. The nest and the model both list the papers
 *  of the rest layer's shape. */
export function eachSourceOnce(credits: readonly ExtrasolarCredit[]): ExtrasolarCredit[] {
	const seen = new Set<string>();
	return credits.filter(({ source }) => {
		if (seen.has(source)) return false;
		seen.add(source);
		return true;
	});
}
