import { describe, expect, it } from 'vitest';
import { WITHIN_SYSTEM_SWITCH_FADE_MS } from './switch-fade';
import { VisibilityThresholdFades } from './threshold-fade';

describe('visibility threshold fades', () => {
	it('snaps the initial state', () => {
		const fades = new VisibilityThresholdFades();
		fades.beginFrame(16);
		expect(fades.labelShare('moon', false)).toBe(0);
		expect(fades.orbitShare('moon', true)).toBe(1);
		expect(fades.fading).toBe(false);
	});

	it('fades label and orbit thresholds independently', () => {
		const fades = new VisibilityThresholdFades();
		fades.beginFrame(16);
		fades.labelShare('moon', true);
		fades.orbitShare('moon', false);

		fades.beginFrame(WITHIN_SYSTEM_SWITCH_FADE_MS / 2);
		expect(fades.labelShare('moon', false)).toBeCloseTo(0.5, 12);
		expect(fades.orbitShare('moon', true)).toBeCloseTo(0.5, 12);
		expect(fades.fading).toBe(true);

		fades.beginFrame(WITHIN_SYSTEM_SWITCH_FADE_MS / 2);
		expect(fades.labelShare('moon', false)).toBe(0);
		expect(fades.orbitShare('moon', true)).toBe(1);
		expect(fades.fading).toBe(false);
	});

	it('advances an entry at most once per frame', () => {
		const fades = new VisibilityThresholdFades();
		fades.beginFrame(16);
		fades.labelShare('moon', false);

		fades.beginFrame(WITHIN_SYSTEM_SWITCH_FADE_MS / 4);
		const share = fades.labelShare('moon', true);
		expect(fades.labelShare('moon', true)).toBe(share);
	});

	it('does not keep rendering entries outside the current system', () => {
		const fades = new VisibilityThresholdFades();
		fades.beginFrame(16);
		fades.labelShare('moon', true);
		fades.beginFrame(WITHIN_SYSTEM_SWITCH_FADE_MS / 4);
		fades.labelShare('moon', false);
		expect(fades.fading).toBe(true);

		fades.beginFrame(16);
		expect(fades.fading).toBe(false);
	});
});
