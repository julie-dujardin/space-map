import { describe, expect, it } from 'vitest';
import { elements, host, planet } from '$lib/scene/exoplanets/__fixtures__/system';
import { HAS_EXPORT, readExportJson } from '$lib/fetch/extrasolar/__fixtures__/export';
import type { Planet, PlanetSystem } from '$lib/fetch/extrasolar/planets';
import type { PlanetAnchor } from '$lib/types/objects';
import {
	archiveOverview,
	discoveryMethodLabel,
	earthScale,
	formatDays,
	planetBadges,
	planetSections,
	planetStats
} from './planet-rows';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

function anchor(p: Planet, star = host(p.host, [p.number])): PlanetAnchor {
	return { host: p.host, number: p.number, system: p.host, planet: p, hostRecord: star };
}

/** Each section's rows as label → "value [note]". */
function rowsOf(a: PlanetAnchor): Record<string, Record<string, string>> {
	return Object.fromEntries(
		planetSections(a).map((s) => [
			s.key,
			Object.fromEntries(
				s.rows.map((r) => [r.label, plain(r.note ? `${r.value} [${r.note}]` : r.value)])
			)
		])
	);
}

const statsOf = (p: Planet) =>
	planetStats(p).map((row) => row.map((s) => [s.label, plain(s.value), s.note]));

describe("a planet's panel", () => {
	const hot = planet(5, 1, elements(0.05), {
		period: 3.52474859,
		period_error_upper: 3.8e-7,
		period_error_lower: 3.8e-7,
		semi_major_axis: 0.04747,
		eccentricity: 0,
		inclination: 86.71,
		inclination_error_upper: 0.34,
		inclination_error_lower: 0.21,
		mass: 0.73,
		mass_error_upper: 0.04,
		mass_error_lower: 0.04,
		mass_kind: 'true',
		radius: 1.38,
		equilibrium_temperature: 1449,
		discovery_method: 'Transit',
		discovery_year: 1999
	});
	hot.assumed = ['eccentricity'];

	it('gives the four stat cards in Jupiter units for a giant', () => {
		expect(statsOf(hot)).toEqual([
			[
				['Mass', '0.73 MJ', undefined],
				['Radius', '1.38 RJ', undefined]
			],
			[
				['Orbital period', '3.52 d', undefined],
				['Distance from star', '0.0475 AU', undefined]
			]
		]);
		expect(earthScale(hot)).toBe(false);
	});

	it('shows each value at the precision of its error, and what was assumed', () => {
		const rows = rowsOf(anchor(hot));
		expect(rows.orbit['Orbital period']).toBe('3.52474859 ± 0.00000038 d');
		expect(rows.orbit.Eccentricity).toBe('0 [assumed]');
		expect(rows.orbit.Inclination).toBe('86.71° (86.50–87.05°)');
		expect(rows.orbit['Position on orbit']).toBe('From the time of transit');
		expect(rows.orbit['Orbit in the map']).toBeUndefined();
		expect(rows.physical.Mass).toBe('0.73 ± 0.04 MJ');
		expect(rows.discovery).toEqual({ 'Detection method': 'Transit', 'Year of discovery': '1999' });
	});

	it('reads a small planet in Earth units, with the kind of its mass', () => {
		const small = planet(5, 2, elements(0.05), {
			mass: 0.0033194,
			mass_kind: 'minimum',
			radius: 0.0913
		});
		small.estimated = ['radius'];
		expect(earthScale(small)).toBe(true);
		const [masses] = statsOf(small);
		expect(masses).toEqual([
			['Mass', '1.05 M⊕', 'minimum (m sin i)'],
			['Radius', '1.02 R⊕', 'estimated']
		]);
		const card = planetStats(small)[0][0];
		expect(plain(card.tooltip!)).toBe('0.00332 MJ');
		// The published digits carry over to the other unit.
		expect(rowsOf(anchor(small)).physical.Mass).toBe('1.055 M⊕ [minimum (m sin i)]');
	});

	it('says that a value is unknown, or a limit', () => {
		const bare = planet(5, 3, null, { mass: 2.1 });
		bare.limits = ['mass<'];
		expect(statsOf(bare)).toEqual([
			[
				['Mass', '< 2.1 MJ', undefined],
				['Radius', 'Unknown', undefined]
			],
			[
				['Orbital period', 'Unknown', undefined],
				['Distance from star', 'Unknown', undefined]
			]
		]);
	});

	it('says when the place on the orbit or the drawn orbit is not as published', () => {
		const assumed = planet(5, 4, elements(1, { phase: 'assumed' }), {
			periastron_time: 2451545
		});
		assumed.assumed = ['periastron_time'];
		const assumedRows = rowsOf(anchor(assumed)).orbit;
		expect(assumedRows['Position on orbit']).toBe('Unknown');
		expect(assumedRows['Time of periastron']).toBe('2451545 [assumed]');

		const replaced = planet(5, 5, elements(1, { e: 0, replaced: ['eccentricity'] }), {
			eccentricity: 280
		});
		expect(rowsOf(anchor(replaced)).orbit['Orbit in the map']).toBe(
			'Circle (eccentricity out of range)'
		);
		expect(rowsOf(anchor(replaced)).orbit.Eccentricity).toBe('280');

		const none = planet(5, 6, null, { period: 1500 });
		expect(rowsOf(anchor(none)).orbit).toEqual({
			'Orbital period': '1,500 d',
			'Orbit in the map': 'None (no semi-major axis)'
		});
	});

	it('badges the class, and a controversial status', () => {
		const dwarf = planet(5, 7, null);
		dwarf.class = 'brown dwarf';
		dwarf.status = 'controversial';
		expect(planetBadges(dwarf)).toEqual(['Brown dwarf', 'Controversial']);
		expect(planetBadges(hot)).toEqual(['Planet']);
	});

	it('writes a period in days with a space before its unit, as the cards do', () => {
		expect(plain(formatDays(5.12338))).toBe('5.12 d');
		expect(plain(formatDays(1928.7))).toBe('1,930 d');
	});

	it('names the discovery methods the catalogues use, whatever their case', () => {
		expect(discoveryMethodLabel('Radial Velocity')).toBe('Radial velocity');
		expect(discoveryMethodLabel('disk kinematics')).toBe('Disk kinematics');
		expect(discoveryMethodLabel('Something new')).toBe('Something new');
	});

	it('links the host star, and the catalogues by the names they use', () => {
		const named = planet(5, 1, elements(0.05));
		named.name = 'Dimidium';
		named.name_source = 'iau-nameexoworlds';
		named.designation = '51 Peg b';
		named.aliases = ['Dimidium', '51 Peg b', '51 Pegasi b', 'HD 217014 b'];
		named.cross_ids = [
			{ catalogue: 'nasa-exoplanet-archive', release: 'pscomppars', catalogue_id: '3.1' },
			{ catalogue: 'exoplanet-eu', release: 'catalog', catalogue_id: '51 Pegasi b' }
		];
		named.sources = { orbit: 'nasa-exoplanet-archive', mass: 'exoplanet-eu' };
		const sections = planetSections(anchor(named));
		const identifiers = sections.find((s) => s.key === 'identifiers')!.rows;
		expect(identifiers.map((r) => [r.label, r.value])).toEqual([
			['IAU name', 'Dimidium'],
			['Designation', '51 Peg b'],
			['NASA Exoplanet Archive', '51 Peg b'],
			['exoplanet.eu', '51 Pegasi b'],
			['Other names', 'HD\u00a0217014\u00a0b'],
			['Space Map ID', '5/b/1']
		]);
		expect(identifiers[2].href).toBe(archiveOverview('51 Peg b'));
		const star = sections.find((s) => s.key === 'host')!.rows[0];
		expect(star).toMatchObject({ value: 'Star 5', target: { id: 'x-5' } });
		expect(rowsOf(anchor(named)).sources).toEqual({
			Name: 'IAU NameExoWorlds',
			Orbit: 'NASA Exoplanet Archive',
			Mass: 'exoplanet.eu'
		});
	});

	it('keeps a short other name whole, and lets a long one wrap at its spaces', () => {
		const p = planet(5, 1, elements(0.05));
		p.aliases = ['Gl 229 Ba', 'Gaia DR2 2835207319109249920 b'];
		const identifiers = planetSections(anchor(p)).find((s) => s.key === 'identifiers')!.rows;
		expect(identifiers.find((r) => r.label === 'Other names')!.value).toBe(
			'Gl 229 Ba and Gaia DR2 2835207319109249920 b'
		);
	});
});

