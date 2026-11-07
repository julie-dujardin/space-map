import { describe, expect, it } from 'vitest';
import {
	A,
	AB,
	B,
	ROOT,
	heldValues,
	member,
	pairOrbit,
	systemNodeOf,
	threeStars
} from '$lib/fetch/extrasolar/__fixtures__/system-node';
import {
	pointSourceRecord,
	resolvedSystemRecord,
	valueColumns
} from '$lib/fetch/extrasolar/__fixtures__/record';
import { systemRows, type StarSystem } from '$lib/state/star-system';
import type { ExtrasolarRecord, StarRadius } from '$lib/fetch/extrasolar/lookup';
import { memberFigures, systemSections, systemStats } from './system-rows';
import type { StarRowEntry, StarSection } from './star-rows';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

const section = (sections: StarSection[], key: string) => sections.find((s) => s.key === key);
const entry = (rows: StarRowEntry[] | undefined, label: string) =>
	rows?.find((r) => r.label === label);

/** The Point source row of a point that holds two stars: fits that assume one. */
const point = () =>
	pointSourceRecord(
		valueColumns({
			parallax: 13.194,
			parallax_error: 0.012,
			phot_g_mean_mag: 11.7,
			phot_bp_mean_mag: 12.5,
			phot_rp_mean_mag: 10.8,
			teff_gspphot: 4416,
			radius_flame: 0.68,
			lum_flame: 0.16,
			mass_flame: 0.7,
			age_flame: 3.2,
			evolstage_flame: 300,
			azero_gspphot: 0.55,
			distance_gspphot: 75,
			host_teff: 4450
		})
	);
const pointNode = (values = {}) =>
	systemNodeOf(1, { point: true, primary: 1, distance: 75.3, ...values });

describe('the cards of a node', () => {
	it('count what it holds, with no one-star fits', () => {
		const [cards] = systemStats(point(), pointNode(), 1);
		expect(cards.map((c) => c.label)).toEqual(['Stars', 'Planets', 'Distance']);
		expect(cards[0].value).toBe('2');
		expect(cards[1].value).toBe('1');
	});

	it('leave out the planets of a system with none', () => {
		const [cards] = systemStats(point(), pointNode(), 0);
		expect(cards.map((c) => c.label)).toEqual(['Stars', 'Distance']);
	});

	it('take the distance of the System row with no Point source row', () => {
		const [cards] = systemStats(
			resolvedSystemRecord(ROOT, A),
			systemNodeOf(ROOT, { distance: 1.3459 }),
			0
		);
		expect(plain(cards[1].value)).toBe('4.39 ly');
	});
});

describe('the sections of a node', () => {
	it('keep what is true of the point and leave out the fits of one star', () => {
		const sections = systemSections(point(), pointNode(), null);
		expect(sections.map((s) => s.key)).toEqual(['position', 'brightness']);
		const position = section(sections, 'position')?.rows;
		expect(entry(position, 'Parallax')).toBeDefined();
		expect(entry(position, 'Distance from photometry')).toBeUndefined();
		const brightness = section(sections, 'brightness')?.rows;
		expect(entry(brightness, 'Gaia G')).toBeDefined();
		expect(entry(brightness, 'Extinction (A₀)')).toBeUndefined();
	});

	it('give no spectral type: that belongs to the members', () => {
		const sections = systemSections(point(), pointNode({ spectralType: 'F5IV-V+DQZ' }), null);
		expect(section(sections, 'classification')).toBeUndefined();
	});

	it('place a resolved node by its System row', () => {
		const node = systemNodeOf(ROOT, { ra: 219.87, dec: -60.83, distance: 1.3459 });
		const sections = systemSections(resolvedSystemRecord(ROOT, A), node, null);
		const rows = section(sections, 'position')!.rows;
		expect(rows.map((r) => r.label)).toEqual([
			'Right ascension',
			'Declination',
			'Epoch',
			'Distance'
		]);
		expect(entry(rows, 'Epoch')?.value).toBe('J2016.0');
	});
});

