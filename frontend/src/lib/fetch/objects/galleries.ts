/**
 * The Images tab's shelves, in display order. A page's pictures come from
 * several selections, one per subject: the object's own (`images`), its ring
 * system (`ring_images`), and the pooled galleries the exporter attaches
 * (`galleries`). Assembles them into the ordered list the panel renders and
 * the `&gal=` URL indexes into.
 */

import type { Snippet } from 'svelte';
import * as m from '$lib/paraglide/messages.js';
import { imageLabel } from './images';
import type { ImageGalleryData, ObjectImage } from './object-data';

/** URL token for the subject's own pictures — the shelf that always leads. */
export const MAIN_GALLERY = 'main';
/** URL token for the ring-system shelf, linked from the Rings tab. */
export const RINGS_GALLERY = 'rings';
/** URL token for the atmosphere shelf, linked from the Structure tab. */
export const ATMOSPHERE_GALLERY = 'atmosphere';
/** URL token for the shelf pooled from the body's moons, linked from Members. */
export const MOONS_GALLERY = 'moons';
/** URL token for the shelf pooled from its named surface features. */
export const FEATURES_GALLERY = 'features';

export interface Gallery {
	/** Stable URL token: a fixed name, or a member's Object.id. */
	key: string;
	title: string;
	images: ObjectImage[];
	/** Object.id the whole shelf is about, linked under its title. */
	subjectId?: string;
}

/**
 * Where a shelf, or a picture inside one, leads: the object it is about, or
 * the tab on this page covering the same subject. Resolved by the drawer —
 * only it knows the host body, tabs and localized names — keeping the
 * gallery components unaware of routing.
 */
export interface ShelfLink {
	/** Where it lands — what the jump changes. */
	label: string;
	/** What the jump keeps: the tab reached on another object's shelf, the
	 *  object itself on a shelf leading to another of its tabs. */
	kind: string;
	/** Absent only when there is no appState to serialize against. */
	href?: string;
	open: () => void;
	/** The destination's own picture, for the tile in the panel. Awaited there;
	 *  the viewer's caption renders the link as text and ignores it. */
	hero?: string | Promise<string | undefined>;
	/** Backdrop drawn instead of any photograph — for a subject whose pictures
	 *  are the shelf itself, where a portrait would only repeat it. */
	background?: Snippet;
}

/** How many pictures the page holds, across every shelf. Deduped by
 *  filename — the ring selection can repeat one of the object's own. */
export function imageCount(galleries: Gallery[]): number {
	const files = new Set<string>();
	for (const gallery of galleries) {
		for (const image of gallery.images) files.add(image.file);
	}
	return files.size;
}

/** The bundle fields a gallery list is assembled from — object or group. */
export interface GallerySource {
	images?: ObjectImage[];
	ring_images?: ObjectImage[];
	galleries?: ImageGalleryData[];
}

/** Titles for the shelves the exporter names by kind rather than by subject:
 *  the body's own aspects first, then the shelves about other things. */
const POOLED_TITLES: Record<string, () => string> = {
	[ATMOSPHERE_GALLERY]: m.atmosphere,
	interior: m.interior,
	[FEATURES_GALLERY]: m.features_section,
	[MOONS_GALLERY]: m.moons_section
};

/** Shelf order mirroring the drawer's tab bar: the object's own pictures
 *  lead, then one shelf per aspect. A shelf naming a subject rather than an
 *  aspect (a collection's members) has no tab to follow and trails behind. */
const SHELF_ORDER = [
	MAIN_GALLERY,
	FEATURES_GALLERY,
	ATMOSPHERE_GALLERY,
	'interior',
	RINGS_GALLERY,
	MOONS_GALLERY
];

function shelfRank(key: string): number {
	const rank = SHELF_ORDER.indexOf(key);
	return rank === -1 ? SHELF_ORDER.length : rank;
}

/**
 * Assemble the shelves for one page. `subjectName` resolves a pooled entry's
 * subject (an Object.id, or an IAU feature id) to its localized name — the
 * caller owns that, since the names ride in the localized bundle.
 */
export function buildGalleries(
	source: GallerySource | undefined,
	displayName: string,
	subjectName?: (subject: string) => string | undefined
): Gallery[] {
	if (!source) return [];
	const out: Gallery[] = [];
	if (source.images?.length) {
		out.push({ key: MAIN_GALLERY, title: displayName, images: source.images });
	}
	if (source.ring_images?.length) {
		out.push({ key: RINGS_GALLERY, title: m.tab_rings(), images: source.ring_images });
	}
	for (const gallery of source.galleries ?? []) {
		if (!gallery.images?.length) continue;
		const pooled = POOLED_TITLES[gallery.key];
		const named = gallery.subject ? subjectName?.(gallery.subject) : undefined;
		out.push({
			key: gallery.key,
			title: pooled ? pooled() : (named ?? gallery.key),
			images: gallery.images,
			subjectId: gallery.subject
		});
	}
	// Stable: the member shelves all rank the same and keep the order they came in.
	return out.sort((a, b) => shelfRank(a.key) - shelfRank(b.key));
}

/**
 * What a tile is captioned with, best first: the reading-language title, the
 * exporter's base-language one, the subject it's a picture of (a pooled
 * shelf's subject often says more than the picture's own name), then the
 * Commons filename.
 */
export function imageTitle(
	image: ObjectImage,
	localized?: Record<string, string>,
	subjectName?: (subject: string) => string | undefined
): string {
	const subject = image.subject === undefined ? undefined : subjectName?.(String(image.subject));
	return localized?.[image.file] ?? image.title ?? subject ?? imageLabel(image.file);
}

/** The shelf a `&gal=` token names, or undefined when it names none. */
export function findGallery(galleries: Gallery[], key: string | null): Gallery | undefined {
	if (key === null) return undefined;
	return galleries.find((gallery) => gallery.key === key);
}
