import { describe, it, expect } from 'vitest';
import type { Hazard, HazardKind } from '$lib/travel/hazards';
import { radiationSources } from './radiation-sources';

function hazard(kind: HazardKind, extra: Partial<Hazard> = {}): Hazard {
	return {
		kind,
		severity: 'amber',
		startJd: 2460000,
		endJd: 2460100,
		peakJd: 2460050,
		peak: 1,
		...extra
	} as Hazard;
}

const IN_SYSTEM = ['naif-399', 'naif-499'];
const PROXIMA = 'x-27424668';
const BARNARDS_STAR = 'x-24913251';
const EARTH_TO_PROXIMA = ['naif-399', PROXIMA];

/** The two works of the fit inside the heliopause. */
const HELIOSPHERE_AUTHORS = ['Roussos', 'SIDC/SILSO'];

/** The dose per particle against energy. */
const SATO = [
	'https://doi.org/10.1088/0031-9155/54/7/009',
	'https://doi.org/10.1088/0031-9155/55/8/008'
];

/** The density of the gas, which the dust also scales with. */
const DENSITY = [
	'https://doi.org/10.3847/1538-3881/ac816b',
	'https://doi.org/10.3847/1538-4357/ada89e',
	'https://doi.org/10.3847/1538-4357/abb80a',
	'https://doi.org/10.1051/0004-6361:20078101'
];

/** The dose behind the hull per proton. */
const HULL = [
	'https://inspirehep.net/literature/361639',
	'https://physics.nist.gov/PhysRefData/Star/Text/PSTAR.html',
	'https://doi.org/10.1016/j.nimb.2007.09.046'
];

/** The shield: the ISS dose, the cosmic rays behind thick water, the hull works
 *  and the neutrons through iron and concrete. */
const SHIELD = [
	'https://doi.org/10.1051/swsc/2017005',
	'https://ntrs.nasa.gov/citations/20250008430',
	'https://ntrs.nasa.gov/citations/20160007694',
	'https://nss.org/wp-content/uploads/2018/01/NSS-JOURNAL-Orbital-Space-Settlement-Radiation-Shielding.pdf',
	'https://doi.org/10.1371/journal.pone.0144679',
	'https://doi.org/10.21203/rs.3.rs-2364937/v1',
	...HULL,
	'https://doi.org/10.1097/00004032-198207000-00002',
	'https://www.oecd-nea.org/upload/docs/application/pdf/2020-01/nsc-doc2010-6.pdf#page=237',
	'https://www.oecd-nea.org/upload/docs/application/pdf/2020-01/nsc-doc2010-6.pdf#page=45'
];

const ICRP_103 = 'https://www.icrp.org/publication.asp?id=ICRP%20Publication%20103';
const CDC = 'https://www.cdc.gov/radiation-emergencies/hcp/clinical-guidance/ars.html';

