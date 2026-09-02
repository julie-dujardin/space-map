/**
 * A random place to go, drawn by walking the collection tree instead of the
 * catalogue.
 *
 * Drawing from the catalogue is drawing from the Main Belt: it holds 1.37 M of
 * the 1.59 M objects, so all but one draw in seven is an unnamed rock. The walk
 * descends one level at a time and picks uniformly among what the page holds,
 * so the belt is one choice among the fifteen asteroid zones rather than the
 * whole draw, and a moon, a comet and a crater each get a real share.
 *
 * The root's slots are the kinds of thing there are to see. The collection
 * pages are one of them — every /g page in the catalogue drawn flat, from the
 * Solar System itself down to a satellite operator — rather than a stop on the
 * way down, so reaching one doesn't depend on how deep it sits.
 *
 * Whatever comes up has to be somewhere: an object the scene can't place is
 * redrawn, so the reader never lands on a page with an empty sky beside it.
 *
 * Planets, dwarf planets and ringed bodies are not slots: the planets are the
 * one thing already on screen, and a dwarf planet still comes up through its
 * orbit zone. Their pages stay drawable as collections.
 */

import { resolve } from '$app/paths';
import { getLocale, type Locale } from '$lib/paraglide/runtime.js';
import {
	fetchGroupDetail,
	type ChildGroupEntry,
	type GroupDetailData
} from '$lib/fetch/groups/details';
import {
	categoryLabel,
	fetchGroupIndex,
	CAT_DEBRIS,
	CAT_DWARF_PLANETS,
	CAT_PLANETS,
	CAT_SATELLITE_SYSTEMS,
	CAT_RING_SYSTEMS,
	CAT_SATELLITES,
	CAT_SOLAR_SYSTEM,
	CAT_STRUCTURE_ACTIVITY
} from '$lib/fetch/groups/registry';
import { canBePlaced } from '$lib/fetch/objects/global-body';
import {
	fetchObjectDetail,
	memberEntryKey,
	type NotableMemberEntry
} from '$lib/fetch/objects/object-data';
import {
	isSearchEnabled,
	localizedName,
	searchGroupMembers,
	MAX_TOTAL_HITS,
	type MemberHit
} from '$lib/search/client';
import { UrlType, urlTypeFromId, urlTypeToIdPrefix } from './view';

/** Anything that can fill the sidebar: a collection page, a body, a landform. */
export type RandomTarget =
	| { kind: 'group'; slug: string; name: string }
	| { kind: 'object'; id: string; name: string }
	| { kind: 'feature'; bodyId: string; featureId: number; name: string };

/** The two Earth-orbiter collections hang off Earth rather than off the root,
 *  and the walk stops at a body — without these, half a million satellites
 *  would be undrawable. */
const EXTRA_ROOT_CHILDREN = [CAT_SATELLITES, CAT_DEBRIS];

/** Root slots that draw no bodies of their own.
 *
 *  Planets, systems and ring systems hold the same dozen bodies the map opens
 *  on; a dwarf planet is drawn as the small body it is, from its orbit zone.
 *  Structure & Activity holds nothing but collections, which have their own
 *  slot. All five pages stay reachable there. */
const NON_DRAWING_CATEGORIES: readonly string[] = [
	CAT_PLANETS,
	CAT_SATELLITE_SYSTEMS,
	CAT_DWARF_PLANETS,
	CAT_RING_SYSTEMS,
	CAT_STRUCTURE_ACTIVITY
];

/** The root slot standing for every collection page. Not a slug: no page
 *  collects the collections, so the draw reads the group index instead. */
const META_COLLECTIONS = 'collections';

/** Root → category → zone → constellation → member is four; the cap is what
 *  keeps a tree that ever points back at itself from spinning. */
const MAX_DEPTH = 6;

function randomIndex(n: number): number {
	return Math.floor(Math.random() * n);
}

interface Node {
	slug: string;
	name: string;
}

/** The child collections a page lists. */
function childNodes(children: ChildGroupEntry[] | undefined): Node[] {
	return (children ?? [])
		.filter((c) => c.primary_id)
		.map((c) => ({ slug: c.primary_id as string, name: c.name }));
}

/**
 * Draw a destination, keeping off ground just covered.
 *
 * The recently-drawn destinations are refused outright, and the categories the
 * last few draws went through are struck off the root before it picks — one
 * asteroid after another reads as a broken button even when each draw is honest.
 * If every attempt repeats something, the repeat is taken: going nowhere is
 * worse than going somewhere twice.
 */
export async function randomTarget(locale = getLocale()): Promise<RandomTarget | null> {
	const recent = readRecent();
	let drawn: Draw | null = null;
	for (let attempt = 0; attempt < DRAW_ATTEMPTS; attempt++) {
		drawn = await walk(locale, recent.categories);
		if (!drawn) return null;
		if (!recent.targets.includes(targetKey(drawn.target))) break;
	}
	if (drawn) rememberDraw(recent, drawn);
	return drawn?.target ?? null;
}

/** A destination and the root category it was reached through. */
interface Draw {
	target: RandomTarget;
	category: string;
}