describe('the orbit of a node', () => {
	const rows = (orbit: ReturnType<typeof pairOrbit>) =>
		section(systemSections(point(), pointNode({ orbit }), null), 'orbit')!.rows;

	it('shows each element with its source, by the work where it has one', () => {
		const out = rows(pairOrbit());
		expect(plain(entry(out, 'Orbital period')!.value)).toBe('41.0792 d');
		expect(entry(out, 'Orbital period')?.tooltip).toBe('Source: Doyle et al. 2011');
		expect(entry(out, 'Longitude of ascending node')?.tooltip).toBe(
			'Source: Gaia DR3 orbit solution'
		);
	});

	it('says when the node can be either one', () => {
		const ascending = rows(pairOrbit());
		expect(entry(ascending, 'Longitude of either node')).toBeUndefined();
		const either = rows(pairOrbit({ nodeAscending: false }));
		expect(entry(either, 'Longitude of ascending node')).toBeUndefined();
		expect(entry(either, 'Longitude of either node')?.tooltip).toBe(
			'Source: Gaia DR3 orbit solution'
		);
	});

	it('rounds a Julian day to under a second', () => {
		const time = entry(rows(pairOrbit()), 'Time of periastron');
		expect(plain(time!.value)).toBe('2455190.56935');
	});

	it('writes a long period in years', () => {
		expect(plain(entry(rows(pairOrbit({ period: 29187.1275 })), 'Orbital period')!.value)).toBe(
			'79.91 y'
		);
	});

	it('marks an assumed element and a computed one', () => {
		const out = rows(
			pairOrbit({ assumed: ['eccentricity', 'epoch'], computed: ['semi_major_axis'] })
		);
		expect(entry(out, 'Eccentricity')?.note).toBe('assumed');
		expect(entry(out, 'Time of periastron')?.note).toBe('assumed');
		expect(entry(out, 'Semi-major axis')?.note).toBe('computed');
		expect(entry(out, 'Inclination')?.note).toBeUndefined();
	});

	it('says so when the first member stays at the centre', () => {
		expect(entry(rows(pairOrbit()), 'Centre of orbit')).toBeUndefined();
		expect(entry(rows(pairOrbit({ centre: 'primary' })), 'Centre of orbit')?.value).toBe(
			'Primary star'
		);
	});

	it('gives the angle of an axis that comes from one', () => {
		const axis = entry(rows(pairOrbit({ semiMajorAxisArcsec: 17.57 })), 'Semi-major axis');
		expect(axis?.tooltip).toBe('17.6″ · Source: Doyle et al. 2011');
	});
});

