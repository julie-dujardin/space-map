import { describe, expect, it } from 'vitest';
import { familiesOf, starFamilyLinks } from './families';
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

describe('starFamilyLinks', () => {
	it('keeps the families that contain none of the others', () => {
		const links = starFamilyLinks(
			['classification', 'dwarf', 'main-sequence', 'g-type-main-sequence'],
			[],
			FAMILIES
		);
		expect(links).toEqual([{ slug: 'star-g-type-main-sequence', estimated: false }]);
	});

	it('puts the published first, then the families with fewer stars', () => {
		const links = starFamilyLinks(
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
		const links = starFamilyLinks(
			['classification', 'dwarf', 'main-sequence'],
			['g-type-main-sequence'],
			FAMILIES
		);
		expect(links).toEqual([
			{ slug: 'star-main-sequence', estimated: false },
			{ slug: 'star-g-type-main-sequence', estimated: true }
		]);
	});

	it('gives nothing without the tree', () => {
		const old = FAMILIES.map((entry) => ({ ...entry, parents: undefined }));
		expect(starFamilyLinks(['classification', 'giant'], [], old)).toEqual([]);
	});
});
