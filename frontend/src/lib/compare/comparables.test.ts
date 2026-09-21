import { describe, expect, it } from 'vitest';
import { MAX_FACTOR, pickComparable, TARGET_SPAN, type SizedComparable } from './comparables';

const sized = (slug: string, spanMetres: number): SizedComparable => ({
	slug,
	label: () => slug,
	radiusKm: spanMetres / 2000,
	flatness: 1
});

const BANANA = sized('banana', 0.2);
const BIKE = sized('bike', 1.8);
const CAR = sized('car', 4.66);
const BUS = sized('bus', 12.27);
const WHALE = sized('whale', 25);
const PITCH = sized('pitch', 105);
const EIFFEL = sized('eiffel', 330);
const BURJ = sized('burj', 828);
const ALL = [BANANA, BIKE, CAR, BUS, WHALE, PITCH, EIFFEL, BURJ];

/** A laptop's compare stage. */
const STAGE = 720;
/** The scale a row comes out at having drawn a body of `spanMetres` across
 *  `share` of the stage's height. */
const drawnAt = (spanMetres: number, share = 1) => (STAGE * share) / (spanMetres / 1000);
/** What a comparable takes of the stage's height, as the row draws it. */
const share = (c: SizedComparable, pxPerKm: number) => (c.radiusKm * 2 * pxPerKm) / STAGE;

/** Where the target share sits inside the band, as the picker reads it. */
const midpoint = Math.sqrt(TARGET_SPAN[0] * TARGET_SPAN[1]);

describe('pickComparable', () => {
	it('lands inside the target band', () => {
		for (const span of [4, 30, 94.5, 300, 2000]) {
			const scale = drawnAt(span);
			const picked = pickComparable(ALL, STAGE, scale);
			expect(picked).not.toBeNull();
			expect(share(picked!, scale)).toBeLessThanOrEqual(TARGET_SPAN[1]);
		}
	});

	it('reads the row, not the bodies', () => {
		// The ISS alone fills the stage and stands beside a whale. Crowded onto a
		// page with three of its own size, it is drawn a quarter as large — and a
		// third of the stage is now a football pitch, not a whale.
		expect(pickComparable(ALL, STAGE, drawnAt(94.5))).toBe(WHALE);
		expect(pickComparable(ALL, STAGE, drawnAt(94.5, 1 / 4))).toBe(PITCH);
	});

	it('steps down rather than overrun the band', () => {
		// Nearest in ratio is the pitch, but it would stand taller than a third
		// of the stage, so the whale is drawn instead.
		const scale = drawnAt(190);
		expect(share(PITCH, scale)).toBeGreaterThan(TARGET_SPAN[1]);
		expect(pickComparable(ALL, STAGE, scale)).toBe(WHALE);
	});

	it('shows nothing where even a banana would overrun', () => {
		// A 3U cubesat: nothing everyday is small enough beside it.
		expect(pickComparable(ALL, STAGE, drawnAt(0.3))).toBeNull();
	});

	it('has nothing to say before the row is measured', () => {
		expect(pickComparable(ALL, 0, drawnAt(10))).toBeNull();
		expect(pickComparable(ALL, STAGE, 0)).toBeNull();
	});

	it('leaves a page that has left everyday sizes behind', () => {
		expect(pickComparable(ALL, STAGE, drawnAt(2 * 2631.2 * 1000))).toBeNull(); // Ganymede
	});

	it('holds the window at the near end', () => {
		// The largest that still fits under the band is far below it: drawn at
		// MAX_FACTOR short of the target it is kept, a hair further it is not.
		const only = [sized('only', 100)];
		const scale = (factor: number) => drawnAt((100 / midpoint) * factor);
		expect(pickComparable(only, STAGE, scale(MAX_FACTOR))?.slug).toBe('only');
		expect(pickComparable(only, STAGE, scale(MAX_FACTOR * 1.01))).toBeNull();
	});
});
