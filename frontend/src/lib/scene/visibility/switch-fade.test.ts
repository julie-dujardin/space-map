import { describe, expect, it } from 'vitest';
import { SYSTEM_SWITCH_FADE_MS, SwitchFade } from './switch-fade';

describe('a switch fade', () => {
	it('with no start, starts where its first step asks', () => {
		const fade = new SwitchFade();
		fade.step(false, 16);
		expect(fade.share).toBe(0);
		expect(fade.fading).toBe(false);
	});

	it('with a start, fades from it on its first step', () => {
		const fade = new SwitchFade(false);
		fade.step(true, SYSTEM_SWITCH_FADE_MS / 2);
		expect(fade.share).toBeCloseTo(0.5, 12);
		expect(fade.fading).toBe(true);
	});

	it('runs out over its time once the switch flips, with no further change', () => {
		const fade = new SwitchFade(true);
		fade.step(false, SYSTEM_SWITCH_FADE_MS / 2);
		expect(fade.share).toBeCloseTo(0.5, 12);
		expect(fade.fading).toBe(true);
		fade.step(false, SYSTEM_SWITCH_FADE_MS / 2);
		expect(fade.share).toBe(0);
		expect(fade.fading).toBe(false);
	});

	it('stays at its end while the switch holds', () => {
		for (const on of [true, false]) {
			const fade = new SwitchFade(on);
			for (let i = 0; i < 4; i++) fade.step(on, 33);
			expect(fade.share).toBe(on ? 1 : 0);
			expect(fade.fading).toBe(false);
		}
	});

	it('turns back from where it is', () => {
		const fade = new SwitchFade(false);
		fade.step(true, SYSTEM_SWITCH_FADE_MS / 4);
		const part = fade.share;
		expect(part).toBeGreaterThan(0);
		fade.step(false, SYSTEM_SWITCH_FADE_MS / 8);
		expect(fade.share).toBeLessThan(part);
		fade.step(false, SYSTEM_SWITCH_FADE_MS);
		expect(fade.share).toBe(0);
	});
});
