/**
 * Server-side SEO meta for a content page.
 *
 * Runs only during SSR (crawlers, first paint) — see the `browser` guard in the
 * page loads. Deliberately self-contained rather than reusing the client fetch
 * layer: that layer leans on module-singleton caches, unsuited to a per-request
 * server load, and touches no shared state here.
 *
 * Fetches use the global `fetch` against an absolute URL, NOT the load's
 * `event.fetch`: in dev the data path (`/data/...`) collides with the
 * `[type]/[id]` route, and event.fetch dispatches it to the router (returning
 * HTML) instead of the vite proxy. A real network request to the origin hits
 * the proxy in dev and the CDN in prod.
 */

import { DATA_BASE, IMAGES_BASE } from '$lib/fetch/data-base';
import { hashBucket } from '$lib/fetch/metadata';
import type {
	GlobalObjectData,
	LocalizedObjectData,
	ObjectImage
} from '$lib/fetch/objects/object-data';
import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';

/** Localized shapes share this description source (object + group bundles). */
type Describable = { wikipedia?: { extract?: string }; description?: string } | null;

export interface SeoMeta {
	title: string;
	description: string;
	/** Absolute canonical URL. */
	canonical: string;
	/** Absolute OG image URL, when the object has one. */
	image?: string;
	ogType: 'website' | 'article';
}

// English is the SSR default: it's the right baseline for search/social, and
// there's no server-side locale context (no hooks.server.ts) to key off yet.
const SSR_LANG = 'en';

// OG images want ~1200px; prefer the medium bucket, fall back either way.
const OG_LABELS = ['m', 'xl', 's'] as const;

const DESCRIPTION_MAX = 200;

async function fetchJsonGz(url: string): Promise<Record<string, unknown> | null> {
	const res = await fetch(url);
	if (!res.ok) return null;
	const ds = new DecompressionStream('gzip');
	return (await new Response(res.body!.pipeThrough(ds)).json()) as Record<string, unknown>;
}

/** Absolute for a cross-origin CDN base; else resolved against the request. */
function absolutize(url: string, origin: string): string {
	return /^https?:\/\//i.test(url) ? url : `${origin}${url}`;
}

function versioned(url: string, token: string | undefined): string {
	return token ? `${url}?v=${token}` : url;
}

function ogImage(
	images: ObjectImage[] | undefined,
	imagesToken: string | undefined,
	origin: string
): string | undefined {
	const img = images?.find((i) => i.kind === 'photo') ?? images?.find((i) => i.kind === 'logo');
	if (!img) return undefined;
	for (const label of OG_LABELS) {
		const ext = img.variants[label];
		if (!ext) continue;
		const path = `/v1/images/${encodeURIComponent(img.file)}/${label}.${ext}`;
		return absolutize(versioned(`${IMAGES_BASE}${path}`, imagesToken), origin);
	}
	return undefined;
}

function cleanDescription(raw: string): string {
	const text = raw
		.replace(/<[^>]*>/g, '')
		.replace(/\s+/g, ' ')
		.trim();
	if (text.length <= DESCRIPTION_MAX) return text;
	const cut = text.slice(0, DESCRIPTION_MAX);
	const lastSpace = cut.lastIndexOf(' ');
	return `${cut.slice(0, lastSpace > 0 ? lastSpace : DESCRIPTION_MAX).trimEnd()}…`;
}

function describe(name: string, localized: Describable): string {
	const raw = localized?.wikipedia?.extract || localized?.description;
	if (raw) return cleanDescription(raw);
	return `Explore ${name} in Space Map — an interactive 3D map of the solar system.`;
}

/** Title from an object/collection name, matching the client's `<title>`. */
export function pageTitle(name: string): string {
	return name ? `${name} - Space Map` : 'Space Map';
}

/** Baseline meta when there's no per-object data to fetch (groups, features,
 *  unknown ids): a title and canonical still make the page shareable. */
export function minimalSeo(name: string, origin: string, path: string): SeoMeta {
	return {
		title: pageTitle(name),
		description: name
			? `Explore ${name} in Space Map — an interactive 3D map of the solar system.`
			: 'Space Map — an interactive 3D map of the solar system.',
		canonical: `${origin}${path}`,
		ogType: 'website'
	};
}

