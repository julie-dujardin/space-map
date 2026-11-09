/** A body's mass and density rows show the export's pick, with its marks. */

import { afterEach, describe, expect, it } from 'vitest';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { ltrIsolate, quantityIsolate } from '$lib/format/bidi';
import { binarySystemMass, densityRow, massRow, nominalNote } from './body-rows';

/** The text without its bidi isolates and with plain spaces. */
const INVISIBLES = new RegExp('[\\u2060\\u2066-\\u2069]', 'g');
const plain = (s: string) => s.replace(INVISIBLES, '').replace(/\u00a0/g, ' ');

function body(fields: Partial<GlobalObjectData>): GlobalObjectData {
	return { id: 'naif-904', type: 'moon', name: 'Kerberos', ...fields };
}

describe('massRow', () => {
	it('shows the mass the export chose', () => {
		const row = massRow(body({ mass_kg: 6.4171e23, mass_source: 'pck' }));
		expect(
			row && { ...row, value: plain(row.value), valueTooltip: plain(row.valueTooltip!) }
		).toEqual({
			label: 'mass',
			tooltip: undefined,
			value: '6.42×10²³ kg',
			valueTooltip: "11% of Earth's",
			note: undefined
		});
	});

	it('reads no Wikidata or SBDB mass, which the export keeps for older clients', () => {
		const old = {
			wikidata: { mass: { value: 3, unit: 'kilogram' } },
			sbdb: { mass: { value: 3, unit: 'kilogram' } }
		} as unknown as Partial<GlobalObjectData>;
		expect(massRow(body(old))).toBeNull();
		expect(densityRow(body(old))).toBeNull();
	});

	it('marks a nominal mass as estimated', () => {
		const row = massRow(
			body({ mass_kg: 1.65e16, mass_source: 'jpl_satellite_physical', mass_nominal: true })
		);
		expect(row?.note).toBe('estimated');
	});

	it("labels a system mass as the system's", () => {
		const row = massRow(body({ mass_kg: 1.66e22, mass_source: 'pck', mass_system: true }));
		expect(row?.label).toBe('System mass');
		expect(row?.tooltip).toBe('Mass of the body and its moons together.');
	});
});

describe('densityRow', () => {
	it('shows the density the export computed', () => {
		const row = densityRow(body({ mass_kg: 6.4171e23, mean_density_g_cm3: 3.934 }));
		expect(row?.label).toBe('density');
		expect(plain(row!.value)).toBe('3.93 gram per cubic centimetre');
		expect(plain(row!.valueTooltip!)).toBe('1.46× crustal rock');
		expect(row?.note).toBeUndefined();
	});

	it('marks a nominal density as estimated, whatever the mass', () => {
		const row = densityRow(
			body({ mass_kg: 1, mean_density_g_cm3: 0.5, mean_density_nominal: true })
		);
		expect(row?.note).toBe('estimated');
	});

	it("labels the density over a system mass as the system's", () => {
		const row = densityRow(body({ mass_kg: 1, mass_system: true, mean_density_g_cm3: 2.43 }));
		expect(row?.label).toBe('System density');
		expect(row?.tooltip).toBe(
			'System mass divided by the volume of the body and its moons together.'
		);
	});
});

describe('the figures in a right-to-left locale', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('isolate the figure from a Hebrew unit, which follows it', () => {
		overwriteGetLocale(() => 'he');
		const row = densityRow(body({ mass_kg: 1, mean_density_g_cm3: 1.41 }));
		expect(row?.value).toBe(quantityIsolate(`${ltrIsolate('1.41')}\u00a0גרם/סמ"ק`));
		const mass = massRow(body({ mass_kg: 1.989e30 }))!.value;
		expect(plain(mass)).toBe('1.99×10³⁰ ק"ג');
		expect(mass.startsWith(quantityIsolate('').slice(0, 1))).toBe(true);
		expect(mass.endsWith('\u00a0ק"ג\u2069')).toBe(true);
	});
});

describe('nominalNote', () => {
	it('says nothing of a measured value', () => {
		expect(nominalNote(undefined)).toBeUndefined();
		expect(nominalNote(true)).toBe('estimated');
	});
});

describe('binarySystemMass', () => {
	const pair = { value: 1.1e19, unit: 'kg' };

	it("is the catalogue's where the export's mass is the body's own", () => {
		const orcus = body({ mass_kg: 5.8e20, astersat: { frame: 'ICRF', system_mass: pair } });
		expect(binarySystemMass(orcus)).toEqual(pair);
	});

	it("is none where the export's mass is the system's, which shows once", () => {
		const eris = body({
			mass_kg: 1.66e22,
			mass_system: true,
			johnston: { mass: pair }
		});
		expect(binarySystemMass(eris)).toBeUndefined();
	});
});
