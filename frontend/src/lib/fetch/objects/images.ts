/**
 * Helpers for resolving image URLs against the per-image bundle layout:
 *
 *   /data/v1/images/<file>/{s,m,xl}.<ext>
 *   /data/v1/images/<file>/metadata.json.gz
 *
 * The exporter emits only the variants the source actually covers — small
 * sources produce only `s` (verbatim, no upscale). Callers pass a target
 * pixel width; `pickImageUrl` returns the URL for the smallest variant that
 * meets it, falling back to the largest available when the source is
 * smaller than the request.
 */

import { DATA_BASE } from '$lib/fetch/data-base';
import type { ImageVariants, ObjectImage } from './object-data';

const BUCKET_DIMS = { s: 512, m: 1024, xl: 4096 } as const;

type VariantLabel = keyof typeof BUCKET_DIMS;

const LABEL_ORDER: readonly VariantLabel[] = ['s', 'm', 'xl'];

function availableLabels(variants: ImageVariants): VariantLabel[] {
	return LABEL_ORDER.filter((l) => variants[l] !== undefined);
}

/**
 * Pick the smallest emitted variant whose bucket dimension covers
 * `targetDevicePx` (CSS px × devicePixelRatio). Falls back to the largest
 * available variant when the source is smaller than the request.
 *
 * Returns undefined only when the image has no declared variants — which
 * shouldn't happen for servable images but is guarded defensively.
 */
export function pickImageUrl(image: ObjectImage, targetDevicePx: number): string | undefined {
	const available = availableLabels(image.variants);
	if (!available.length) return undefined;
	const label =
		available.find((l) => BUCKET_DIMS[l] >= targetDevicePx) ?? available[available.length - 1];
	return variantUrl(image, label);
}

/** Return the URL for a specific variant, or undefined if it wasn't emitted. */
export function variantUrl(image: ObjectImage, label: VariantLabel): string | undefined {
	const ext = image.variants[label];
	if (!ext) return undefined;
	return `${DATA_BASE}/v1/images/${encodeURIComponent(image.file)}/${label}.${ext}`;
}

/** URL of the gzipped per-image metadata JSON. */
export function metadataUrl(image: ObjectImage): string {
	return `${DATA_BASE}/v1/images/${encodeURIComponent(image.file)}/metadata.json.gz`;
}

/** Fetch and decompress the per-image metadata JSON. */
export async function fetchImageMetadata(image: ObjectImage): Promise<ImageMetadata | null> {
	const res = await fetch(metadataUrl(image));
	if (!res.ok) return null;
	const ds = new DecompressionStream('gzip');
	return (await new Response(res.body!.pipeThrough(ds)).json()) as ImageMetadata;
}

/**
 * Trimmed shape written by the exporter. Bare strings appear when Commons
 * didn't return a multilang blob; when a dict is present its keys are
 * restricted to the supported locales (ar/en/fr/ja/ru/zh). HTML fragments
 * from Commons still ride through — callers must strip.
 */
export interface ImageMetadata {
	source_url: string;
	license?: { name?: string; url?: string };
	artist?: string | Record<string, string>;
	description?: string | Record<string, string>;
	/** ISO-truncated creation date: "YYYY-MM-DD" / "YYYY-MM" / "YYYY". */
	date?: string;
	/** Wikidata QIDs from Commons SDC P180 ("depicts"). */
	depicts?: string[];
}
