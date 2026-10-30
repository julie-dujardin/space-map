import { afterEach, describe, expect, it } from 'vitest';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import { ltrIsolate } from './bidi';
import { formatJoules, formatJoulesWithTnt, jouleParts, tntParts } from './energy';

describe('formatJoules', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('picks the prefix that keeps the figure at 1 or more', () => {
		expect(formatJoules(0.042)).toBe('42\u00a0mJ');
		expect(formatJoules(3.38)).toBe('3.4\u00a0J');
		expect(formatJoules(8.33e8)).toBe('830\u00a0MJ');
		expect(formatJoules(3.9e11)).toBe('390\u00a0GJ');
		expect(formatJoules(2e18)).toBe('2\u00a0EJ');
		expect(formatJoules(2e21)).toBe('2,000\u00a0EJ');
		expect(formatJoules(2e-5)).toBe('0.02\u00a0mJ');
	});

	it('rounds before it picks the prefix', () => {
		expect(formatJoules(999.7e6)).toBe('1\u00a0GJ');
		expect(formatJoules(999.7e6, 4)).toBe('999.7\u00a0MJ');
	});

	it('gives no figure for a value that is not finite', () => {
		expect(jouleParts(NaN)).toEqual({ value: '—', unit: '' });
	});

	it('writes the prefix of the locale', () => {
		overwriteGetLocale(() => 'ru');
		expect(formatJoules(3.38e3)).toBe('3,4\u00a0кДж');
		overwriteGetLocale(() => 'ar');
		expect(formatJoules(3.38e9)).toBe('3.4\u00a0‎GJ‎');
	});
});

describe('the TNT equivalent', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('starts at 1 g of TNT, which is 4.184 kJ', () => {
		expect(tntParts(4184)).toEqual({ value: '1', unit: 'g' });
		expect(tntParts(4100)).toBeNull();
		expect(tntParts(0)).toBeNull();
		expect(tntParts(NaN)).toBeNull();
		// 0.999 g rounds to 1 g before the floor is applied, as the joules round.
		expect(tntParts(4180)).toEqual({ value: '1', unit: 'g' });
	});

	it('climbs from grams to gigatonnes after rounding', () => {
		const tnt = (joules: number) => {
			const parts = tntParts(joules);
			return parts && `${parts.value} ${parts.unit}`;
		};
		expect(tnt(4.6e8)).toBe('110 kg');
		expect(tnt(1.73e10)).toBe('4.1 t');
		expect(tnt(4.184e12)).toBe('1 kt');
		expect(tnt(6.3e13)).toBe('15 kt');
		expect(tnt(4.184e15)).toBe('1 Mt');
		expect(tnt(4.184e18)).toBe('1 Gt');
		expect(tnt(4.184e21)).toBe('1,000 Gt');
		// 999.7 kg rounds to 1 t, not to 1,000 kg.
		expect(tnt(999.7 * 4184e3)).toBe('1 t');
	});

	it('puts the TNT equivalent beside the joules, each measure in its own isolate', () => {
		expect(formatJoulesWithTnt(4.6e8)).toBe(
			`${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} of TNT)`
		);
		expect(formatJoulesWithTnt(1.9)).toBe(ltrIsolate('1.9\u00a0J'));
	});

	it('says TNT equivalent the way each language does', () => {
		const cases = [
			['fr', `${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} de TNT)`],
			['de', `${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} TNT-Äquivalent)`],
			[
				'ru',
				`${ltrIsolate('460\u00a0МДж')} (${ltrIsolate('110\u00a0кг')} в тротиловом эквиваленте)`
			],
			['ja', `${ltrIsolate('460\u00a0MJ')}（TNT換算 ${ltrIsolate('110\u00a0kg')}）`],
			['zh', `${ltrIsolate('460\u00a0MJ')}（${ltrIsolate('110\u00a0kg')} TNT当量）`],
			['pl', `${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} trotylu)`],
			[
				'ar',
				`${ltrIsolate('460\u00a0\u200eMJ\u200e')} (ما يعادل ${ltrIsolate('110\u00a0\u200ekg\u200e')} من مادة TNT)`
			],
			['he', `${ltrIsolate('460\u00a0MJ')} (שווה ערך ל־${ltrIsolate('110\u00a0kg')} של TNT)`]
		] as const;
		for (const [locale, text] of cases) {
			overwriteGetLocale(() => locale);
			expect(formatJoulesWithTnt(4.6e8)).toBe(text);
		}
		overwriteGetLocale(() => 'ru');
		expect(formatJoulesWithTnt(6.3e13)).toContain(ltrIsolate('15\u00a0кт'));
	});
});
