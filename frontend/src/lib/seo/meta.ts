/**
 * Server-side SEO meta for a content page.
 *
 * Runs only during SSR (crawlers, first paint) — see the `browser` guard in the
 * page loads. Shares the bundle-pair descriptors and loader with the client but
 * injects its own fetcher: the client fetch layer leans on module-singleton
 * caches, unsuited to a per-request server load.
 *
 * Fetches use the global `fetch` against an absolute URL, NOT the load's
 * `event.fetch`: in dev the data path (`/data/...`) collides with the
 * `[type]/[id]` route, and event.fetch dispatches it to the router (returning
 * HTML) instead of the vite proxy. A real network request to the origin hits
 * the proxy in dev and the CDN in prod.
 *
 * A page of the sitemap reads its record from the site's own static assets
 * instead: one file of a few KB in place of buckets of a few MB, whose parsing
 * was most of the Worker's CPU time (`scripts/seo-pages.mjs`).
 *
 * Nothing here comes from the name in the request path: a subject the export
 * does not hold is a 404, and its name is the export's, in the language of the
 * request. The canonical link is built from that name too, so a made-up URL
 * cannot put its own words on this site.
 */

import { error } from '@sveltejs/kit';
import * as m from '$lib/paraglide/messages.js';
import { dominantPlanetId } from '$lib/constants';
import { getLocale } from '$lib/host';
import { dataBase, imagesBase } from '$lib/fetch/data-base';
import { extractEmbeddedImageMetadata, smallestRasterVariant } from '$lib/fetch/objects/images';
import {
	FEATURE_BUNDLES,
	GROUP_BUNDLES,
	loadBundlePair,
	OBJECT_BUNDLES,
	type BundleMetadata,
	type BundlePair,
	type BundlePairDescriptor
} from '$lib/fetch/bundle-pair';
import { heroImage } from '$lib/fetch/objects/galleries';
import { diameterKmFromH } from '$lib/math/h-magnitude';
import { formatKm } from '$lib/format/distance';
import type {
	EntityRef,
	GlobalObjectData,
	LocalizedObjectData,
	ObjectImage
} from '$lib/fetch/objects/object-data';
import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
import {
	featureBucketKey,
	type FeatureGlobalData,
	type FeatureLocalizedData
} from '$lib/fetch/nomenclature/details';
import { nameFeatures } from '$lib/fetch/nomenclature/fetch';
import { parseNomenclature } from '$lib/fetch/nomenclature/parse';
import { gunzip, gunzipJson } from '$lib/fetch/gz';
import { bodyHref, featureHref, groupHref } from '$lib/state/page-href';
import { groupPageName, objectPageName } from '$lib/state/page-name';
import { Container } from '$lib/fetch/extrasolar/container';
import {
	EXTRASOLAR_FORMAT,
	ExtrasolarStaleError,
	extrasolarAllowed,
	extrasolarBase,
	type ExtrasolarMetadata
} from '$lib/fetch/extrasolar/files';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { ExtrasolarLookup } from '$lib/fetch/extrasolar/lookup';

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

/** What this file reads of an image. */
type SeoImage = Pick<ObjectImage, 'file' | 'kind' | 'attr' | 'variants'>;

// What this file reads of each bundle entry. A page record carries these
// fields alone, so `export/seo_pages.py` keeps the same lists.
type SeoObjectGlobal = Pick<
	GlobalObjectData,
	'name' | 'type' | 'parent_name' | 'discovery_year'
> & {
	images?: SeoImage[];
	sbdb?: Pick<
		NonNullable<GlobalObjectData['sbdb']>,
		'class' | 'first_obs' | 'diameter' | 'H' | 'spec_B' | 'spec_T'
	>;
	wikidata?: Pick<NonNullable<GlobalObjectData['wikidata']>, 'discovery_date' | 'launch_date'>;
	celestrak?: Pick<
		NonNullable<GlobalObjectData['celestrak']>,
		'object_type' | 'launch_date' | 'orbit_center'
	>;
	part_of_mission?: Pick<NonNullable<GlobalObjectData['part_of_mission']>, 'name'>;
	mission?: Pick<NonNullable<GlobalObjectData['mission']>, 'name'>;
};
type SeoObjectLocalized = Pick<LocalizedObjectData, 'name' | 'description'> & {
	discoverers?: Pick<EntityRef, 'name'>[];
};
type SeoGroupGlobal = { images?: SeoImage[]; galleries?: { images?: SeoImage[] }[] };
type SeoGroupLocalized = Pick<LocalizedGroupData, 'name' | 'description'>;
type SeoFeatureGlobal = Pick<FeatureGlobalData, 'origin'> & { images?: SeoImage[] };
type SeoFeatureLocalized = Pick<FeatureLocalizedData, 'description'>;

