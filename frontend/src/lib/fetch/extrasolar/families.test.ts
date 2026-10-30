import { describe, expect, it } from 'vitest';
import { familiesOf, familyLinks, solarPlanetFamilyLinks } from './families';
import type { ExtrasolarFamily } from './files';

function family(slug: string, parents: string[], stars: number): ExtrasolarFamily {
	return { slug, wikidata: [], parents, published: stars, estimated: 0 };
}

const FAMILIES = [
	family('classification', [], 100),
	family('giant', ['classification'], 50),
	family('red-giant', ['giant'], 40),
	family('barium-star', ['classification'], 2),
	family('dwarf', ['classification'], 60),
	family('main-sequence', ['dwarf'], 55),
	family('g-type-main-sequence', ['main-sequence'], 20)
];

describe('familiesOf', () => {
	it('reads bit n as entry n', () => {
		expect(familiesOf(0b1010n, FAMILIES)).toEqual(['giant', 'barium-star']);
	});
});

describe('familyLinks', () => {
	it('keeps the families that contain none of the others', () => {
		const links = familyLinks(
			'star_family',
			['classification', 'dwarf', 'main-sequence', 'g-type-main-sequence'],
			[],
			FAMILIES
		);
		expect(links).toEqual([
			{ type: 'star_family', slug: 'star-g-type-main-sequence', estimated: false }
		]);
	});

	it('puts the published first, then the families with fewer stars', () => {
		const links = familyLinks(
			'star_family',
			['classification', 'giant', 'red-giant'],
			['barium-star', 'dwarf', 'main-sequence'],
			FAMILIES
		);
		expect(links.map((link) => link.slug)).toEqual([
			'star-red-giant',
			'star-barium-star',
			'star-main-sequence'
		]);
		expect(links.map((link) => link.estimated)).toEqual([false, true, true]);
	});

	it('keeps a published family that only an estimate refines', () => {
		const links = familyLinks(
			'star_family',
			['classification', 'dwarf', 'main-sequence'],
			['g-type-main-sequence'],
			FAMILIES
		);
		expect(links).toEqual([
			{ type: 'star_family', slug: 'star-main-sequence', estimated: false },
			{ type: 'star_family', slug: 'star-g-type-main-sequence', estimated: true }
		]);
	});

	it('links a planet to the planet- pages', () => {
		const links = familyLinks(
			'planet_family',
			['classification', 'giant'],
			['red-giant'],
			FAMILIES
		);
		expect(links).toEqual([
			{ type: 'planet_family', slug: 'planet-giant', estimated: false },
			{ type: 'planet_family', slug: 'planet-red-giant', estimated: true }
		]);
	});

	it('gives nothing without the tree', () => {
		const old = FAMILIES.map((entry) => ({ ...entry, parents: undefined }));
		expect(familyLinks('star_family', ['classification', 'giant'], [], old)).toEqual([]);
	});
});

describe('solarPlanetFamilyLinks', () => {
	const index = {
		'planet-terrestrial-planet': { type: 'planet_family', applies_to: 'planet', n: 1098 },
		'planet-goldilocks-planet': { type: 'planet_family', applies_to: 'planet', n: 217 }
	} as const;

	it('puts the family with fewer planets first', () => {
		const links = solarPlanetFamilyLinks(['terrestrial-planet', 'goldilocks-planet'], index);
		expect(links).toEqual([
			{ type: 'planet_family', slug: 'planet-goldilocks-planet', estimated: false },
			{ type: 'planet_family', slug: 'planet-terrestrial-planet', estimated: false }
		]);
	});

	it('leaves out a family with no page', () => {
		expect(solarPlanetFamilyLinks(['ice-giant'], index)).toEqual([]);
	});
});
