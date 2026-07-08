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

/** Localized shapes share this description source (object + group bundles).
 *  `description` is the CC0 Wikidata short description — the Wikipedia extract
 *  is deliberately absent here (CC BY-SA, no credit surface in a card). */
type Describable = { description?: string } | null;

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

interface OgPick {
	url: string;
	file: string;
	attr: 'free' | 'credit';
}

// Longest artist string inlined into a card credit before we truncate it.
const CREDIT_ARTIST_MAX = 60;

// Prefer attribution-free images; fall back to a credit-tier image, which the
// caller must attribute in the description. `other` (uncreditable) is skipped.
// Keeps ingest rank order; prefers photo over logo.
function pickOgImage(
	images: ObjectImage[] | undefined,
	imagesToken: string | undefined,
	origin: string
): OgPick | undefined {
	const pick = (tier: 'free' | 'credit') =>
		images?.find((i) => i.kind === 'photo' && i.attr === tier) ??
		images?.find((i) => i.kind === 'logo' && i.attr === tier);
	const img = pick('free') ?? pick('credit');
	if (img?.attr !== 'free' && img?.attr !== 'credit') return undefined;
	for (const label of OG_LABELS) {
		const ext = img.variants[label];
		if (!ext) continue;
		const path = `/v1/images/${encodeURIComponent(img.file)}/${label}.${ext}`;
		return {
			url: absolutize(versioned(`${IMAGES_BASE}${path}`, imagesToken), origin),
			file: img.file,
			attr: img.attr
		};
	}
	return undefined;
}

function pickLocale(v: string | Record<string, string> | undefined): string | undefined {
	if (!v || typeof v === 'string') return v || undefined;
	return v[SSR_LANG] ?? v.en ?? Object.values(v)[0];
}

/** Front-loadable credit for a `credit`-tier card image, or null when the
 *  author is missing — a license name alone can't attribute it. */
function buildCredit(meta: {
	license?: { name?: string };
	artist?: string | Record<string, string>;
}): string | null {
	const license = meta.license?.name;
	const artistRaw = pickLocale(meta.artist);
	if (!license || !artistRaw) return null;
	const artist = truncate(stripHtml(artistRaw), CREDIT_ARTIST_MAX);
	return artist ? `Image: ${artist} (${license})` : null;
}

/** Fetch the chosen image's metadata and build its credit line. */
async function fetchImageCredit(
	file: string,
	origin: string,
	imagesToken: string | undefined
): Promise<string | null> {
	const url = absolutize(
		versioned(`${IMAGES_BASE}/v1/images/${encodeURIComponent(file)}/metadata.json.gz`, imagesToken),
		origin
	);
	const meta = await fetchJsonGz(url);
	return meta
		? buildCredit(meta as { license?: { name?: string }; artist?: string | Record<string, string> })
		: null;
}

/** Resolve the card image + description together: a `credit`-tier image is only
 *  used when we can front-load its attribution; otherwise it's dropped so the
 *  card degrades to no image rather than an uncredited one. */
async function resolveOgCard(
	images: ObjectImage[] | undefined,
	baseDescription: string,
	origin: string,
	imagesToken: string | undefined
): Promise<{ image?: string; description: string }> {
	const pick = pickOgImage(images, imagesToken, origin);
	if (!pick) return { description: baseDescription };
	if (pick.attr === 'free') return { image: pick.url, description: baseDescription };
	const credit = await fetchImageCredit(pick.file, origin, imagesToken);
	if (!credit) return { description: baseDescription };
	return { image: pick.url, description: `${credit}. ${baseDescription}` };
}

function stripHtml(raw: string): string {
	return raw
		.replace(/<[^>]*>/g, '')
		.replace(/\s+/g, ' ')
		.trim();
}

function truncate(text: string, max: number): string {
	if (text.length <= max) return text;
	const cut = text.slice(0, max);
	const lastSpace = cut.lastIndexOf(' ');
	return `${cut.slice(0, lastSpace > 0 ? lastSpace : max).trimEnd()}…`;
}

function cleanDescription(raw: string): string {
	return truncate(stripHtml(raw), DESCRIPTION_MAX);
}

// Wikidata short descriptions are sentence-case ("moon of Saturn"); capitalize
// at display like the sidebar (ObjectHeader) rather than mutate the source.
function ucfirst(s: string): string {
	return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function describe(name: string, localized: Describable): string {
	// Only the CC0 Wikidata short description — the Wikipedia extract is CC BY-SA
	// and a social card has no surface for the required credit.
	const raw = localized?.description;
	if (raw) return ucfirst(cleanDescription(raw));
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
	const card = await resolveOgCard(
		global.images,
		describe(name, localized),
		origin,
		meta.versions?.images
	);
	return {
		title: pageTitle(name),
		description: card.description,
		canonical: `${origin}${path}`,
		image: card.image,
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
	const card = await resolveOgCard(
		global?.images,
		describe(name, localized),
		origin,
		meta.versions?.images
	);
	return {
		title: pageTitle(name),
		description: card.description,
		canonical: `${origin}${path}`,
		image: card.image,
		ogType: 'website'
	};
}