/** The credit metadata an image embeds. */
type ImageCreditMeta = { license?: { name?: string }; artist?: string | Record<string, string> };

/**
 * A page's record, which the build writes into the site's static assets for
 * each page of the sitemap. Any other page reads the bundles.
 */
interface SeoPage<G, L> {
	/** `images` version token of the export the record comes from. */
	v?: string;
	global: G | null;
	localized: Record<string, L>;
	/** Of the card images that need a credit, by file. */
	credits: Record<string, ImageCreditMeta>;
	/** Features only: the page's name, by language. */
	names?: Record<string, string>;
}

/** Reads a file of the site's static assets; null where the platform has none. */
let readAsset: ((path: string) => Promise<Response>) | null = null;

/** Point the lookups at the site's static assets, which hold the page records. */
export function configureSeoPages(read: ((path: string) => Promise<Response>) | null): void {
	readAsset = read;
}

async function readSeoPage<G, L>(key: string): Promise<SeoPage<G, L> | null> {
	if (!readAsset) return null;
	const res = await readAsset(`/_seo/${key}.json`);
	return res.ok ? ((await res.json()) as SeoPage<G, L>) : null;
}

/** Where a card image resolves: its URL, and its credit when it needs one. */
interface CardSource {
	/** The request the meta is for. */
	url: URL;
	lang: string;
	/** `images` version token. */
	imagesVersion: string | undefined;
	/** Null when the credit cannot be read. */
	credit: (image: SeoImage) => Promise<string | null>;
}

/** A page's bundle entries, and where its card image resolves. */
interface SeoSubject<G, L> extends BundlePair<G, L> {
	cards: CardSource;
}

function pageSubject<G, L>(page: SeoPage<G, L>, url: URL): SeoSubject<G, L> {
	const lang = getLocale();
	return {
		global: page.global,
		localized: page.localized[lang] ?? null,
		cards: {
			url,
			lang,
			imagesVersion: page.v,
			credit: async (image) => {
				const meta = page.credits[image.file];
				return meta ? buildCredit(meta, lang) : null;
			}
		}
	};
}

// OG images want ~1200px; prefer the medium bucket, fall back either way.
const OG_LABELS = ['m', 'xl', 's'] as const;

const DESCRIPTION_MAX = 200;

/** Longest wait for all the files of one page: a slow origin costs the page
 *  its meta, not its response. */
const LOOKUP_TIMEOUT_MS = 5_000;

/** The export as one page lookup reads it. */
interface SeoExport {
	/** The request the lookup is for. */
	url: URL;
	/** Absolute root of the data. */
	base: string;
	meta: BundleMetadata;
	/** Language of the request, as `hooks.server.ts` resolved it. A crawler
	 *  that states none reads English. */
	lang: string;
	/** Ends every fetch of the lookup at its one deadline. */
	signal: AbortSignal;
}

/** One file of the export. Null when the export does not have it; throws when
 *  it cannot be read, which says nothing about what the export holds. */
async function fetchExport(url: string, signal: AbortSignal): Promise<Response | null> {
	const res = await fetch(url, { signal });
	if (res.status === 404) return null;
	if (!res.ok) throw new Error(`${url} returned ${res.status} ${res.statusText}`);
	return res;
}

/** Absolute for a cross-origin CDN base; else resolved against the request. */
function absolutize(url: string, origin: string): string {
	return /^https?:\/\//i.test(url) ? url : `${origin}${url}`;
}

/** The absolute address of an app path. On the server, `$app/paths` gives a
 *  path relative to the request. */
function absoluteHref(href: string, url: URL): string {
	return new URL(href, url).href;
}

async function openExport(url: URL): Promise<SeoExport> {
	const signal = AbortSignal.timeout(LOOKUP_TIMEOUT_MS);
	const base = absolutize(dataBase(), url.origin);
	const res = await fetchExport(`${base}/v1/metadata.json`, signal);
	if (!res) throw new Error(`${base}/v1/metadata.json is missing`);
	return { url, base, meta: (await res.json()) as BundleMetadata, lang: getLocale(), signal };
}