describe('radiationSources', () => {
	it('credits nothing for a trip with no dose row', () => {
		expect(radiationSources([hazard('signal-lag'), hazard('conjunction')], IN_SYSTEM)).toEqual([]);
	});

	it('credits the field model and the risk coefficient behind a cruise dose', () => {
		const titles = radiationSources([hazard('radiation')], IN_SYSTEM).map((s) => s.title);
		expect(titles).toHaveLength(4);
		expect(titles.some((t) => t.startsWith('Guo'))).toBe(true);
		expect(titles.some((t) => t.startsWith('ICRP'))).toBe(true);
	});

	it('credits the belt profile and the lethal dose behind a pass in grays', () => {
		const titles = radiationSources(
			[hazard('belt-crossing', { bodyId: 'naif-599' })],
			IN_SYSTEM
		).map((s) => s.title);
		expect(titles.some((t) => t.startsWith('Miller'))).toBe(true);
		expect(titles.some((t) => t.startsWith('CDC'))).toBe(true);
	});

	it('credits only what establishes the belt when the pass carries no figure', () => {
		const titles = radiationSources(
			[hazard('belt-crossing', { bodyId: 'naif-799', unpriced: true })],
			IN_SYSTEM
		).map((s) => s.title);
		expect(titles).toEqual(['Garrett et al. 2015 (JPL Publication 15-1), Uranus Radiation Model']);
	});

	it('leaves an unpriced pass past an unmodelled belt uncredited', () => {
		expect(
			radiationSources([hazard('belt-crossing', { bodyId: 'naif-399', unpriced: true })], IN_SYSTEM)
		).toEqual([]);
	});

	it('adds the interstellar dose works on a trip between two systems', () => {
		const titles = radiationSources(
			[hazard('radiation', { shipTime: true })],
			EARTH_TO_PROXIMA
		).map((s) => s.title);
		expect(titles).toHaveLength(9);
		expect(titles.some((t) => t.startsWith('Guo'))).toBe(true);
		for (const author of ['Mewaldt', 'Corti', 'Cummings', 'Sato et al. 2009', 'Sato, Endo']) {
			expect(titles.some((t) => t.startsWith(author))).toBe(true);
		}
		const plain = radiationSources([hazard('radiation')], IN_SYSTEM).map((s) => s.title);
		expect(plain.some((t) => t.startsWith('Mewaldt'))).toBe(false);
		expect(plain.some((t) => t.startsWith('Sato'))).toBe(false);
	});

	it('credits the fit inside the heliopause only when an end is in the solar system', () => {
		const dose = [hazard('radiation', { shipTime: true })];
		const titles = (ends: string[]) => radiationSources(dose, ends).map((s) => s.title);
		const between = titles([PROXIMA, BARNARDS_STAR]);
		expect(between).toHaveLength(7);
		for (const author of ['Guo', 'ICRP', 'Mewaldt', 'Corti', 'Cummings', 'Sato']) {
			expect(between.some((t) => t.startsWith(author))).toBe(true);
		}
		for (const author of HELIOSPHERE_AUTHORS) {
			expect(between.some((t) => t.startsWith(author))).toBe(false);
		}
		// A planet of another star is in the system of its host.
		expect(titles([`${PROXIMA}-b-1`, BARNARDS_STAR])).toEqual(between);
		for (const ends of [EARTH_TO_PROXIMA, [BARNARDS_STAR, 'naif-399']]) {
			const solar = titles(ends);
			for (const author of HELIOSPHERE_AUTHORS) {
				expect(solar.some((t) => t.startsWith(author))).toBe(true);
			}
		}
	});

	it('credits the grain sizes and the gas density behind the dust row', () => {
		const sources = radiationSources([hazard('dust')], EARTH_TO_PROXIMA);
		expect(sources.map((s) => s.url)).toEqual([
			'https://doi.org/10.1086/318651',
			'https://doi.org/10.1088/0004-637X/812/2/139',
			'https://doi.org/10.1051/0004-6361/201834316',
			'https://doi.org/10.1029/1999JA900359',
			...DENSITY
		]);
		expect(radiationSources([hazard('signal-lag')], EARTH_TO_PROXIMA)).toEqual([]);
	});

	it('credits the dose coefficients, the gas density and the hull behind the gas row', () => {
		const urls = (peak: number) =>
			radiationSources([hazard('gas', { peak, shipTime: true })], EARTH_TO_PROXIMA).map(
				(s) => s.url
			);
		// 7.8 × 10⁸ Sv, Nostalgia for Infinity to Proxima: many lethal doses.
		expect(urls(7.8e8)).toEqual([...SATO, ...DENSITY, ...HULL, ICRP_103, CDC]);
		// Under the linear risk model, the sentence gives the cancer risk instead.
		expect(urls(10)).toEqual([...SATO, ...DENSITY, ...HULL, ICRP_103]);
		// The gas row has nothing of the heliosphere fit.
		for (const author of HELIOSPHERE_AUTHORS) {
			expect(
				radiationSources([hazard('gas', { peak: 7.8e8 })], EARTH_TO_PROXIMA).some((s) =>
					s.title.startsWith(author)
				)
			).toBe(false);
		}
	});

	it('credits the shield works only for a route with a shield', () => {
		const urls = (hazards: Hazard[], shielded: boolean, ends = EARTH_TO_PROXIMA) =>
			radiationSources(hazards, ends, shielded).map((s) => s.url);
		const cosmic = [hazard('radiation', { shipTime: true })];
		const plain = urls(cosmic, false);
		expect(urls(cosmic, true)).toEqual([...plain, ...SHIELD]);
		// The shield does not need a dose row: either row can be under its threshold.
		expect(urls([], true)).toEqual(SHIELD);
		const unshielded = [
			plain,
			urls([hazard('radiation')], false, IN_SYSTEM),
			urls([hazard('gas', { peak: 7.8e8, shipTime: true })], false)
		];
		for (const list of unshielded) {
			for (const url of SHIELD.slice(0, 6)) expect(list).not.toContain(url);
		}
	});

	it('links each work of a crossing to its own page', () => {
		const sources = radiationSources(
			[
				hazard('radiation', { shipTime: true }),
				hazard('dust'),
				hazard('gas', { peak: 7.8e8, shipTime: true })
			],
			EARTH_TO_PROXIMA,
			true
		);
		// The panel keys its list by url. The two SATIF-8 papers share one PDF.
		expect(new Set(sources.map((s) => s.url)).size).toBe(sources.length);
		expect(sources.filter((s) => s.title.includes('SATIF-8'))).toHaveLength(2);
		for (const source of sources) expect(source.url).toMatch(/^https:\/\//);
	});

	it('credits a work shared by two rows once', () => {
		const sources = radiationSources(
			[
				hazard('radiation', { shipTime: true }),
				hazard('dust'),
				hazard('gas', { peak: 7.8e8, shipTime: true }),
				hazard('belt-crossing', { bodyId: 'naif-599' }),
				hazard('belt-crossing', { bodyId: 'naif-599' })
			],
			EARTH_TO_PROXIMA,
			true
		);
		expect(new Set(sources.map((s) => s.title)).size).toBe(sources.length);
	});
});
