import { describe, it, expect } from 'vitest';

// No runtime mock: the unit symbols and the vocabularies come out of paraglide,
// and stubbing the runtime cuts the messages off from their locale.
import {
	activitySummary,
	ageParts,
	degreeParts,
	dipoleMomentNote,
	fieldParts,
	fieldStrengthNote,
	fieldSummary,
	headline,
	massRateParts,
	measurement,
	momentParts,
	powerParts,
	qualifier
} from './activity';
import type { ActivityBlock } from '$lib/fetch/objects/object-data';

/** Strip the LRI/PDI isolates the RTL-safe formatters wrap numbers in, so an
 *  assertion reads as the string a user sees. */
const plain = (s: string | null) => s?.replace(/[\u2066\u2069]/g, '') ?? null;

describe('measurement', () => {
	it('keeps a bare count bare', () => {
		expect(measurement({ value: 52 })).toBe('52');
	});

	it('keeps every digit of a catalogue count', () => {
		// GVP holds 1,196 Holocene volcanoes. Three significant figures would
		// publish 1,200 as though the last two digits were unknown.
		expect(measurement({ value: 1196 })).toBe('1,196');
	});

	it('goes scientific before a decimal turns into zeros', () => {
		// Ceres extrudes 10⁻⁵ km³ of brine a year.
		expect(measurement({ value: 1e-5 })).toBe('1×10⁻⁵');
		expect(measurement({ value: 0.04 })).toBe('0.04');
	});

	it('says the unit once across a span', () => {
		expect(measurement({ value: 4.7e13, range: [4.5e13, 4.9e13] }, powerParts)).toBe(
			'47 TW (45–49 TW)'
		);
	});

	it('says it twice when the span crosses a prefix', () => {
		// Venus's surface age: 250 Ma to 1 Ga depending on the crater model, and
		// "250–1 Ga" would read as a range ending below where it starts.
		expect(measurement({ value: 6e8, range: [2.5e8, 1e9] }, ageParts)).toBe(
			'600 Ma (250 Ma – 1 Ga)'
		);
	});

	it('scales heat down to Enceladus', () => {
		expect(measurement({ value: 1.58e10 }, powerParts)).toBe('15.8 GW');
	});

	it('scales a field from Jupiter to the Moon', () => {
		expect(measurement({ value: 4.177e-4 }, fieldParts)).toBe('418 µT');
		expect(measurement({ value: 7.18e-7 }, fieldParts)).toBe('718 nT');
	});

	it('marks a bound and gives it no width', () => {
		// Titan's moment is a non-detection. A "<" and a bracket would be two
		// different statements about the same absence.
		expect(measurement({ value: 7.8e-10, upper_limit: true }, fieldParts)).toBe('< 0.78 nT');
	});

	it('brackets a fixed unit the way it brackets a prefixed one', () => {
		// Enceladus's plumes, on the same panel as its 15.8 GW. The rate used to
		// wrap the whole reading in a message of its own and came out
		// "200 (170–230) kg/s" beside "15.8 GW (12.7–18.9 GW)".
		expect(measurement({ value: 200, range: [170, 230] }, massRateParts)).toBe(
			'200 kg/s (170–230 kg/s)'
		);
	});

	it('binds a degree sign to its digits', () => {
		expect(measurement({ value: 9.6, range: [9.4, 9.9] }, degreeParts)).toBe('9.6° (9.4–9.9°)');
	});
});

describe('headline', () => {
	it('drops a width the card has no room for', () => {
		// Jupiter's surface field, published 320 µT to 2 mT. The full form is
		// three lines in a stat card; the tooltip still carries it.
		expect(headline({ value: 4.177e-4, range: [3.2e-4, 2e-3] }, fieldParts)).toBe('418 µT');
	});

	it('keeps the bound, which is what the number is', () => {
		expect(headline({ value: 7.8e-10, upper_limit: true }, fieldParts)).toBe('< 0.78 nT');
	});

	it('is the whole reading where there was no width to drop', () => {
		const value = { value: 1.05e14 };
		expect(headline(value, powerParts)).toBe(measurement(value, powerParts));
	});
});

describe('qualifier', () => {
	it('has nothing to say about a plain measurement', () => {
		expect(qualifier({ value: 52 })).toBeUndefined();
	});

	it('flags an extrapolation, which would otherwise read as a count', () => {
		expect(qualifier({ value: 120, modelled: true })).toContain('Scaled');
	});

	it('passes the survey through in the source’s own words', () => {
		expect(qualifier({ value: 343, as_of: 'through mid-2023' })).toBe('through mid-2023');
	});
});

