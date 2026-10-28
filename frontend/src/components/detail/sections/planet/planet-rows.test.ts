import { describe, expect, it } from 'vitest';
import { elements, host, planet } from '$lib/scene/exoplanets/__fixtures__/system';
import { HAS_EXPORT, readExportJson } from '$lib/fetch/extrasolar/__fixtures__/export';
import type { Planet, PlanetSystem } from '$lib/fetch/extrasolar/planets';
import type { PlanetAnchor } from '$lib/types/objects';
import {
	archiveOverview,
	discoveryMethodLabel,
	formatDays,
	planetAliases,
	planetBadges,
	planetIdentifiers,
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

	it('gives the three preferred available stats for a giant', () => {
		expect(statsOf(hot)).toEqual([
			[
				['Diameter', '197,000 km', undefined],
				['Mean orbital speed', '147 km/s', undefined],
				['Distance from star', '0.0475 AU', undefined]
			]
		]);
	});

	it('uses the circumference of an eccentric orbit for its mean speed', () => {
		const eccentric = planet(5, 9, elements(0.05, { e: 0.8 }), {
			period: 3.52474859,
			semi_major_axis: 0.04747,
			eccentricity: 0.8
		});
		expect(statsOf(eccentric)[0][0]).toEqual(['Mean orbital speed', '119 km/s', undefined]);

		delete eccentric.values.eccentricity;
		expect(statsOf(eccentric)[0].some(([label]) => label === 'Mean orbital speed')).toBe(false);
	});

	it('bounds the mean speed as the limits it comes from bound it', () => {
		const loose = planet(5, 10, elements(0.05), {
			period: 3.52474859,
			semi_major_axis: 0.04747,
			eccentricity: 0.6
		});
		const speed = () => statsOf(loose)[0].find(([label]) => label === 'Mean orbital speed');
		expect(speed()).toEqual(['Mean orbital speed', '132 km/s', undefined]);
		// A rounder orbit is longer, in the same period.
		loose.limits = ['eccentricity<'];
		expect(speed()).toEqual(['Mean orbital speed', '> 132 km/s', undefined]);
		loose.limits = ['eccentricity<', 'semi_major_axis>'];
		expect(speed()?.[1]).toBe('> 132 km/s');
		loose.limits = ['period>'];
		expect(speed()?.[1]).toBe('< 132 km/s');
		loose.limits = ['eccentricity<', 'period>'];
		expect(speed()).toBeUndefined();
	});

	it('shows each value at the precision of its error, and what was assumed', () => {
		const rows = rowsOf(anchor(hot));
		expect(rows.orbit['Orbital period']).toBe('3.52474859 ± 0.00000038 d');
		expect(rows.orbit.Eccentricity).toBe('0 [assumed]');
		expect(rows.orbit.Inclination).toBe('86.71° (86.50–87.05°)');
		expect(rows.orbit['Position on orbit']).toBeUndefined();
		expect(rows.orbit['Orbit in the map']).toBeUndefined();
		expect(rows.physical.Mass).toBe('(1.386 ± 0.076)×10²⁷ kg');
		expect(rows.physical.Diameter).toBe('197,000 km');
		expect(rows.discovery).toEqual({ 'Detection method': 'Transit', 'Year of discovery': '1999' });
	});

	it('reads a mass in kilograms, against Jupiter or Earth, with its errors', () => {
		const mass = planetSections(anchor(hot))
			.find((s) => s.key === 'physical')!
			.rows.find((r) => r.label === 'Mass')!;
		expect(plain(mass.tooltip!)).toBe("73.0% ± 4.0% of Jupiter's");

		const small = planet(5, 2, elements(0.05), {
			mass: 0.0033194,
			mass_kind: 'minimum',
			radius: 0.0913
		});
		small.estimated = ['radius'];
		const [cards] = statsOf(small);
		expect(cards).toEqual([
			['Diameter', '13,100 km', 'estimated'],
			['Class', 'Planet', undefined]
		]);
		expect(planetStats(small)[0][0].tooltip).toBeUndefined();
		// The published digits carry over to kilograms.
		expect(rowsOf(anchor(small)).physical.Mass).toBe('6.3007×10²⁴ kg [minimum (m sin i)]');
		expect(rowsOf(anchor(small)).physical.Diameter).toBe('13,100 km [estimated]');
	});

	it('reads insolation in W/m², against Earth with its errors', () => {
		const lit = planet(5, 6, elements(0.05), {
			insolation: 0.641,
			insolation_error_upper: 0.065,
			insolation_error_lower: 0.065
		});
		const insolation = planetSections(anchor(lit))
			.find((s) => s.key === 'physical')!
			.rows.find((r) => r.label === 'Insolation')!;
		expect(plain(insolation.value)).toBe('872 ± 88 W/m²');
		expect(plain(insolation.tooltip!)).toBe("64.1% ± 6.5% of Earth's");
		expect(insolation.definition).toBe(
			"Power per unit area received from the star at the planet's distance"
		);
		lit.values = { insolation: 2400 };
		expect(rowsOf(anchor(lit)).physical.Insolation).toBe('3.3 MW/m²');
	});

	it('omits unknown stats and keeps limits', () => {
		const bare = planet(5, 3, null, { mass: 2.1 });
		bare.limits = ['mass<'];
		expect(statsOf(bare)).toEqual([
			[
				['Mass', '< 3.99×10²⁷ kg', undefined],
				['Class', 'Planet', undefined]
			]
		]);
	});

	it('leaves map-fit details for a later presentation', () => {
		const assumed = planet(5, 4, elements(1, { phase: 'assumed' }), {
			periastron_time: 2451545
		});
		assumed.assumed = ['periastron_time'];
		const assumedRows = rowsOf(anchor(assumed)).orbit;
		expect(assumedRows['Position on orbit']).toBeUndefined();
		expect(assumedRows['Time of periastron']).toBe('2451545 [assumed]');

		const replaced = planet(5, 5, elements(1, { e: 0, replaced: ['eccentricity'] }), {
			eccentricity: 280
		});
		expect(rowsOf(anchor(replaced)).orbit['Orbit in the map']).toBeUndefined();
		expect(rowsOf(anchor(replaced)).orbit.Eccentricity).toBe('280');

		const none = planet(5, 6, null, { period: 1500 });
		expect(rowsOf(anchor(none)).orbit).toEqual({ 'Orbital period': '1,500 d' });
	});

	it('keeps the class badge and moves a controversial status into the stats', () => {
		const dwarf = planet(5, 7, null);
		dwarf.class = 'brown dwarf';
		dwarf.class_basis = 'minimum mass';
		dwarf.status = 'controversial';
		expect(planetBadges(dwarf)).toEqual(['Brown dwarf']);
		expect(statsOf(dwarf)[0][0]).toEqual(['Status', 'Controversial', undefined]);
		expect(statsOf(dwarf)[0][1]).toEqual(['Class', 'Brown dwarf', 'Minimum mass']);
		expect(planetBadges(hot)).toEqual(['Planet']);
	});

	it('shows a mass ratio only where no planet mass is available', () => {
		const ratio = planet(5, 8, null);
		ratio.mass_ratio = 0.001;
		expect(rowsOf(anchor(ratio)).physical['Mass ratio to the star']).toBe('1×10⁻³');
		ratio.values.mass = 1;
		expect(rowsOf(anchor(ratio)).physical['Mass ratio to the star']).toBeUndefined();
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

	it('links the catalogues by the names they use', () => {
		const named = planet(5, 1, elements(0.05));
		named.name = 'Dimidium';
		named.name_source = 'iau-nameexoworlds';
		named.designation = '51 Peg b';
		named.aliases = ['Dimidium', '51 Peg b', '51 Pegasi b', 'HD 217014 b'];
		named.cross_ids = [
			{ catalogue: 'nasa-exoplanet-archive', release: 'pscomppars', catalogue_id: '3.1' },
			{ catalogue: 'exoplanet-eu', release: 'catalog', catalogue_id: '51 Pegasi b' }
		];
		const identifiers = planetIdentifiers(named);
		expect(identifiers.map((r) => [r.label, r.value])).toEqual([
			['IAU name', 'Dimidium'],
			['Designation', '51 Peg b'],
			['NASA Exoplanet Archive', '51 Peg b'],
			['exoplanet.eu', '51 Pegasi b']
		]);
		expect(identifiers[2].href).toBe(archiveOverview('51 Peg b'));
		expect(planetAliases(named)).toEqual(['HD 217014 b']);
	});

	it('leaves other names to the shared links section', () => {
		const p = planet(5, 1, elements(0.05));
		p.aliases = ['Gl 229 Ba', 'Gaia DR2 2835207319109249920 b'];
		expect(planetAliases(p)).toEqual(['Gl 229 Ba', 'Gaia DR2 2835207319109249920 b']);
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
		expect(rows.orbit['Position on orbit']).toBeUndefined();
		expect(rows.physical.Mass).toBe('(6.30 ± 0.33)×10²⁴ kg [minimum (m sin i)]');
		expect(
			planetIdentifiers(anchorOf(27424668, 27424668, 1).planet).find(
				(row) => row.label === 'NASA Exoplanet Archive'
			)?.value
		).toBe('Proxima Cen b');
	});

	it('does not expose map-fit details', () => {
		expect(rowsOf(anchorOf(27424668, 564339647, 1)).orbit['Orbit in the map']).toBeUndefined();
		const toi = rowsOf(anchorOf(19608004, 19608004, 2));
		expect(toi.orbit['Orbit in the map']).toBeUndefined();
	});
});