/** The kinds of thing there are to see: the collections slot, then each root
 *  category that draws bodies of its own. */
async function rootSlots(locale: Locale): Promise<Node[]> {
	const detail = await fetchGroupDetail(CAT_SOLAR_SYSTEM, locale);
	const listed = childNodes(detail.localized?.child_groups).filter(
		(c) => !NON_DRAWING_CATEGORIES.includes(c.slug)
	);
	return [
		{ slug: META_COLLECTIONS, name: META_COLLECTIONS },
		...listed,
		...EXTRA_ROOT_CHILDREN.map((slug) => ({ slug, name: categoryLabel(slug) }))
	];
}

/** One draw: a root slot, then down from it. */
async function walk(locale: Locale, skipCategories: string[]): Promise<Draw | null> {
	let slots: Node[];
	try {
		slots = await rootSlots(locale);
	} catch (e) {
		console.warn('[random] the root is unreachable — nothing to draw.', e);
		return null;
	}
	// The categories just visited are struck off, never the levels below: the
	// repetition a reader notices is the kind of place, not the shelf it sat on.
	const fresh = slots.filter((s) => !skipCategories.includes(s.slug));
	const candidates = fresh.length > 0 ? fresh : slots;
	if (candidates.length === 0) return null;

	const slot = candidates[randomIndex(candidates.length)];
	if (slot.slug === META_COLLECTIONS) {
		const page = await randomCollection(locale);
		return page && { target: page, category: META_COLLECTIONS };
	}
	return descend(slot, locale);
}

/** Any collection page, drawn flat off the group index — a category, an orbit
 *  zone, a constellation, an operator, a launch site. Flat because the index is
 *  the list of pages there are; tiering it by kind would be a second opinion
 *  about which kind matters, which is what the tree already answers. */
async function randomCollection(locale: Locale): Promise<RandomTarget | null> {
	let slugs: string[];
	try {
		slugs = Object.keys(await fetchGroupIndex());
	} catch (e) {
		console.warn('[random] the group index is unreachable — no collection to draw.', e);
		return null;
	}
	if (slugs.length === 0) return null;
	const slug = slugs[randomIndex(slugs.length)];
	// The bundle carries the localized name; the slug is what a category falls
	// back to, and what an unnamed collection is called anyway.
	const detail = await fetchGroupDetail(slug, locale).catch(() => null);
	return { kind: 'group', slug, name: detail?.localized?.name ?? categoryLabel(slug) };
}

/** Down from one root category until the draw lands on a body or a landform.
 *  A collection at the end is the fallback for a category that lists nothing,
 *  not a destination the walk aims for. */
async function descend(start: Node, locale: Locale): Promise<Draw | null> {
	let node = start;
	for (let depth = 0; depth < MAX_DEPTH; depth++) {
		let detail: GroupDetailData;
		try {
			detail = await fetchGroupDetail(node.slug, locale);
		} catch (e) {
			console.warn(`[random] ${node.slug} unreachable — stopping the walk here.`, e);
			return here(node, start.slug);
		}

		const children = childNodes(detail.localized?.child_groups);
		if (children.length > 0) {
			node = children[randomIndex(children.length)];
			continue;
		}

		const member = await placeableMember(node.slug, detail, locale);
		if (!member) return here(node, start.slug);
		// An Earth-orbit zone lists the constellations that live in it; descend
		// into one rather than handing back a collection the reader picked past.
		if (member.kind !== 'group') return { target: member, category: start.slug };
		node = { slug: member.slug, name: member.name };
	}
	return here(node, start.slug);
}

/** The walk stopping where it stands. */
function here(node: Node, category: string): Draw {
	return { target: { kind: 'group', ...node }, category };
}

/** A member the map can show. A destination the scene can't place is a page
 *  with an empty sky next to it — most of the moons of asteroids were published
 *  without an orbit, and a decayed satellite has no elements left. Redrawing
 *  within the collection keeps the walk's shape: the reader still lands where
 *  the tree sent them, on something that is there. */
async function placeableMember(
	slug: string,
	detail: GroupDetailData,
	locale: Locale
): Promise<RandomTarget | null> {
	for (let attempt = 0; attempt < MEMBER_ATTEMPTS; attempt++) {
		const member = await randomMember(slug, detail, locale);
		if (!member || member.kind !== 'object') return member;
		const global = await fetchObjectDetail(member.id, false, locale)
			.then((d) => d.global)
			.catch(() => null);
		if (canBePlaced(member.id, global)) return member;
	}
	// Every draw came back unplaceable — a collection of nothing but decayed
	// debris is a real thing. Its page still has something to read.
	return null;
}

