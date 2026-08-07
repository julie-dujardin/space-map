import { describe, expect, it } from 'vitest';
import {
	buildGalleries,
	findGallery,
	imageCount,
	imageTitle,
	MAIN_GALLERY,
	RINGS_GALLERY
} from './galleries';
import type { ObjectImage } from './object-data';

function image(file: string, subject?: string | number): ObjectImage {
	return { file, source_url: `https://x/${file}`, kind: 'photo', variants: { s: 'webp' }, subject };
}

describe('buildGalleries', () => {
	it('returns nothing for a bundle with no pictures', () => {
		expect(buildGalleries(undefined, 'Saturn')).toEqual([]);
		expect(buildGalleries({}, 'Saturn')).toEqual([]);
	});

	it('leads with the object itself, named after it', () => {
		const galleries = buildGalleries({ images: [image('a.jpg')] }, 'Saturn');
		expect(galleries).toHaveLength(1);
		expect(galleries[0].key).toBe(MAIN_GALLERY);
		expect(galleries[0].title).toBe('Saturn');
	});

	it('puts the ring pictures on their own shelf, behind the object', () => {
		const galleries = buildGalleries(
			{ images: [image('a.jpg')], ring_images: [image('r.jpg')] },
			'Saturn'
		);
		expect(galleries.map((g) => g.key)).toEqual([MAIN_GALLERY, RINGS_GALLERY]);
		expect(galleries[1].images).toHaveLength(1);
	});

	it('names a pooled shelf by its kind and keeps the exporter order', () => {
		const galleries = buildGalleries(
			{
				images: [image('a.jpg')],
				galleries: [
					{ key: 'features', images: [image('f.jpg', 14940)] },
					{ key: 'moons', images: [image('m.jpg', 'naif-502')] }
				]
			},
			'Jupiter'
		);
		expect(galleries.map((g) => g.key)).toEqual([MAIN_GALLERY, 'features', 'moons']);
		expect(galleries[1].title).not.toBe('features');
		expect(galleries[2].title).not.toBe('moons');
	});

	it("names a member's shelf after the member, and links to it", () => {
		const galleries = buildGalleries(
			{ galleries: [{ key: 'naif-502', subject: 'naif-502', images: [image('e.jpg')] }] },
			'Ring Systems',
			(subject) => (subject === 'naif-502' ? 'Europa' : undefined)
		);
		expect(galleries[0].title).toBe('Europa');
		expect(galleries[0].subjectId).toBe('naif-502');
	});

	// The localized bundle can lag the global one; an unnamed shelf still has
	// to render, and its key is the least-wrong thing to show.
	it('falls back to the key when the subject has no name yet', () => {
		const galleries = buildGalleries(
			{ galleries: [{ key: 'naif-502', subject: 'naif-502', images: [image('e.jpg')] }] },
			'Ring Systems'
		);
		expect(galleries[0].title).toBe('naif-502');
	});

	it('drops an empty shelf rather than rendering a heading over nothing', () => {
		const galleries = buildGalleries(
			{ images: [image('a.jpg')], galleries: [{ key: 'moons', images: [] }] },
			'Jupiter'
		);
		expect(galleries).toHaveLength(1);
	});
});

describe('imageTitle', () => {
	it('prefers the reading language over the exported base title', () => {
		const img = { ...image('a.jpg'), title: 'Jupiter in true color' };
		expect(imageTitle(img, { 'a.jpg': 'Jupiter en couleurs réelles' })).toBe(
			'Jupiter en couleurs réelles'
		);
	});

	it('falls back to the base title, then the subject, then the filename', () => {
		expect(imageTitle({ ...image('a.jpg'), title: 'Great Red Spot' })).toBe('Great Red Spot');
		expect(imageTitle(image('a.jpg', 'naif-502'), undefined, () => 'Europa')).toBe('Europa');
		expect(imageTitle(image('Jupiter_OPAL_2024.png'))).toBe('Jupiter OPAL 2024');
	});

	// A title says what the picture is; the subject only says whose shelf it is on.
	it('lets a picture with both keep its own title', () => {
		const img = { ...image('a.jpg', 'naif-502'), title: 'Europa transiting Jupiter' };
		expect(imageTitle(img, undefined, () => 'Europa')).toBe('Europa transiting Jupiter');
	});
});

describe('imageCount', () => {
	it('counts every shelf, not just the first', () => {
		const galleries = buildGalleries(
			{
				images: [image('a.jpg'), image('b.jpg')],
				ring_images: [image('r.jpg')],
				galleries: [{ key: 'moons', images: [image('m.jpg', 'naif-502')] }]
			},
			'Saturn'
		);
		expect(imageCount(galleries)).toBe(4);
	});

	// The exporter keeps pooled shelves clear of the object's own pictures, but
	// the ring selection can repeat one — counting it twice overstates the page.
	it('counts a picture on two shelves once', () => {
		const galleries = buildGalleries(
			{ images: [image('a.jpg')], ring_images: [image('a.jpg')] },
			'Saturn'
		);
		expect(imageCount(galleries)).toBe(1);
	});

	it('is zero for a page with no pictures', () => {
		expect(imageCount([])).toBe(0);
	});
});

describe('findGallery', () => {
	const galleries = buildGalleries({ images: [image('a.jpg')] }, 'Saturn');

	it('resolves a key to its shelf', () => {
		expect(findGallery(galleries, MAIN_GALLERY)?.key).toBe(MAIN_GALLERY);
	});

	// A stale or foreign `&gal=` must fall back to the index, not throw.
	it('returns nothing for an unknown key or none at all', () => {
		expect(findGallery(galleries, 'moons')).toBeUndefined();
		expect(findGallery(galleries, null)).toBeUndefined();
	});
});
