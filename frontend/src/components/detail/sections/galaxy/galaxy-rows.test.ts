import { describe, expect, it } from 'vitest';
import {
	ABOUT_KINDS,
	MILKY_WAY_COLUMNS,
	MILKY_WAY_ENTRY,
	galaxyRecord
} from '$lib/fetch/extrasolar/__fixtures__/galaxy';
import { catalogueCounts, galaxyRow } from '$lib/fetch/extrasolar/galaxies';
import {
	CAT_PLANETARY_SYSTEMS,
	CAT_SOLAR_SYSTEM,
	CAT_STARS,
	CAT_STAR_SYSTEMS
} from '$lib/fetch/groups/registry';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import type { StarSection } from '../star/star-rows';
import { HOME_GALAXY_TILES, galaxySections, galaxyStats, galaxyWorks } from './galaxy-rows';

/** The text without its bidi isolates and word joiners, with plain spaces. */
const CONTROLS = new RegExp('[\\u2060\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(CONTROLS, '').replace(NO_BREAK, ' ');

const row = () => galaxyRow(galaxyRecord());
const counts = () => catalogueCounts(ABOUT_KINDS);
const sections = () => galaxySections(row(), MILKY_WAY_ENTRY, counts());

/** The rows of a section as label, value and note. */
function rowsOf(all: StarSection[], key: string): [string, string, string?][] {
	const section = all.find((s) => s.key === key);
	return (section?.rows ?? []).map((r) => [r.label, plain(r.value), r.note]);
}

describe('the sections of a galaxy', () => {
	it('come in panel order, each under its title', () => {
		expect(sections().map((s) => [s.key, s.title])).toEqual([
			['classification', 'Classification'],
			['structure', 'Structure'],
			['mass', 'Mass'],
			['rotation', 'Rotation'],
			['population', 'Stars and planets'],
			['companions', 'Companions'],
			['position', 'Position'],
			['catalogue', 'In this catalogue']
		]);
	});

	it('show the Redshift row at the figures of its papers', () => {
		const all = sections();
		expect(rowsOf(all, 'classification')).toEqual([
			['Morphological type', 'SAB(rs)bc', undefined],
			['Age', '13 Ga', undefined]
		]);
		expect(rowsOf(all, 'mass')).toEqual([
			['Total mass', '1.08×10¹² M☉ (0.94–1.28×10¹² M☉)', undefined],
			['Stellar mass', '5.04×10¹⁰ M☉ (4.52–5.47×10¹⁰ M☉)', undefined],
			['Stellar halo mass', '(1.4 ± 0.4)×10⁹ M☉', undefined],
			['Central black hole mass', '(4.297 ± 0.012)×10⁶ M☉', undefined]
		]);
		expect(rowsOf(all, 'position')).toEqual([
			['Right ascension', '17ʰ 45ᵐ 40.03ˢ', undefined],
			['Declination', '-29° 00′ 28.2″', undefined],
			['Epoch', 'J2016.0', undefined],
			['Distance to the centre', '27,000 ± 110 ly', undefined]
		]);
	});

	it('show a length that a paper gives in parsecs in light years', () => {
		expect(rowsOf(sections(), 'structure')).toEqual([
			['Half-light radius', '18,800 ± 1,200 ly', undefined],
			['Disc scale length', '8,610 ± 420 ly', undefined],
			['Thin disc scale height', '980 ± 200 ly', undefined],
			['Thick disc scale height', '2,940 ± 590 ly', undefined],
			['Disc radius', '≥ 84,800 ly', undefined],
			['Bar half-length', '16,310 ± 650 ly', undefined]
		]);
	});

	it('mark an estimate, and show a count that is a range as a range', () => {
		const all = sections();
		expect(rowsOf(all, 'population')).toEqual([
			['Stars', '100–200B', 'estimated'],
			['Star formation rate', '1.65 ± 0.19 M☉/yr', undefined],
			['Core-collapse supernovae', '1.63 ± 0.46 per century', undefined],
			['Planets per star', '1.60 (0.71–2.32)', undefined],
			['Free-floating planets per star', '21 (8–44)', undefined],
			['Planets', '80–500B', 'estimated']
		]);
		expect(rowsOf(all, 'rotation')).toEqual([
			['Rotation speed at the Sun', '236 ± 7 km/s', undefined],
			['Orbital period of the Sun', '212 ± 11 Ma', 'estimated']
		]);
	});

	it('show a lower limit as one', () => {
		expect(rowsOf(sections(), 'companions')).toEqual([
			['Globular clusters', '157', undefined],
			['Satellite galaxies', '≥ 65', undefined]
		]);
	});

	it('write a count in the digits of the locale', () => {
		const base = getLocale;
		overwriteGetLocale(() => 'de');
		try {
			const all = sections();
			expect(rowsOf(all, 'population')[0][1]).toBe('100–200 Mrd.');
			expect(rowsOf(all, 'catalogue')[0][1]).toBe('180.622.691');
		} finally {
			overwriteGetLocale(base);
		}
	});

	it('name no source on a value: the works are in the footer', () => {
		const rows = sections().flatMap((s) => s.rows);
		expect(rows.length).toBeGreaterThan(20);
		expect(rows.filter((r) => r.tooltip !== undefined)).toEqual([]);
	});

	it('keep the figure of a lower limit left to right beside a unit in Arabic letters', () => {
		const base = getLocale;
		overwriteGetLocale(() => 'ar');
		try {
			const [LRI, FSI, PDI] = [0x2066, 0x2068, 0x2069].map((code) => String.fromCharCode(code));
			const value = (key: string, label: number) =>
				sections().find((s) => s.key === key)!.rows[label].value;
			// Disc radius: the unit is outside the isolate of the figure.
			const radius = value('structure', 4);
			expect(radius.startsWith(`≥ ${FSI}${LRI}84,800${PDI}\u00a0`)).toBe(true);
			expect(radius.endsWith(PDI)).toBe(true);
			// Satellite galaxies: a bare figure.
			expect(value('companions', 1)).toBe(`≥ ${LRI}65${PDI}`);
		} finally {
			overwriteGetLocale(base);
		}
	});

	it('label what the catalogue holds as the catalogue, and cite no paper for it', () => {
		const catalogue = sections().find((s) => s.key === 'catalogue');
		expect(catalogue?.title).toBe('In this catalogue');
		expect(catalogue?.rows.map((r) => [r.label, r.value, r.tooltip, r.note])).toEqual([
			['Stars', '180,622,691', undefined, undefined],
			['Star systems', '1,689,592', undefined, undefined],
			['Planets', '7,538', undefined, undefined]
		]);
	});

	it('put the groups of the galaxy under its classification, not under its discovery', () => {
		const groups = [{ name: 'Milky Way subgroup' }, { name: 'Local Group' }];
		const all = galaxySections(row(), MILKY_WAY_ENTRY, null, groups);
		expect(all.find((s) => s.key === 'classification')?.rows.at(-1)).toEqual({
			label: 'part of',
			value: '',
			entities: groups
		});
		// With no other row, the groups still have their section.
		expect(galaxySections(null, null, null, groups).map((s) => s.key)).toEqual(['classification']);
	});

	it('leave out the catalogue for a galaxy whose objects it does not hold', () => {
		const keys = galaxySections(row(), MILKY_WAY_ENTRY).map((s) => s.key);
		expect(keys).not.toContain('catalogue');
	});

	it('show only the facts that the entry has', () => {
		const entry = {
			references: MILKY_WAY_ENTRY.references,
			facts: { age: MILKY_WAY_ENTRY.facts!.age }
		};
		expect(galaxySections(row(), entry).map((s) => s.key)).toEqual([
			'classification',
			'mass',
			'population',
			'position'
		]);
		expect(rowsOf(galaxySections(row(), entry), 'population')).toEqual([
			['Star formation rate', '1.65 ± 0.19 M☉/yr', undefined]
		]);
	});

	it('show the row of a galaxy with no entry, and nothing where the row is barred', () => {
		expect(rowsOf(galaxySections(row(), null), 'classification')).toEqual([
			['Morphological type', 'SAB(rs)bc', undefined]
		]);
		expect(galaxySections(null, null)).toEqual([]);
	});

	it('show a value with no bounds at its own figures', () => {
		const bare = MILKY_WAY_COLUMNS.filter(
			({ name }) => !name.endsWith('_lower') && !name.endsWith('_upper')
		);
		const all = galaxySections(galaxyRow(galaxyRecord(bare)), null);
		expect(rowsOf(all, 'mass')).toEqual([
			['Total mass', '1.08×10¹² M☉', undefined],
			['Stellar mass', '5.04×10¹⁰ M☉', undefined]
		]);
		expect(rowsOf(all, 'position').at(-1)).toEqual([
			'Distance to the centre',
			'27,000 ly',
			undefined
		]);
	});
});

describe('the works of a galaxy', () => {
	it('lists each cited work once', () => {
		const works = galaxyWorks(row(), MILKY_WAY_ENTRY);
		const shorts = works.map((work) => work.short);
		expect(new Set(shorts).size).toBe(shorts.length);
		expect(shorts).toHaveLength(20);
		expect(shorts).toContain('Xu et al. 2022');
		expect(shorts).toContain('Chabrier 2003');
	});

	it('lists the works of every column group and every fact of the entry', () => {
		const urls = new Set(galaxyWorks(row(), MILKY_WAY_ENTRY).map((work) => work.url));
		const cited = [
			...Object.values(MILKY_WAY_ENTRY.references ?? {}).flatMap((works) => works ?? []),
			...Object.values(MILKY_WAY_ENTRY.facts ?? {}).flatMap((fact) => fact?.references ?? [])
		];
		expect(cited.length).toBeGreaterThan(20);
		expect(cited.filter((work) => !urls.has(work.url))).toEqual([]);
	});

	it('leaves out the works of a fact with no row', () => {
		const entry = { facts: { age: MILKY_WAY_ENTRY.facts!.age } };
		expect(galaxyWorks(row(), entry).map((work) => work.short)).toEqual(['Xiang & Rix 2022']);
	});
});

describe('the cards of a galaxy', () => {
	it('are one row of three: its stars as an estimate, its width and its type', () => {
		const rows = galaxyStats(row(), MILKY_WAY_ENTRY);
		expect(rows.map((cards) => cards.map((c) => [c.label, plain(c.value), c.note]))).toEqual([
			[
				['Stars', '100–200B', 'estimated'],
				['Diameter', '≥ 170,000 ly', undefined],
				['Type', 'SAB(rs)bc', undefined]
			]
		]);
		expect(rows.flat().filter((card) => card.tooltip !== undefined)).toEqual([]);
	});

	it('give a measured radius twice over, with no limit sign', () => {
		const entry = { facts: { disc_radius: { value: 26000, references: [] } } };
		const [[diameter]] = galaxyStats(null, entry);
		expect(plain(diameter.value)).toBe('170,000 ly');
	});

	it('keep each figure left to right beside a unit in Arabic letters', () => {
		const base = getLocale;
		overwriteGetLocale(() => 'ar');
		try {
			const cards = galaxyStats(row(), MILKY_WAY_ENTRY).flat();
			const [LRI, FSI, PDI] = [0x2066, 0x2068, 0x2069].map((code) => String.fromCharCode(code));
			// The word is outside the isolate of the figures, so it follows them in reading order.
			expect(cards[0].value).toBe(`${FSI}${LRI}100–\u2060200${PDI}\u00a0مليار${PDI}`);
			expect(cards[1].value).toContain(`${FSI}${LRI}170,000${PDI}`);
		} finally {
			overwriteGetLocale(base);
		}
	});

	it('are the type alone for a galaxy with no entry', () => {
		const rows = galaxyStats(row(), null);
		expect(rows.map((cards) => cards.map((c) => c.label))).toEqual([['Type']]);
	});

	it('are none for a galaxy with no row and no entry', () => {
		expect(galaxyStats(null, null)).toEqual([]);
	});
});

describe('the tiles of the galaxy of the Sun', () => {
	it('are the four pages of what it holds, two rows of two', () => {
		expect(HOME_GALAXY_TILES).toEqual([
			CAT_SOLAR_SYSTEM,
			CAT_STARS,
			CAT_STAR_SYSTEMS,
			CAT_PLANETARY_SYSTEMS
		]);
		expect(HOME_GALAXY_TILES.length % 2).toBe(0);
	});
});