/** Fetch one object's global + localized bundles server-side and build its meta.
 *  Returns null when the object isn't found so the caller can fall back. */
export async function loadObjectSeo(
	fileId: string,
	origin: string,
	path: string
): Promise<SeoMeta | null> {
	const base = absolutize(DATA_BASE, origin);
	const metaRes = await fetch(`${base}/v1/metadata.json`);
	if (!metaRes.ok) return null;
	const meta = (await metaRes.json()) as {
		object_bundles: Record<string, number>;
		versions?: Record<string, string>;
	};
	const token = meta.versions?.objects;

	const nGlobal = meta.object_bundles.global;
	const nLocalized = meta.object_bundles[SSR_LANG] ?? 0;
	const [gBucket, lBucket] = await Promise.all([
		hashBucket(fileId, nGlobal),
		nLocalized ? hashBucket(fileId, nLocalized) : Promise.resolve(-1)
	]);

	const [gBundle, lBundle] = await Promise.all([
		fetchJsonGz(versioned(`${base}/v1/objects/__global__/${gBucket}.json.gz`, token)),
		lBucket >= 0
			? fetchJsonGz(versioned(`${base}/v1/objects/${SSR_LANG}/${lBucket}.json.gz`, token))
			: Promise.resolve(null)
	]);

	const global = (gBundle?.[fileId] as GlobalObjectData | undefined) ?? null;
	if (!global) return null;
	const localized = (lBundle?.[fileId] as LocalizedObjectData | undefined) ?? null;

	const name = localized?.name || global.name || '';
	return {
		title: pageTitle(name),
		description: describe(name, localized),
		canonical: `${origin}${path}`,
		image: ogImage(global.images, meta.versions?.images, origin),
		ogType: 'article'
	};
}

// Group slug prefixes to strip when a collection has no localized name yet.
const GROUP_PREFIXES = [
	'const-',
	'class-',
	'cat-',
	'flag-',
	'comet-family-',
	'mission-',
	'bus-',
	'lv-'
];

function prettifySlug(slug: string): string {
	const prefix = GROUP_PREFIXES.find((p) => slug.startsWith(p));
	const stem = prefix ? slug.slice(prefix.length) : slug;
	return stem.replace(/[-_]/g, ' ').trim() || slug;
}

/** Meta for a /g/<slug> collection page. The display name lives in the localized
 *  bundle; the global bundle carries images. Group bundles are unversioned. */
export async function loadGroupSeo(
	slug: string,
	origin: string,
	path: string
): Promise<SeoMeta | null> {
	const base = absolutize(DATA_BASE, origin);
	const metaRes = await fetch(`${base}/v1/metadata.json`);
	if (!metaRes.ok) return null;
	const meta = (await metaRes.json()) as {
		group_bundles: Record<string, number>;
		versions?: Record<string, string>;
	};

	const nGlobal = meta.group_bundles.global;
	const nLocalized = meta.group_bundles[SSR_LANG] ?? 0;
	const [gBucket, lBucket] = await Promise.all([
		hashBucket(slug, nGlobal),
		nLocalized ? hashBucket(slug, nLocalized) : Promise.resolve(-1)
	]);

	const [gBundle, lBundle] = await Promise.all([
		fetchJsonGz(`${base}/v1/groups/__global__/${gBucket}.json.gz`),
		lBucket >= 0
			? fetchJsonGz(`${base}/v1/groups/${SSR_LANG}/${lBucket}.json.gz`)
			: Promise.resolve(null)
	]);

	const global = (gBundle?.[slug] as GlobalGroupData | undefined) ?? null;
	const localized = (lBundle?.[slug] as LocalizedGroupData | undefined) ?? null;
	if (!global && !localized) return null;

	const name = localized?.name || prettifySlug(slug);
	return {
		title: pageTitle(name),
		description: describe(name, localized),
		canonical: `${origin}${path}`,
		image: ogImage(global?.images, meta.versions?.images, origin),
		ogType: 'website'
	};
}
