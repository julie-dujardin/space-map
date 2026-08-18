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

import * as m from '$lib/paraglide/messages.js';
import { DATA_BASE, IMAGES_BASE } from '$lib/fetch/data-base';
import { extractEmbeddedImageMetadata, smallestRasterVariant } from '$lib/fetch/objects/images';
import { hashBucket } from '$lib/fetch/metadata';
import { heroImage } from '$lib/fetch/objects/galleries';
import { diameterKmFromH } from '$lib/math/h-magnitude';
import { formatQuantity } from '$lib/format/quantities';
import type {
	GlobalObjectData,
	LocalizedObjectData,
	ObjectImage
} from '$lib/fetch/objects/object-data';
import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
import type { FeatureGlobalData, FeatureLocalizedData } from '$lib/fetch/nomenclature/details';

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
	image: ObjectImage;
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
			image: img,
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

/** Fetch the chosen image's metadata and build its credit line.
 *
 * Metadata is embedded in the variants' EXIF; the imported helpers are pure
 * functions, so the self-containment note above still holds. The sidecar
 * fallback covers bundles that couldn't embed. */
async function fetchImageCredit(
	image: ObjectImage,
	origin: string,
	imagesToken: string | undefined
): Promise<string | null> {
	const base = `${IMAGES_BASE}/v1/images/${encodeURIComponent(image.file)}`;
	const label = smallestRasterVariant(image.variants);
	if (label) {
		const url = absolutize(
			versioned(`${base}/${label}.${image.variants[label]}`, imagesToken),
			origin
		);
		const res = await fetch(url).catch(() => null);
		if (res?.ok) {
			const meta = extractEmbeddedImageMetadata(new Uint8Array(await res.arrayBuffer()));
			if (meta) return buildCredit(meta);
		}
	}
	const meta = await fetchJsonGz(
		absolutize(versioned(`${base}/sidecar.json.gz`, imagesToken), origin)
	);
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
	const credit = await fetchImageCredit(pick.image, origin, imagesToken);
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

function genericDescription(name: string): string {
	return m.seo_generic_named({ name });
}

/** Group/feature description: the CC0 Wikidata short description or a generic
 *  line. The Wikipedia extract is deliberately absent (CC BY-SA, no card credit
 *  surface). Objects get richer treatment via {@link describeObject}. */
function describe(name: string, localized: Describable): string {
	const raw = localized?.description;
	if (raw) return ucfirst(cleanDescription(raw));
	return genericDescription(name);
}

// --- Auto-built descriptions for objects lacking a Wikidata short description ---
// Composed from exported physical/orbital data so the long tail (provisional
// asteroids, debris, uncatalogued moons) still gets a factual card line.

/** First 4-digit year in an ISO-ish date string. */
function yearOf(date: string | undefined): string | undefined {
	return date?.match(/\d{4}/)?.[0];
}

// Lead noun keyed on the coarse export `type`; small bodies refine via sbdb.class.
const TYPE_NOUN: Record<string, () => string> = {
	asteroid: m.seo_noun_asteroid,
	asteroid_main_belt: m.seo_noun_main_belt_asteroid,
	asteroid_inner: m.seo_noun_near_earth_asteroid,
	asteroid_trojan: m.seo_noun_jupiter_trojan,
	asteroid_centaur: m.seo_noun_centaur,
	asteroid_tno: m.seo_noun_trans_neptunian_object,
	comet: m.seo_noun_comet
};

// sbdb.class → noun, authoritative over `type` for the dynamical family.
const CLASS_NOUN: Record<string, () => string> = {
	MCA: m.seo_noun_mars_crossing_asteroid,
	IMB: m.seo_noun_main_belt_asteroid,
	MBA: m.seo_noun_main_belt_asteroid,
	OMB: m.seo_noun_main_belt_asteroid,
	APO: m.seo_noun_near_earth_asteroid,
	AMO: m.seo_noun_near_earth_asteroid,
	ATE: m.seo_noun_near_earth_asteroid,
	IEO: m.seo_noun_near_earth_asteroid,
	TJN: m.seo_noun_jupiter_trojan,
	CEN: m.seo_noun_centaur,
	TNO: m.seo_noun_trans_neptunian_object,
	COM: m.seo_noun_comet,
	HYA: m.seo_noun_comet,
	PAA: m.seo_noun_comet,
	JFC: m.seo_noun_comet,
	HTC: m.seo_noun_comet,
	ETC: m.seo_noun_comet,
	CTC: m.seo_noun_comet,
	PAR: m.seo_noun_comet,
	HYP: m.seo_noun_comet
};

const CELESTRAK_NOUN: Record<string, () => string> = {
	rocket_body: m.seo_noun_rocket_body,
	debris: m.seo_noun_orbital_debris,
	payload: m.seo_noun_satellite
};

// One clause for both units: the sentence says "across", the quantity says
// which unit it is across in, the way every panel does it.
function diameterClause(km: number): string {
	const q = km < 1 ? { value: km * 1000, unit: 'metre' } : { value: km, unit: 'kilometre' };
	return m.seo_attr_diameter({ value: formatQuantity(q, true) });
}

function joinNames(names: string[]): string {
	if (names.length === 1) return names[0];
	if (names.length === 2) return m.seo_discoverers_two({ a: names[0], b: names[1] });
	return m.seo_discoverers_many({ first: names[0] });
}

function smallBodyDescription(
	global: GlobalObjectData,
	localized: LocalizedObjectData | null
): string | null {
	const sbdb = global.sbdb;
	if (!sbdb) return null;
	const noun = (
		(sbdb.class && CLASS_NOUN[sbdb.class]) ||
		TYPE_NOUN[global.type] ||
		m.seo_noun_asteroid
	)();

	// first_obs is a discovery proxy; a real discoverer only comes from Wikidata.
	const year = yearOf(global.wikidata?.discovery_date?.[0] ?? sbdb.first_obs);
	const discoverers = (localized?.discoverers ?? []).map((d) => d.name).filter(Boolean);
	let lead = noun;
	if (year && discoverers.length)
		lead = m.seo_lead_discovered({ noun, year, who: joinNames(discoverers) });
	else if (year) lead = m.seo_lead_first_observed({ noun, year });

	const parts = [lead];
	const km = sbdb.diameter ?? (sbdb.H != null ? diameterKmFromH(sbdb.H) : undefined);
	if (km != null) parts.push(diameterClause(km));
	const spec = sbdb.spec_B ?? sbdb.spec_T;
	if (spec) parts.push(m.seo_attr_spectral_type({ spec }));
	return `${parts.join(', ')}.`;
}

function moonDescription(global: GlobalObjectData): string | null {
	if (global.type !== 'moon') return null;
	const parent = global.parent_name?.replace(/\s*Barycenter$/i, '').trim();
	const noun = parent ? m.seo_noun_moon_of({ parent }) : m.seo_noun_moon();
	return global.discovery_year != null
		? `${noun}, ${m.seo_attr_discovered({ year: String(global.discovery_year) })}.`
		: `${noun}.`;
}

function satelliteDescription(global: GlobalObjectData): string | null {
	const ct = global.celestrak;
	if (!ct) return null;
	const noun = (CELESTRAK_NOUN[ct.object_type ?? ''] ?? m.seo_noun_orbiting_object)();
	const year = yearOf(ct.launch_date);
	const parts = [year ? m.seo_lead_launched({ noun, year }) : noun];
	if (ct.orbit_center) parts.push(m.seo_attr_orbiting({ center: ucfirst(ct.orbit_center) }));
	return `${parts.join(', ')}.`;
}

function spacecraftDescription(global: GlobalObjectData): string | null {
	if (global.type !== 'spacecraft') return null;
	const noun = m.seo_noun_spacecraft();
	const year = yearOf(global.wikidata?.launch_date);
	const parts = [year ? m.seo_lead_launched({ noun, year }) : noun];
	const mission = global.part_of_mission?.name ?? global.mission?.name;
	if (mission) parts.push(m.seo_attr_part_of_mission({ mission }));
	return `${parts.join(', ')}.`;
}

function dynamicObjectDescription(
	global: GlobalObjectData,
	localized: LocalizedObjectData | null
): string | null {
	return (
		smallBodyDescription(global, localized) ??
		moonDescription(global) ??
		satelliteDescription(global) ??
		spacecraftDescription(global)
	);
}

/** Object description: Wikidata short description, else a factual line built from
 *  exported data, else the generic fallback. */
function describeObject(
	name: string,
	global: GlobalObjectData,
	localized: LocalizedObjectData | null
): string {
	const raw = localized?.description;
	if (raw) return ucfirst(cleanDescription(raw));
	const dynamic = dynamicObjectDescription(global, localized);
	return dynamic ? cleanDescription(dynamic) : genericDescription(name);
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
			? genericDescription(name)
			: 'Space Map, an interactive 3D map of the solar system.',
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
		describeObject(name, global, localized),
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

/** Meta for a surface-feature page (`/<type>/<id>/f/<featureId>/<name>`).
 *
 * Description order: the CC0 Wikidata short description, then the IAU
 * name-origin blurb — public-domain gazetteer text, and the one line that
 * actually distinguishes one anonymous crater from the next. The Wikipedia
 * extract stays out for the licensing reason noted above. */
export async function loadFeatureSeo(
	bodyId: string,
	featureId: number,
	name: string,
	origin: string,
	path: string
): Promise<SeoMeta | null> {
	const base = absolutize(DATA_BASE, origin);
	const metaRes = await fetch(`${base}/v1/metadata.json`);
	if (!metaRes.ok) return null;
	const meta = (await metaRes.json()) as {
		feature_bundles?: Record<string, number>;
		versions?: Record<string, string>;
	};
	const bundles = meta.feature_bundles;
	if (!bundles) return null;
	const token = meta.versions?.nomenclature;

	const key = `${bodyId}:${featureId}`;
	const nGlobal = bundles.global ?? 0;
	const nLocalized = bundles[SSR_LANG] ?? 0;
	const [gBucket, lBucket] = await Promise.all([
		nGlobal ? hashBucket(key, nGlobal) : Promise.resolve(-1),
		nLocalized ? hashBucket(key, nLocalized) : Promise.resolve(-1)
	]);

	const [gBundle, lBundle] = await Promise.all([
		gBucket >= 0
			? fetchJsonGz(
					versioned(`${base}/v1/nomenclature/details/__global__/${gBucket}.json.gz`, token)
				)
			: Promise.resolve(null),
		lBucket >= 0
			? fetchJsonGz(
					versioned(`${base}/v1/nomenclature/details/${SSR_LANG}/${lBucket}.json.gz`, token)
				)
			: Promise.resolve(null)
	]);

	const global = (gBundle?.[key] as FeatureGlobalData | undefined) ?? null;
	const localized = (lBundle?.[key] as FeatureLocalizedData | undefined) ?? null;
	if (!global && !localized) return null;

	const description = localized?.description
		? ucfirst(cleanDescription(localized.description))
		: global?.origin
			? cleanDescription(ucfirst(global.origin.replace(/\.?$/, '.')))
			: genericDescription(name);
	const card = await resolveOgCard(global?.images, description, origin, meta.versions?.images);
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
	'lv-',
	'ft-'
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
	const lead = heroImage(global);
	const card = await resolveOgCard(
		lead ? [lead] : undefined,
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