function exportCards(exp: SeoExport): CardSource {
	return {
		url: exp.url,
		lang: exp.lang,
		imagesVersion: exp.meta.versions?.images,
		credit: (image) => fetchImageCredit(image, exp)
	};
}

function versioned(url: string, token: string | undefined): string {
	return token ? `${url}?v=${token}` : url;
}

interface OgPick {
	url: string;
	image: SeoImage;
	attr: 'free' | 'credit';
}

// Longest artist string inlined into a card credit before we truncate it.
const CREDIT_ARTIST_MAX = 60;

// Prefer attribution-free images; fall back to a credit-tier image, which the
// caller must attribute in the description. `other` (uncreditable) is skipped.
// Keeps ingest rank order; prefers photo over logo.
function pickOgImage(images: SeoImage[] | undefined, cards: CardSource): OgPick | undefined {
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
			url: absolutize(versioned(`${imagesBase()}${path}`, cards.imagesVersion), cards.url.origin),
			image: img,
			attr: img.attr
		};
	}
	return undefined;
}

function pickLocale(
	v: string | Record<string, string> | undefined,
	lang: string
): string | undefined {
	if (!v || typeof v === 'string') return v || undefined;
	return v[lang] ?? v.en ?? Object.values(v)[0];
}

/** Front-loadable credit for a `credit`-tier card image, or null when the
 *  author is missing — a license name alone can't attribute it. */
function buildCredit(meta: ImageCreditMeta, lang: string): string | null {
	const license = meta.license?.name;
	const artistRaw = pickLocale(meta.artist, lang);
	if (!license || !artistRaw) return null;
	const artist = truncate(stripHtml(artistRaw), CREDIT_ARTIST_MAX);
	return artist ? `Image: ${artist} (${license})` : null;
}

/** Fetch the chosen image's metadata and build its credit line.
 *
 * Metadata is embedded in the variants' EXIF; the imported helpers are pure
 * functions, so no client cache is touched. The sidecar fallback covers bundles
 * that couldn't embed. */
async function fetchImageCredit(image: SeoImage, exp: SeoExport): Promise<string | null> {
	const base = `${imagesBase()}/v1/images/${encodeURIComponent(image.file)}`;
	const file = (name: string) =>
		fetchExport(
			absolutize(versioned(`${base}/${name}`, exp.meta.versions?.images), exp.url.origin),
			exp.signal
		);
	const label = smallestRasterVariant(image.variants);
	if (label) {
		const res = await file(`${label}.${image.variants[label]}`);
		if (res) {
			const meta = extractEmbeddedImageMetadata(new Uint8Array(await res.arrayBuffer()));
			if (meta) return buildCredit(meta, exp.lang);
		}
	}
	const sidecar = await file('sidecar.json.gz');
	return sidecar ? buildCredit(await gunzipJson(sidecar), exp.lang) : null;
}

/** Resolve the card image + description together: a `credit`-tier image is only
 *  used when we can front-load its attribution; otherwise it's dropped so the
 *  card degrades to no image rather than an uncredited one. */
async function resolveOgCard(
	images: SeoImage[] | undefined,
	baseDescription: string,
	cards: CardSource
): Promise<{ image?: string; description: string }> {
	const pick = pickOgImage(images, cards);
	if (!pick) return { description: baseDescription };
	if (pick.attr === 'free') return { image: pick.url, description: baseDescription };
	// An image whose credit cannot be read is one that cannot be credited.
	const credit = await cards.credit(pick.image).catch(() => null);
	if (!credit) return { description: baseDescription };
	return { image: pick.url, description: `${credit}. ${baseDescription}` };
}

// A single pass leaves a tag behind whenever one was nested inside another
// ("<<b>i>" collapses to "<i>"), so strip to a fixpoint.
function stripHtml(raw: string): string {
	let out = raw;
	let prev: string;
	do {
		prev = out;
		out = out.replace(/<[^>]*>/g, '');
	} while (out !== prev);
	return out.replace(/\s+/g, ' ').trim();
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
	return m.seo_attr_diameter({ value: formatKm(km) });
}

function joinNames(names: string[]): string {
	if (names.length === 1) return names[0];
	if (names.length === 2) return m.seo_discoverers_two({ a: names[0], b: names[1] });
	return m.seo_discoverers_many({ first: names[0] });
}

