/**
 * Helpers for resolving image URLs against the per-image bundle layout:
 *
 *   /data/v1/images/<file>/{s,m,xl}.<ext>
 *   /data/v1/images/<file>/sidecar.json.gz   (only when EXIF can't carry)
 *
 * The exporter emits only the variants the source actually covers — small
 * sources produce only `s` (verbatim, no upscale). Callers pass a target
 * pixel width; `pickImageUrl` returns the URL for the smallest variant that
 * meets it, falling back to the largest available when the source is
 * smaller than the request.
 *
 * Viewer metadata (license/artist/description/…) rides inside each raster
 * variant's EXIF — a per-image JSON file would count against the images
 * Worker's file budget. Bundles whose variants can't embed (SVG/WebM
 * passthrough, oversize payloads) ship the sidecar instead.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { versionedImageUrl } from '$lib/fetch/data-base';
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
	return versionedImageUrl(`/v1/images/${encodeURIComponent(image.file)}/${label}.${ext}`);
}

/** Pre-picked thumbnail descriptor: a single emitted variant, as written by
 *  the search indexer and the group notable-members exporter. */
export interface PickedThumbnail {
	file: string;
	/** Variant bucket: `s` (512px) when emitted, `m` / `xl` for sources that
	 *  skipped smaller buckets (e.g. SVG/WebM passthrough → `xl` only). */
	label: 's' | 'm' | 'xl';
	ext: string;
}

/** URL for a pre-picked thumbnail descriptor. */
export function pickedThumbnailUrl(t: PickedThumbnail): string {
	return versionedImageUrl(`/v1/images/${encodeURIComponent(t.file)}/${t.label}.${t.ext}`);
}

/** Formats that can't carry the embedded EXIF payload. */
const NO_EXIF_EXTS = new Set(['svg', 'webm']);

/** Smallest variant that can carry the EXIF payload — the cheapest bytes to
 *  fetch for metadata (usually already in the HTTP cache from display). */
export function smallestRasterVariant(variants: ImageVariants): VariantLabel | undefined {
	return LABEL_ORDER.find((l) => {
		const ext = variants[l];
		return ext !== undefined && !NO_EXIF_EXTS.has(ext);
	});
}

const META_SENTINEL = 'SPACEMAP-META:v1:';

/**
 * Extract the exporter's sentinel-wrapped metadata JSON from raw image bytes.
 *
 * A byte scan, not an EXIF parse: the payload is length-prefixed ASCII JSON
 * (`SPACEMAP-META:v1:<byte-len>:<json>`) placed in an EXIF ImageDescription,
 * so searching bytes is container-agnostic (WebP/JPEG/AVIF) and works in
 * workerd, whose TextDecoder is UTF-8-only.
 */
export function extractEmbeddedImageMetadata(bytes: Uint8Array): ImageMetadata | null {
	const at = findAscii(bytes, META_SENTINEL);
	if (at === -1) return null;
	let i = at + META_SENTINEL.length;
	let len = 0;
	while (i < bytes.length && bytes[i] >= 0x30 && bytes[i] <= 0x39) {
		len = len * 10 + (bytes[i] - 0x30);
		i++;
	}
	if (len <= 0 || bytes[i] !== 0x3a /* ':' */ || i + 1 + len > bytes.length) return null;
	try {
		return JSON.parse(
			new TextDecoder().decode(bytes.subarray(i + 1, i + 1 + len))
		) as ImageMetadata;
	} catch {
		return null;
	}
}

function findAscii(bytes: Uint8Array, needle: string): number {
	const first = needle.charCodeAt(0);
	outer: for (let i = 0; i + needle.length <= bytes.length; i++) {
		if (bytes[i] !== first) continue;
		for (let j = 1; j < needle.length; j++) {
			if (bytes[i + j] !== needle.charCodeAt(j)) continue outer;
		}
		return i;
	}
	return -1;
}

/** URL of the gzipped fallback metadata JSON. */
function sidecarUrl(image: ObjectImage): string {
	return versionedImageUrl(`/v1/images/${encodeURIComponent(image.file)}/sidecar.json.gz`);
}

/** Fetch the per-image metadata: EXIF from the smallest raster variant,
 *  falling back to the sidecar for bundles that couldn't embed. */
export async function fetchImageMetadata(image: ObjectImage): Promise<ImageMetadata | null> {
	const label = smallestRasterVariant(image.variants);
	const url = label ? variantUrl(image, label) : undefined;
	if (url) {
		try {
			const res = await fetch(url);
			if (res.ok) {
				const meta = extractEmbeddedImageMetadata(new Uint8Array(await res.arrayBuffer()));
				if (meta) return meta;
			}
		} catch {
			// Embed miss or network hiccup — the sidecar below is authoritative.
		}
	}
	const res = await fetch(sidecarUrl(image));
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

/** Resolve a multilang metadata field to plain text.
 *
 *  The exporter writes bare strings when Commons didn't return a multilang
 *  blob and `{<locale>: str}` dicts (restricted to supported locales) when it
 *  did. HTML fragments from Commons ride along and are stripped here.
 *
 *  With `strictLocale` a dict resolves only for the reader's own locale — a
 *  description in an arbitrary other language is unreadable, where a credit
 *  ("NASA/JPL") is the same name whatever the locale. Bare strings are
 *  returned either way. */
export function imageMetadataText(
	value: string | Record<string, string> | undefined,
	strictLocale = false
): string | undefined {
	if (value === undefined) return undefined;
	const raw = typeof value === 'string' ? value : pickLang(value, strictLocale);
	if (!raw) return undefined;
	// Commons extmetadata HTML is attacker-editable; parse it in an inert
	// DOMParser doc so `<img onerror>`-style payloads can't fire (a live
	// element's innerHTML would run them).
	const tmp = new DOMParser().parseFromString(raw, 'text/html').body;
	for (const br of tmp.querySelectorAll('br')) br.replaceWith('\n');
	for (const block of tmp.querySelectorAll('p, div, li')) block.append('\n\n');
	const text = (tmp.textContent ?? '')
		// Collapse non-newline whitespace runs; keep newlines intact.
		.replace(/[^\S\n]+/g, ' ')
		// Normalize any run of 2+ newlines to exactly one blank line.
		.replace(/\n{2,}/g, '\n\n')
		.trim();
	return text || undefined;
}

function pickLang(value: Record<string, string>, strictLocale: boolean): string {
	const locale = getLocale();
	if (typeof value[locale] === 'string') return value[locale];
	if (strictLocale) return '';
	if (typeof value.en === 'string') return value.en;
	for (const v of Object.values(value)) {
		if (typeof v === 'string') return v;
	}
	return '';
}
