/**
 * The Images tab's shelves, in display order.
 *
 * A page's pictures come from several selections, one per subject: the object's
 * own (`images`), its ring system (`ring_images`), and the pooled galleries the
 * exporter attaches (`galleries` — its features, its moons, or one shelf per
 * member on a collection). This assembles them into the ordered list the panel
 * renders and the `&gal=` URL indexes into.
 */

import * as m from '$lib/paraglide/messages.js';
import { imageLabel } from './images';
import type { ImageGalleryData, ObjectImage } from './object-data';

/** URL token for the subject's own pictures — the shelf that always leads. */
export const MAIN_GALLERY = 'main';
/** URL token for the ring-system shelf, linked from the Rings tab. */
export const RINGS_GALLERY = 'rings';

export interface Gallery {
	/** Stable URL token: a fixed name, or a member's Object.id. */
	key: string;
	title: string;
	images: ObjectImage[];
	/** Object.id the whole shelf is about, linked under its title. */
	subjectId?: string;
}

/**
 * Where a shelf, or a picture inside one, leads: the object it is about, or the
 * tab on this page that covers the same subject. Resolved by the drawer — only
 * it knows the host body, which tabs exist, and the localized names — so the
 * gallery components stay unaware of routing.
 */
export interface ShelfLink {
	label: string;
	/** Absent only when there is no appState to serialize against. */
	href?: string;
	open: () => void;
}

/**
 * How many pictures the page holds in total, across every shelf.
 *
 * Deduped by filename: the exporter keeps the pooled shelves clear of the
 * object's own pictures, but the ring selection can repeat one of them.
 */
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
	atmosphere: m.atmosphere,
	interior: m.interior,
	features: m.features_section,
	moons: m.moons_section
};

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
	return out;
}

/**
 * What a tile is captioned with, best first: the picture's title in the reading
 * language, the exporter's base-language one, the subject it is a picture of
 * (in a pooled shelf, where the subject says more than the picture's own name),
 * and failing all of those the Commons filename.
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