/** One member of a collection that lists no child collections. */
async function randomMember(
	slug: string,
	detail: GroupDetailData,
	locale: string
): Promise<RandomTarget | null> {
	// The index caps a result set at 1000 and ranks it notable-first, so the draw
	// is over members a reader can be shown something about. That cap is the
	// feature here, not a limitation: the tail is rocks with a number and nothing
	// else.
	const count = Math.min(detail.global?.member_count ?? 0, MAX_TOTAL_HITS);
	if (isSearchEnabled() && count > 0) {
		let page = await searchGroupMembers(slug, randomIndex(count), 1, locale);
		// The baked count outruns what the index holds for some collections, so an
		// overshooting offset comes back empty; the response's own total corrects it.
		if (page.hits.length === 0 && page.estimatedTotalHits > 0) {
			const offset = randomIndex(Math.min(page.estimatedTotalHits, MAX_TOTAL_HITS));
			page = await searchGroupMembers(slug, offset, 1, locale);
		}
		if (page.hits[0]) return targetOfHit(page.hits[0], locale);
	}
	// The baked top members: the whole membership for collections the index tags
	// nothing for (split-comet families), and the answer when search is dark.
	const notable = detail.global?.notable_members ?? [];
	if (notable.length === 0) return null;
	return targetOfEntry(notable[randomIndex(notable.length)], detail);
}

function targetOfHit(hit: MemberHit, locale: string): RandomTarget {
	const name = localizedName(hit, locale);
	if (hit.kind === 'group') return { kind: 'group', slug: hit.slug, name };
	if (hit.kind === 'feature')
		return { kind: 'feature', bodyId: hit.body_id, featureId: hit.feature_id, name };
	return { kind: 'object', id: hit.id, name };
}

function targetOfEntry(entry: NotableMemberEntry, detail: GroupDetailData): RandomTarget {
	const name = detail.localized?.notable_member_names?.[memberEntryKey(entry)] ?? entry.name;
	if (entry.group) return { kind: 'group', slug: entry.group, name };
	if (entry.feature_id != null && entry.id)
		return { kind: 'feature', bodyId: entry.id, featureId: entry.feature_id, name };
	return { kind: 'object', id: entry.id ?? '', name };
}

/**
 * What the last draws landed on, kept in localStorage so the pill and a
 * bookmarked `/random` share one history, and so a reload doesn't hand back
 * where the reader just was.
 */
interface RecentDraws {
	/** Destination keys, newest first. */
	targets: string[];
	/** Root categories, newest first. */
	categories: string[];
}

const RECENT_KEY = 'space-map-random-recent';
const RECENT_TARGETS = 100;
const RECENT_CATEGORIES = 3;

/** Draws inside one collection before the walk gives up on it and hands back
 *  the page itself. Half of the catalogued moons are moons of asteroids with no
 *  published orbit, so three tries hand the Moons page back one time in seven;
 *  five brings that under one in twenty, and only a collection that is genuinely
 *  all placeholders pays for all five. */
export const MEMBER_ATTEMPTS = 5;

/** Enough tries to get clear of the recent list wherever the tree is wide,
 *  and few enough that a reader who has seen a small collection out still gets
 *  an answer rather than a spinner. */
const DRAW_ATTEMPTS = 8;

/** What makes two draws the same place. */
function targetKey(target: RandomTarget): string {
	if (target.kind === 'group') return target.slug;
	if (target.kind === 'feature') return `${target.bodyId}:${target.featureId}`;
	return target.id;
}

function readRecent(): RecentDraws {
	if (typeof localStorage === 'undefined') return { targets: [], categories: [] };
	try {
		const raw = localStorage.getItem(RECENT_KEY);
		const parsed = raw ? (JSON.parse(raw) as Partial<RecentDraws>) : {};
		return {
			targets: Array.isArray(parsed.targets) ? parsed.targets : [],
			categories: Array.isArray(parsed.categories) ? parsed.categories : []
		};
	} catch {
		return { targets: [], categories: [] };
	}
}

function rememberDraw(recent: RecentDraws, draw: Draw): void {
	const key = targetKey(draw.target);
	const next: RecentDraws = {
		targets: [key, ...recent.targets.filter((t) => t !== key)].slice(0, RECENT_TARGETS),
		categories: [draw.category, ...recent.categories.filter((c) => c !== draw.category)].slice(
			0,
			RECENT_CATEGORIES
		)
	};
	if (typeof localStorage === 'undefined') return;
	try {
		localStorage.setItem(RECENT_KEY, JSON.stringify(next));
	} catch {
		// localStorage can throw in private-mode Safari — drop silently.
	}
}

/** The plain route path for a target — no `?at=` framing, the same as any
 *  fresh open. What `/random` redirects to. */
export function randomTargetPath(target: RandomTarget): string {
	if (target.kind === 'group') {
		return resolve('/[type]/[id]/[[name]]', {
			type: UrlType.Group,
			id: target.slug,
			name: encodeURIComponent(target.name)
		});
	}
	const bodyId = target.kind === 'feature' ? target.bodyId : target.id;
	const type = urlTypeFromId(bodyId);
	const id = bodyId.slice(`${urlTypeToIdPrefix(type)}-`.length);
	if (target.kind === 'feature') {
		return resolve('/[type]/[id]/f/[featureId]/[[name]]', {
			type,
			id,
			featureId: String(target.featureId),
			name: encodeURIComponent(target.name)
		});
	}
	return resolve('/[type]/[id]/[[name]]', { type, id, name: encodeURIComponent(target.name) });
}