describe('activitySummary', () => {
	const summary = (activity: ActivityBlock) => activitySummary(activity);

	it('leads with volcanism and adds tectonics only where it is running', () => {
		expect(
			summary({
				volcanism: { kind: 'silicate', status: 'active' },
				tectonics: { style: 'plate_tectonics', status: 'active' }
			})
		).toBe('Volcanism, plate tectonics');
	});

	it('qualifies anything short of active, which is most of the list', () => {
		expect(summary({ volcanism: { kind: 'silicate', status: 'probable' } })).toBe(
			'Volcanism (probable)'
		);
		expect(summary({ volcanism: { kind: 'cryo', status: 'suspected' } })).toBe(
			'Cryovolcanism (suspected)'
		);
	});

	it('leaves out tectonics nobody has caught moving', () => {
		// Mercury's thrust scarps are `probable`, and naming the style beside an
		// active volcano would read as two live processes.
		expect(
			summary({
				volcanism: { kind: 'silicate', status: 'extinct' },
				tectonics: { style: 'contractional_lid', status: 'probable' }
			})
		).toBe('Volcanism (extinct)');
	});

	it('names that style anyway where the row is all the tectonics get', () => {
		// The Structure tab has no separate tectonics row, so an omission there
		// loses Mercury's scarps entirely rather than deferring them.
		expect(
			activitySummary(
				{
					volcanism: { kind: 'silicate', status: 'extinct' },
					tectonics: { style: 'contractional_lid', status: 'probable' }
				},
				{ everyStyle: true }
			)
		).toBe('Volcanism (extinct), contractional lid (probable)');
	});

	it('says a tide has stopped, which is why the rest reads past tense', () => {
		// Ganymede, Triton and Charon. The tide is the reason the grooves and the
		// resurfacing happened, and it is the only place that now gets said.
		expect(
			summary({
				volcanism: { kind: 'cryo', status: 'extinct' },
				tidal: { raised_by: 'naif-599', role: 'past' }
			})
		).toBe('Cryovolcanism (extinct), tidally heated in the past');
	});

	it('says nothing about a tide that is still running', () => {
		// Europa's is `significant` with no watts behind it, and a rung with
		// nothing to be significant against is not worth a clause.
		expect(
			summary({
				volcanism: { kind: 'cryo', status: 'suspected' },
				tidal: { raised_by: 'naif-599', role: 'significant' }
			})
		).toBe('Cryovolcanism (suspected)');
	});

	it('falls back to the tide where that is all there is', () => {
		// Mimas and Dione: no volcanism entry, and an ocean that only the tide
		// explains.
		expect(summary({ tidal: { raised_by: 'naif-699', role: 'significant' } })).toBe(
			'Tidally heated'
		);
	});

	it('says nothing for a body with only a magnetic field', () => {
		expect(summary({ magnetism: { kind: 'dynamo' } })).toBeNull();
		expect(activitySummary(undefined)).toBeNull();
	});
});

describe('fieldSummary', () => {
	it('names the kind and the strength', () => {
		expect(plain(fieldSummary({ kind: 'dynamo', surface_field_t: { value: 2.9733e-5 } }))).toBe(
			'Dynamo · 29.7 µT'
		);
	});

	it('drops the span, which belongs in the tab', () => {
		expect(
			plain(
				fieldSummary({
					kind: 'dynamo',
					surface_field_t: { value: 2.28e-5, range: [1e-5, 1.1e-4] }
				})
			)
		).toBe('Dynamo · 22.8 µT');
	});

	it('is the kind alone where the finding is that there is one', () => {
		expect(plain(fieldSummary({ kind: 'induced' }))).toBe('Induced');
	});

	it('does not put a bound next to "none"', () => {
		// Titan's 0.78 nT is the tightness of the non-detection, not a field.
		expect(
			plain(fieldSummary({ kind: 'none', surface_field_t: { value: 7.8e-10, upper_limit: true } }))
		).toBe('None detected');
	});
});

describe('fieldStrengthNote', () => {
	it('reads a field against the one everybody stands in', () => {
		// Jupiter: 14× Earth's at the cloud tops, against a dipole moment 20,000×
		// Earth's. The gap between the two ratios is Jupiter's size.
		expect(plain(fieldStrengthNote({ value: 4.177e-4 }) ?? null)).toBe('14× Earth');
	});

	it('keeps what the source said after the comparison', () => {
		expect(plain(fieldStrengthNote({ value: 7.18e-7, as_of: 'Galileo' }) ?? null)).toBe(
			"2.4% of Earth's — Galileo"
		);
	});

	it('has nothing to tell Earth about itself', () => {
		expect(fieldStrengthNote({ value: 2.9733e-5 })).toBeUndefined();
	});
});

describe('momentParts', () => {
	it('keeps a 28-digit number readable', () => {
		// Jupiter. No prefixed form of A m² exists, so this is the one quantity
		// that stays in scientific notation at every magnitude.
		expect(measurement({ value: 1.53e27 }, momentParts)).toBe('1.53×10²⁷ A·m²');
	});

	it('marks a moment that is only a bound', () => {
		// Titan's, which is a non-detection.
		expect(measurement({ value: 1.33e17, upper_limit: true }, momentParts)).toBe(
			'< 1.33×10¹⁷ A·m²'
		);
	});
});

describe('dipoleMomentNote', () => {
	it('reads a moment against the one everybody has a feel for', () => {
		expect(plain(dipoleMomentNote({ value: 1.53e27 }) ?? null)).toBe('19,900× Earth');
	});

	it('turns a moment below Earth’s into a percentage of it', () => {
		// Everything under parity reads as a percentage, whatever the quantity —
		// "0.0017× Earth" reads as a multiplication, and the two × in
		// "1.7×10⁻⁶× Earth" read as a typo.
		expect(plain(dipoleMomentNote({ value: 1.31e20 }) ?? null)).toBe("0.17% of Earth's");
	});

	it('drops to scientific notation before the decimals run out', () => {
		expect(plain(dipoleMomentNote({ value: 1.33e17, upper_limit: true }) ?? null)).toContain(
			"< 1.7×10⁻⁴% of Earth's"
		);
	});

	it('spells out what a bound is, after the comparison', () => {
		expect(plain(dipoleMomentNote({ value: 1.33e17, upper_limit: true }) ?? null)).toContain(
			'upper limit'
		);
	});

	it('has nothing to tell Earth about itself', () => {
		expect(dipoleMomentNote({ value: 7.69e22 })).toBeUndefined();
	});
});
