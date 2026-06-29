import { describe, it, expect } from 'vitest';
import { frameFitPreference } from './trail';

/**
 * A probe trail samples in one fixed frame (`currentParentKey`). When the probe
 * appears in overlapping zones at the same jd (a flyby probe is in both the
 * interplanetary zone and the planet zone), the trail must resolve in its own
 * frame — otherwise the planet-zone samples are gated out and the encounter is
 * bridged with a straight line.
 */
describe('frameFitPreference', () => {
	it('a heliocentric trail prefers the Sun fit over an overlapping planet zone', () => {
		const pref = frameFitPreference('naif-10');
		expect(pref(10)).toBe(true); // interplanetary (Sun) — this trail's frame
		expect(pref(599)).toBe(false); // Jupiter zone the flyby probe also lives in
	});

	it('a planet-frame trail prefers its own planet fit', () => {
		const pref = frameFitPreference('naif-599');
		expect(pref(599)).toBe(true);
		expect(pref(10)).toBe(false);
	});

	it('an override frame (moon) matches no zone fit center, falling back to default order', () => {
		const pref = frameFitPreference('naif-901');
		expect(pref(699)).toBe(false); // Saturn zone fit center ≠ the moon override
		expect(pref(901)).toBe(true);
	});
});