describe('a held star', () => {
	const held = systemNodeOf(A, {
		stars: 1,
		parent: AB,
		root: ROOT,
		distance: 1.3459,
		ra: 219.87,
		dec: -60.83,
		star: heldValues()
	});
	/** A held star whose Metadata row has `radius`. */
	const heldRecord = (radius: StarRadius | null): ExtrasolarRecord => {
		const base = resolvedSystemRecord(A, null);
		return { ...base, metadata: { ...base.metadata, class: 'star', radius } };
	};
	const record = heldRecord({ solar: 0.6489, source: 'literature' });
	const inPair = (orbit = pairOrbit()): StarSystem => {
		const base = threeStars();
		const pair = base.nodes.get(AB)!;
		return { ...base, nodes: new Map([...base.nodes, [AB, { ...pair, orbit }]]) };
	};

	it('shows its own values on its cards', () => {
		const [cards] = systemStats(record, held, 0);
		expect(cards.map((c) => c.label)).toEqual(['Diameter', 'Distance', 'Temperature']);
	});

	it('shows its Metadata radius and that source, not the radius of its System row', () => {
		const archive = heldRecord({ solar: 2, source: 'nasa-exoplanet-archive' });
		const [cards] = systemStats(archive, held, 0);
		expect(cards[0].value).toBe('2.78M km');
		const physical = section(systemSections(archive, held, null), 'physical')?.rows;
		expect(plain(entry(physical, 'Diameter')!.tooltip!)).toBe(
			'2× the Sun · Source: NASA Exoplanet Archive'
		);
	});

	it("names no paper of its own for the radius of its point's paper", () => {
		const borrowed = { ...held, star: heldValues({ radiusSource: null, dominant: true }) };
		const physical = section(systemSections(record, borrowed, null), 'physical')?.rows;
		const tooltip = entry(physical, 'Diameter')!.tooltip!;
		expect(tooltip).not.toContain('Doyle');
		expect(tooltip).toContain('Source: Published paper');
	});

	it('gives a catalogue radius as the page of a star gives it, with its error', () => {
		const host = { ...held, star: heldValues({ hostRadiusError: 0.046 }) };
		const radius = { solar: 1.657, source: 'nasa-exoplanet-archive' } as const;
		const physical = section(systemSections(heldRecord(radius), host, null), 'physical')?.rows;
		expect(plain(entry(physical, 'Diameter')!.value)).toBe('2,306,000 ± 64,000 km');
	});

	it('falls back to mass and spectral type', () => {
		const star = heldValues({ teff: null });
		const [cards] = systemStats(heldRecord(null), { ...held, star }, 0);
		expect(cards.map((c) => c.label)).toEqual(['Mass', 'Distance', 'Spectral type']);
	});

	it('gives each value with its source', () => {
		const sections = systemSections(record, held, null);
		const physical = section(sections, 'physical')?.rows;
		expect(entry(physical, 'Diameter')?.tooltip).toContain('Source: Doyle et al. 2011');
		expect(entry(physical, 'Mass')?.tooltip).toContain('Source: Doyle et al. 2011');
		expect(section(sections, 'classification')?.rows[0].tooltip).toBe(
			'Source: Open Exoplanet Catalogue'
		);
	});

	it('names its pair and its orbit partner, with the orbit of the pair', () => {
		const rows = section(systemSections(record, held, inPair()), 'orbit')!.rows;
		expect(rows.map((r) => r.label)).toEqual([
			'Pair',
			'Orbit partner',
			'Orbital period',
			'Semi-major axis'
		]);
		expect(rows[0].entities).toEqual([
			{ name: 'Alpha Centauri AB', primary_type: 'x', primary_id: String(AB) }
		]);
		expect(rows[1].entities).toEqual([
			{ name: 'Toliman', primary_type: 'x', primary_id: String(B) }
		]);
	});

	it('names an orbit partner with no ID, unlinked', () => {
		const base = inPair();
		const pair = base.nodes.get(AB)!;
		const members = [member(A), member(null, { kind: 'entry', label: 'Gliese 1 B' })];
		const nodes = new Map([...base.nodes, [AB, { ...pair, members }]]);
		const rows = section(systemSections(record, held, { ...base, nodes }), 'orbit')!.rows;
		expect(rows[1].entities).toEqual([{ name: 'Gliese 1 B' }]);
	});

	it('has no pair in a node of three members', () => {
		const base = inPair();
		const pair = base.nodes.get(AB)!;
		const members = [member(A), member(B), member(300)];
		const nodes = new Map([...base.nodes, [AB, { ...pair, members }]]);
		const rows = section(systemSections(record, held, { ...base, nodes }), 'orbit')!.rows;
		expect(rows.map((r) => r.label)).toEqual(['part of']);
	});

	it('has no pair rows before the system loads', () => {
		expect(section(systemSections(record, held, null), 'orbit')).toBeUndefined();
	});
});

describe('memberFigures', () => {
	const rows = systemRows(threeStars(), ROOT);

	it('counts the stars of a member node', () => {
		expect(memberFigures(rows[0])).toEqual({ what: '2 stars', where: '' });
	});

	it('gives what a star is and where it is', () => {
		const { what, where } = memberFigures({
			...rows[3],
			member: { ...rows[3].member, period: 282230501.25 }
		});
		expect(plain(what)).toBe('M5.5Ve · 0.12 M☉');
		expect(plain(where)).toBe('7,860″ · 773,000 y');
	});

	it('falls back to the values of a held star', () => {
		const held = heldValues({ spectralType: 'K', mass: 0.69 });
		expect(plain(memberFigures({ ...rows[1], held }).what)).toBe('K · 0.69 M☉');
	});
});