describe.skipIf(!HAS_EXPORT)("a planet's panel from the real export", () => {
	const system = (key: number) => readExportJson<PlanetSystem>(`planets/${key}.json.gz`);
	const anchorOf = (key: number, hostId: number, n: number): PlanetAnchor => {
		const file = system(key);
		const p = file.planets.find((x) => x.host === hostId && x.number === n)!;
		return anchor(p, file.hosts.find((h) => h.id === hostId)!);
	};

	it('shows Proxima b', () => {
		const rows = rowsOf(anchorOf(27424668, 27424668, 1));
		expect(rows.orbit['Orbital period']).toBe('11.18465 ± 0.00053 d');
		expect(rows.orbit['Position on orbit']).toBe('From the time of transit');
		expect(rows.physical.Mass).toBe('1.055 ± 0.055 M⊕ [minimum (m sin i)]');
		expect(rows.host.Star).toBe('Proxima Centauri');
		expect(rows.host['Orbit in a binary']).toBe('Around one star (S-type)');
		expect(rows.identifiers['NASA Exoplanet Archive']).toBe('Proxima Cen b');
	});

	it('shows α Cen B c with no orbit, and TOI-1272 c drawn as a circle', () => {
		expect(rowsOf(anchorOf(27424668, 564339647, 1)).orbit['Orbit in the map']).toBe(
			'None (no semi-major axis)'
		);
		const toi = rowsOf(anchorOf(19608004, 19608004, 2));
		expect(toi.orbit['Orbit in the map']).toBe('Circle (eccentricity out of range)');
	});
});