function smallBodyDescription(
	global: SeoObjectGlobal,
	localized: SeoObjectLocalized | null
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

function moonDescription(global: SeoObjectGlobal): string | null {
	if (global.type !== 'moon') return null;
	const parent = global.parent_name?.replace(/\s*Barycenter$/i, '').trim();
	const noun = parent ? m.seo_noun_moon_of({ parent }) : m.seo_noun_moon();
	return global.discovery_year != null
		? `${noun}, ${m.seo_attr_discovered({ year: String(global.discovery_year) })}.`
		: `${noun}.`;
}

function satelliteDescription(global: SeoObjectGlobal): string | null {
	const ct = global.celestrak;
	if (!ct) return null;
	const noun = (CELESTRAK_NOUN[ct.object_type ?? ''] ?? m.seo_noun_orbiting_object)();
	const year = yearOf(ct.launch_date);
	const parts = [year ? m.seo_lead_launched({ noun, year }) : noun];
	if (ct.orbit_center) parts.push(m.seo_attr_orbiting({ center: ucfirst(ct.orbit_center) }));
	return `${parts.join(', ')}.`;
}

function spacecraftDescription(global: SeoObjectGlobal): string | null {
	if (global.type !== 'spacecraft') return null;
	const noun = m.seo_noun_spacecraft();
	const year = yearOf(global.wikidata?.launch_date);
	const parts = [year ? m.seo_lead_launched({ noun, year }) : noun];
	const mission = global.part_of_mission?.name ?? global.mission?.name;
	if (mission) parts.push(m.seo_attr_part_of_mission({ mission }));
	return `${parts.join(', ')}.`;
}

function dynamicObjectDescription(
	global: SeoObjectGlobal,
	localized: SeoObjectLocalized | null
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
	global: SeoObjectGlobal,
	localized: SeoObjectLocalized | null
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

/** Meta for a page with no subject of its own to describe: a title and
 *  canonical still make it shareable. `href` is the page's app path. */
export function minimalSeo(url: URL, href: string): SeoMeta {
	return {
		title: pageTitle(''),
		description: 'Space Map, an interactive 3D map of the solar system.',
		canonical: absoluteHref(href, url),
		ogType: 'website'
	};
}

/**
 * Meta for a page of the catalogue, from one of the loaders below. Answers
 * 404 when the export does not hold the subject. When the export cannot be
 * read the page opens all the same, on bare meta at `href`, its path with no
 * name: the app reports its own load, and the reader may reach the data where
 * the server did not.
 */
export async function catalogueSeo(
	lookup: Promise<SeoMeta | null>,
	url: URL,
	href: string
): Promise<SeoMeta> {
	let seo: SeoMeta | null;
	try {
		seo = await lookup;
	} catch (e) {
		console.warn(`[seo] ${url.pathname}: export not readable, bare meta:`, e);
		return minimalSeo(url, href);
	}
	if (!seo) error(404, 'Not found');
	return seo;
}

/**
 * Both bundles holding `key`, per request: no shared cache.
 *
 * Metadata counts the buckets, so one that is not there is an export in the
 * middle of an upload. It throws: only a bucket that was read can say that a
 * key is not in it.
 */
function loadSeoPair<G, L>(
	exp: SeoExport,
	desc: BundlePairDescriptor,
	key: string
): Promise<BundlePair<G, L>> {
	return loadBundlePair<G, L>(desc, key, {
		meta: exp.meta,
		lang: exp.lang,
		fetchBundle: async (path, versionClass) => {
			const token = versionClass ? exp.meta.versions?.[versionClass] : undefined;
			const url = versioned(`${exp.base}${path}`, token);
			const res = await fetchExport(url, exp.signal);
			if (!res) throw new Error(`${url} is missing`);
			return gunzipJson(res);
		}
	});
}

type ObjectPair = BundlePair<GlobalObjectData, LocalizedObjectData>;

function loadObjectPair(exp: SeoExport, fileId: string): Promise<ObjectPair> {
	return loadSeoPair<GlobalObjectData, LocalizedObjectData>(exp, OBJECT_BUNDLES, fileId);
}

/** An object's subject from the bundles, with the pair of its primary when it
 *  is a planetary barycenter: that page is named off its primary. */
async function exportObject(
	fileId: string,
	url: URL
): Promise<[SeoSubject<GlobalObjectData, LocalizedObjectData>, ObjectPair | null]> {
	const exp = await openExport(url);
	const own = await loadObjectPair(exp, fileId);
	const planetId = dominantPlanetId(fileId);
	const primary = own.global && planetId ? await loadObjectPair(exp, planetId) : null;
	return [{ ...own, cards: exportCards(exp) }, primary];
}

/** Build one object's meta. Null when the export holds no such object. */
export async function loadObjectSeo(fileId: string, url: URL): Promise<SeoMeta | null> {
	const page = await readSeoPage<SeoObjectGlobal, SeoObjectLocalized>(`o/${fileId}`);
	// No barycenter has a record: the sitemap lists none.
	const [own, primary]: [SeoSubject<SeoObjectGlobal, SeoObjectLocalized>, ObjectPair | null] = page
		? [pageSubject(page, url), null]
		: await exportObject(fileId, url);
	const { global, localized } = own;
	// An object with no global entry is unknown, whatever a stray localized
	// entry says.
	if (!global) return null;

	const name = objectPageName(fileId, own, primary);
	const card = await resolveOgCard(
		global.images,
		describeObject(name, global, localized),
		own.cards
	);
	return {
		title: pageTitle(name),
		description: card.description,
		canonical: absoluteHref(bodyHref(fileId, name), url),
		image: card.image,
		ogType: 'article'
	};
}

/** The name the body's gazetteer gives the feature, or null when it lists no
 *  such feature. The detail bundles carry no name. */
async function featureName(
	exp: SeoExport,
	bodyId: string,
	featureId: number
): Promise<string | null> {
	const file = (path: string) =>
		fetchExport(
			versioned(`${exp.base}/v1/nomenclature/${path}`, exp.meta.versions?.nomenclature),
			exp.signal
		);
	const [positions, labels] = await Promise.all([
		file(`positions/${bodyId}.bin.gz`),
		file(`labels/${exp.lang}/${bodyId}.txt.gz`)
	]);
	if (!positions) return null;
	const features = nameFeatures(
		parseNomenclature(await gunzip(positions).arrayBuffer()),
		labels ? await gunzip(labels).text() : ''
	);
	return features.find((f) => f.featureId === featureId)?.name ?? null;
}

/** A feature's subject and name from the bundles and the gazetteer. */
async function exportFeature(
	bodyId: string,
	featureId: number,
	url: URL
): Promise<[SeoSubject<FeatureGlobalData, FeatureLocalizedData>, string | null]> {
	const exp = await openExport(url);
	const [pair, name] = await Promise.all([
		loadSeoPair<FeatureGlobalData, FeatureLocalizedData>(
			exp,
			FEATURE_BUNDLES,
			featureBucketKey(bodyId, featureId)
		),
		featureName(exp, bodyId, featureId)
	]);
	return [{ ...pair, cards: exportCards(exp) }, name];
}

/** Meta for a surface-feature page (`/<type>/<id>/f/<featureId>/<name>`).
 *  Null when the body has no such feature.
 *
 * Description order: the CC0 Wikidata short description, then the IAU
 * name-origin blurb — public-domain gazetteer text, and the one line that
 * actually distinguishes one anonymous crater from the next. The Wikipedia
 * extract stays out for the licensing reason noted above. */
export async function loadFeatureSeo(
	bodyId: string,
	featureId: number,
	url: URL
): Promise<SeoMeta | null> {
	const page = await readSeoPage<SeoFeatureGlobal, SeoFeatureLocalized>(`f/${bodyId}/${featureId}`);
	const [{ global, localized, cards }, name]: [
		SeoSubject<SeoFeatureGlobal, SeoFeatureLocalized>,
		string | null
	] = page
		? [pageSubject(page, url), page.names?.[getLocale()] ?? null]
		: await exportFeature(bodyId, featureId, url);
	if (name === null) {
		// In the bundles and not in the gazetteer: an export in the middle of an
		// upload, not an unknown feature.
		if (global) throw new Error(`no gazetteer entry for ${bodyId}:${featureId}`);
		return null;
	}

	const description = localized?.description
		? ucfirst(cleanDescription(localized.description))
		: global?.origin
			? cleanDescription(ucfirst(global.origin.replace(/\.?$/, '.')))
			: genericDescription(name);
	const card = await resolveOgCard(global?.images, description, cards);
	return {
		title: pageTitle(name),
		description: card.description,
		canonical: absoluteHref(featureHref(bodyId, featureId, name), url),
		image: card.image,
		ogType: 'article'
	};
}

async function exportGroup(
	slug: string,
	url: URL
): Promise<SeoSubject<GlobalGroupData, LocalizedGroupData>> {
	const exp = await openExport(url);
	const pair = await loadSeoPair<GlobalGroupData, LocalizedGroupData>(exp, GROUP_BUNDLES, slug);
	return { ...pair, cards: exportCards(exp) };
}

/** Meta for a /g/<slug> collection page, or null when the export holds no such
 *  collection. The display name lives in the localized bundle; the global
 *  bundle carries images. Group bundles are unversioned. */
export async function loadGroupSeo(slug: string, url: URL): Promise<SeoMeta | null> {
	const page = await readSeoPage<SeoGroupGlobal, SeoGroupLocalized>(`g/${slug}`);
	const { global, localized, cards }: SeoSubject<SeoGroupGlobal, SeoGroupLocalized> = page
		? pageSubject(page, url)
		: await exportGroup(slug, url);
	if (!global && !localized) return null;

	const name = groupPageName(slug, localized?.name);
	const lead = heroImage(global);
	const card = await resolveOgCard(lead ? [lead] : undefined, describe(name, localized), cards);
	return {
		title: pageTitle(name),
		description: card.description,
		canonical: absoluteHref(groupHref(slug, name), url),
		image: card.image,
		ogType: 'website'
	};
}

/** What a star page's server render is: its meta, or where its alias goes. */
export type StarPage = { kind: 'page'; seo: SeoMeta } | { kind: 'alias'; location: string };

/**
 * The extrasolar export as one request reads it, through the same lookup as
 * the client: its own caches, and absolute URLs for the reason given at the
 * top of this file. A file from another export throws, as a missing one does:
 * neither says what the export holds.
 */
function requestLookup(url: URL): ExtrasolarLookup {
	const signal = AbortSignal.timeout(LOOKUP_TIMEOUT_MS);
	const base = `${absolutize(extrasolarBase(), url.origin)}/v1/x`;
	let metadata: Promise<ExtrasolarMetadata> | null = null;
	return new ExtrasolarLookup(
		{
			metadata: () =>
				(metadata ??= (async () => {
					const res = await fetchExport(`${base}/metadata.json`, signal);
					if (!res) throw new Error(`${base}/metadata.json is missing`);
					const meta = (await res.json()) as ExtrasolarMetadata;
					if (meta.format !== EXTRASOLAR_FORMAT)
						throw new Error(`extrasolar format ${meta.format}`);
					return meta;
				})()),
			file: async (path, token) => {
				const res = await fetchExport(`${base}/${path}?v=${token}`, signal);
				if (!res) throw new Error(`${base}/${path} is missing`);
				const file = new Container(await gunzip(res).arrayBuffer());
				if (file.token !== token) throw new ExtrasolarStaleError(path, file.token, token);
				return file;
			},
			allowed: extrasolarAllowed
		},
		{ tiles: 4, results: 4 }
	);
}

function starDescription(name: string): string {
	return m.seo_star_description({ name });
}

/**
 * A star page's meta from its Metadata row and its object entry, or the page
 * its alias goes to. Null when the export has no live row for the ID: a 404.
 * Throws when the extrasolar export cannot be read. Without the object bundles
 * the Metadata row alone gives the meta.
 */
export async function loadStarSeo(idText: string, url: URL): Promise<StarPage | null> {
	const lookup = requestLookup(url);
	const found = await lookup.live(idText, { data: false });
	if (found.kind !== 'live') return null;
	const { id, metadata } = found.record;
	const fileId = extrasolarObjectId(id);
	if (String(id) !== idText) {
		const to = new URL(absoluteHref(bodyHref(fileId, metadata.name ?? ''), url));
		return { kind: 'alias', location: `${to.pathname}${url.search}` };
	}
	// A star with an object entry takes its name and the Wikidata description
	// in the reader's language from it, as a body does.
	const localized = metadata.object
		? await exportObject(fileId, url).then(
				([own]) => own.localized,
				(e: unknown) => {
					console.warn(`[seo] ${url.pathname}: object bundles not readable:`, e);
					return null;
				}
			)
		: null;
	const name = localized?.name ?? metadata.name ?? '';
	return {
		kind: 'page',
		seo: {
			title: pageTitle(name),
			description: localized?.description
				? ucfirst(cleanDescription(localized.description))
				: starDescription(name),
			canonical: absoluteHref(bodyHref(fileId, name), url),
			ogType: 'article'
		}
	};
}
