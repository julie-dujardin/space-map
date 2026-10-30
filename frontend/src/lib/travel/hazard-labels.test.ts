import { afterEach, describe, expect, it } from 'vitest';
import { ltrIsolate, quantityIsolate } from '$lib/format/bidi';
import {
	DUST_MASS_KG_M3,
	grainMassKg,
	largestGrainRadiusM,
	MEASURED_GRAIN_RADIUS_M
} from '$lib/math/travel/dust';
import { gasKineticMeV } from '$lib/math/travel/gas';
import { radiationShield } from '$lib/math/travel/shield';
import { LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import type { Hazard, HazardKind } from './hazards';
import {
	gasReading,
	hazardChip,
	hazardDetail,
	hazardName,
	hazardValue,
	shieldRows
} from './hazard-labels';

function hazard(kind: HazardKind, peak: number, auAtPeak?: number): Hazard {
	return { kind, severity: 'notice', startJd: 0, endJd: 0, peakJd: 0, peak, auAtPeak, bands: [] };
}

describe('hazard figures in the locale of the reader', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('writes solar power with the percent sign of the locale', () => {
		expect(hazardValue(hazard('solar-power', 0.45))).toBe('45% of Earth orbit');
		expect(hazardChip(hazard('solar-power', 0.032))).toBe('3.2% power');
		expect(hazardChip(hazard('solar-power', 47.2))).toBe('4,720% power');
		overwriteGetLocale(() => 'fr');
		expect(hazardValue(hazard('solar-power', 0.45))).toBe('45\u00a0% de l’orbite terrestre');
		expect(hazardChip(hazard('solar-power', 0.032))).toBe('3,2\u00a0% d’énergie');
		overwriteGetLocale(() => 'ar');
		expect(hazardValue(hazard('solar-power', 0.45))).toBe('45\u200e%\u200e من مدار الأرض');
	});

	it('writes heat, distance and angle with the decimals of the locale', () => {
		overwriteGetLocale(() => 'de');
		expect(hazardValue(hazard('solar-heat', 4.83, 0.455))).toBe('4,8× Sonnenlicht');
		expect(hazardDetail(hazard('solar-heat', 4.83, 0.455), 'Erde')).toContain('0,46');
		expect(hazardDetail(hazard('solar-power', 0.032, 5.6), 'Erde')).toContain('5,6');
		expect(hazardValue(hazard('conjunction', 1.53))).toBe('1,5° von der Sonne');
	});
});

const C2 = (SPEED_OF_LIGHT_KM_S * 1000) ** 2;

/** The dust of a trip over `ly`, as the kernel gives it. `excess` is γ − 1 at
 *  top speed, and `meanExcess` its mean over the trip. */
function dust(ly: number, excess: number, meanExcess: number): Hazard {
	const distanceM = ly * LIGHT_YEAR_KM * 1000;
	const radiusM = largestGrainRadiusM(distanceM / 1000);
	const massKg = grainMassKg(radiusM);
	return {
		...hazard('dust', excess * massKg * C2),
		dust: {
			radiusM,
			massKg,
			extrapolated: radiusM > MEASURED_GRAIN_RADIUS_M,
			energyJPerM2: DUST_MASS_KG_M3 * C2 * meanExcess * distanceM
		}
	};
}

/** Nostalgia for Infinity to Proxima at 1 g, flat out: 0.9497 c at the midpoint. */
function torchToProxima(): Hazard {
	const excess = 1 / Math.sqrt(1 - 0.9497 ** 2) - 1;
	return dust(4.24, excess, excess / 2);
}

/** A coast to Proxima at 40 km/s, where γ − 1 is ½(v/c)². */
function coastToProxima(): Hazard {
	const excess = 0.5 * (40 / SPEED_OF_LIGHT_KM_S) ** 2;
	return dust(4.24, excess, excess);
}

describe('dust labels', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('gives the largest grain as a diameter, and its energy with an SI prefix', () => {
		const torch = torchToProxima();
		expect(hazardName('dust')).toBe('Interstellar dust');
		expect(hazardChip(torch)).toBe('460\u00a0MJ impact');
		expect(hazardValue(torch)).toBe(
			`${quantityIsolate('110\u00a0µm')} grain, ${ltrIsolate('460\u00a0MJ')}`
		);
		expect(hazardDetail(torch, 'Earth')).toBe(
			`The largest grain expected to hit each square metre of frontal area is ${quantityIsolate('110\u00a0µm')} across and carries ${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} of TNT) of kinetic energy at top speed. All grains together deposit ${ltrIsolate('17\u00a0GJ')} (${ltrIsolate('4.1\u00a0t')} of TNT) per square metre over the trip. The abundance of grains this large is extrapolated from measurements of grains up to ${quantityIsolate('6\u00a0µm')} across.`
		);
		const coast = coastToProxima();
		expect(hazardChip(coast)).toBe('1.9\u00a0J impact');
		expect(hazardValue(coast)).toBe(
			`${quantityIsolate('110\u00a0µm')} grain, ${ltrIsolate('1.9\u00a0J')}`
		);
		expect(hazardDetail(coast, 'Earth')).toContain(
			`deposit ${ltrIsolate('140\u00a0J')} per square`
		);
	});

	it('gives the TNT equivalent of a joule figure from 1 g of TNT', () => {
		const torch = torchToProxima();
		// 1 g of TNT is 4.184 kJ. Below it the figure is in joules only.
		const detail = (peak: number, total: number) =>
			hazardDetail({ ...torch, peak, dust: { ...torch.dust!, energyJPerM2: total } }, 'Earth');
		expect(detail(4184, 4.184e15)).toContain(
			`carries ${ltrIsolate('4.2\u00a0kJ')} (${ltrIsolate('1\u00a0g')} of TNT) of`
		);
		expect(detail(4184, 4.184e15)).toContain(
			`deposit ${ltrIsolate('4.2\u00a0PJ')} (${ltrIsolate('1\u00a0Mt')} of TNT) per`
		);
		expect(detail(4000, 4.184e15)).toContain(`carries ${ltrIsolate('4\u00a0kJ')} of`);
		// The value line has no room for it.
		expect(hazardValue(torch)).not.toContain('TNT');
		expect(hazardChip(torch)).not.toContain('TNT');
	});

	it('says the size is extrapolated only past the measured grains', () => {
		const measured = torchToProxima();
		measured.dust = { ...measured.dust!, radiusM: 1e-6, extrapolated: false };
		const detail = hazardDetail(measured, 'Earth');
		expect(detail).toContain(`is ${quantityIsolate('2\u00a0µm')} across`);
		expect(detail).not.toContain('extrapolated');
	});

	it('climbs to millimetres and to the next prefix after rounding', () => {
		// At 10,000 ly the largest grain is 1.2 mm across.
		const far = dust(10_000, 1e3, 1e3);
		expect(hazardValue(far)).toMatch(new RegExp(`^${quantityIsolate('1\\.2\u00a0mm')} grain, `));
		// 999.7 MJ rounds to 1 GJ, not to 1,000 MJ.
		expect(hazardChip({ ...far, peak: 999.7e6 })).toBe('1\u00a0GJ impact');
	});

	it('writes the dust figures in French', () => {
		overwriteGetLocale(() => 'fr');
		const coast = coastToProxima();
		expect(hazardChip(coast)).toBe('impact de 1,9\u00a0J');
		expect(hazardValue(coast)).toBe(
			`grain de ${quantityIsolate('110\u00a0µm')}, ${ltrIsolate('1,9\u00a0J')}`
		);
		expect(hazardDetail(torchToProxima(), 'Terre')).toBe(
			`Le plus gros grain attendu sur chaque mètre carré de surface frontale mesure ${quantityIsolate('110\u00a0µm')} de diamètre et porte ${ltrIsolate('460\u00a0MJ')} (${ltrIsolate('110\u00a0kg')} de TNT) d’énergie cinétique à la vitesse maximale. Tous les grains réunis déposent ${ltrIsolate('17\u00a0GJ')} (${ltrIsolate('4,1\u00a0t')} de TNT) par mètre carré sur l’ensemble du trajet. L’abondance de grains aussi gros est extrapolée à partir de mesures de grains d’au plus ${quantityIsolate('6\u00a0µm')} de diamètre.`
		);
	});

	it('writes the dust figures in Arabic with the symbols marked left to right', () => {
		overwriteGetLocale(() => 'ar');
		const coast = coastToProxima();
		expect(hazardChip(coast)).toBe('اصطدام 1.9\u00a0\u200eJ\u200e');
		expect(hazardValue(coast)).toBe(
			`حبيبة ${quantityIsolate('110\u00a0\u200eµm\u200e')}، ${ltrIsolate('1.9\u00a0\u200eJ\u200e')}`
		);
		const detail = hazardDetail(torchToProxima(), 'الأرض');
		expect(detail).toContain(quantityIsolate('110\u00a0\u200eµm\u200e'));
		expect(detail).toContain(
			`${ltrIsolate('460\u00a0\u200eMJ\u200e')} (ما يعادل ${ltrIsolate('110\u00a0\u200ekg\u200e')} من مادة TNT)`
		);
		expect(detail).toContain(ltrIsolate('17\u00a0\u200eGJ\u200e'));
		expect(detail).toContain(`إلى ${quantityIsolate('6\u00a0\u200eµm\u200e')}.`);
	});

	it('isolates each measure of the value line in Arabic and Hebrew', () => {
		const cases = [
			{ locale: 'ar', size: '110\u00a0\u200eµm\u200e', energy: '460\u00a0\u200eMJ\u200e' },
			{ locale: 'he', size: '110\u00a0µm', energy: '460\u00a0MJ' }
		] as const;
		for (const { locale, size, energy } of cases) {
			overwriteGetLocale(() => locale);
			const value = hazardValue(torchToProxima());
			expect(isolates(value)).toEqual([size, energy]);
			// No figure stays outside an isolate to join the run beside it.
			expect(value.replace(ISOLATE, '')).not.toMatch(/\d/);
		}
	});

	it('isolates each joule figure and its TNT equivalent apart in Arabic and Hebrew', () => {
		const cases = [
			{ locale: 'ar', energy: '460\u00a0\u200eMJ\u200e', tnt: '110\u00a0\u200ekg\u200e' },
			{ locale: 'he', energy: '460\u00a0MJ', tnt: '110\u00a0kg' }
		] as const;
		for (const { locale, energy, tnt } of cases) {
			overwriteGetLocale(() => locale);
			const detail = hazardDetail(torchToProxima(), '');
			expect(isolates(detail).slice(1, 3)).toEqual([energy, tnt]);
			expect(detail.replace(ISOLATE, '')).not.toMatch(/\d/);
		}
	});
});

/** A gas row as the kernel gives it: the trip total and the rate at the peak speed. */
function gas(sv: number, svPerDay: number): Hazard {
	return { ...hazard('gas', sv), severity: 'severe', rateAtPeak: svPerDay, shipTime: true };
}

/** Nostalgia for Infinity to Proxima at 1 g, flat out, from the kernel. */
const NOSTALGIA_GAS = gas(7.78e8, 1.766e6);

/** The same trip on the longest coast, which peaks at 0.12 c. */
const NOSTALGIA_COAST_GAS = gas(3.04e4, 2.379);

describe('gas labels', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('writes a dose of 10⁸ Sv with an exponent, and names the gas on the chip', () => {
		expect(hazardName('gas')).toBe('Interstellar gas');
		expect(hazardValue(NOSTALGIA_GAS)).toBe(ltrIsolate('7.8×10⁸\u00a0Sv'));
		expect(hazardChip(NOSTALGIA_GAS)).toBe(`${ltrIsolate('7.8×10⁸\u00a0Sv')} gas`);
		expect(hazardValue(NOSTALGIA_COAST_GAS)).toBe('30,000 Sv');
	});

	it('says what the figure is, and that it is many lethal doses', () => {
		expect(hazardDetail(NOSTALGIA_GAS, 'Earth')).toBe(
			`At relativistic speed, interstellar gas that hits the front of the craft becomes ionising radiation and knocks neutrons out of the hull. On this trip the dose is up to ${ltrIsolate(ltrIsolate('1.8×10⁶\u00a0Sv'))} per day of ship time with no shielding. The total is many times a lethal dose.`
		);
		expect(hazardDetail(NOSTALGIA_COAST_GAS, 'Earth')).toContain(
			`is up to ${ltrIsolate('2.4 Sv')} per day of ship time`
		);
		expect(hazardDetail(NOSTALGIA_COAST_GAS, 'Earth')).toContain('many times a lethal dose.');
	});

	it('gives the cancer risk while the linear model holds', () => {
		expect(gasReading(10)).toBe('risk');
		expect(hazardDetail(gas(10, 3), 'Earth')).toMatch(
			new RegExp(
				`of ship time with no shielding\\. About ${ltrIsolate('41%')} added lifetime cancer risk\\.$`
			)
		);
	});

	it('says many lethal doses only where it holds at any quality factor', () => {
		// The linear model ends at 24 Sv. A lethal dose is 4.5 Gy, and Q(L) is at
		// most 30, so five lethal doses are sure from 675 Sv.
		expect(gasReading(24)).toBe('risk');
		expect(gasReading(25)).toBe('past-model');
		expect(gasReading(674)).toBe('past-model');
		expect(gasReading(675)).toBe('lethal');
		expect(hazardDetail(gas(100, 20), 'Earth')).toMatch(
			/of ship time with no shielding\. The cancer risk estimate does not hold at this dose\.$/
		);
	});

	it('writes the gas row in French and Arabic', () => {
		overwriteGetLocale(() => 'fr');
		expect(hazardChip(NOSTALGIA_GAS)).toBe(`${ltrIsolate('7,8×10⁸\u00a0Sv')} de gaz`);
		expect(hazardDetail(NOSTALGIA_GAS, 'Terre')).toMatch(
			/^À vitesse relativiste, .* va jusqu'à .* par jour de temps à bord sans blindage\. Le total équivaut à de nombreuses doses létales\.$/
		);
		overwriteGetLocale(() => 'ar');
		expect(hazardName('gas')).toBe('الغاز بين النجمي');
		expect(hazardChip(NOSTALGIA_GAS)).toBe(`غاز ${ltrIsolate('7.8×10⁸\u00a0\u200eSv\u200e')}`);
		const detail = hazardDetail(NOSTALGIA_GAS, 'الأرض');
		expect(isolates(detail)).toEqual(['1.8×10⁶\u00a0\u200eSv\u200e']);
		expect(detail.replace(ISOLATE, '')).not.toMatch(/\d/);
	});
});

/** The shield of a crossing whose top speed is `beta` c. */
function shieldAt(beta: number) {
	return radiationShield(gasKineticMeV(Math.atanh(beta)));
}

/** A coast at 40 km/s: the craft is as good as at rest. */
const COAST_SHIELD = shieldAt(40 / SPEED_OF_LIGHT_KM_S);

describe('radiation shield labels', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it('splits the shield into a front and sides at 0.95 c', () => {
		const shield = shieldAt(0.95);
		expect(shield.frontIceM).toBeCloseTo(29.8, 1);
		expect(shield.frontIronM).toBeCloseTo(5.1, 1);
		expect(shield.sideIceM).toBeCloseTo(3.3, 1);
		expect(shieldRows(shield)).toEqual([
			{
				name: 'Frontal shield',
				value: `${quantityIsolate('30\u00a0m')} of ice`,
				detail: `Ice this thick at the front of the craft brings the dose from the gas and the cosmic rays ahead down to ${ltrIsolate('0.6\u00a0mSv')} per day at top speed, the average on the ISS. Iron does the same in ${quantityIsolate('5.1\u00a0m')}, with ${quantityIsolate('60\u00a0cm')} of concrete behind it to stop the slow neutrons that pass through the iron.`
			},
			{
				name: 'Side shield',
				value: `${quantityIsolate('3.3\u00a0m')} of ice`,
				detail: `Ice this thick on the sides and back brings the cosmic-ray dose down to ${ltrIsolate('0.6\u00a0mSv')} per day while the craft is slow, the average on the ISS. It also stops the protons of solar storms, so the crew needs no separate storm shelter.`
			}
		]);
	});

	it('gives a coast one shield all round', () => {
		expect(shieldRows(COAST_SHIELD)).toEqual([
			{
				name: 'Radiation shield',
				value: `${quantityIsolate('3.3\u00a0m')} of ice`,
				detail: `Ice this thick all round the craft brings the radiation dose down to ${ltrIsolate('0.6\u00a0mSv')} per day, the average on the ISS. It also stops the protons of solar storms, so the crew needs no separate storm shelter.`
			}
		]);
	});

	it('gives one shield at the front value while the front is not clearly thicker', () => {
		const rows = shieldRows(shieldAt(0.2));
		expect(rows.map((row) => row.name)).toEqual(['Radiation shield']);
		expect(rows[0].value).toBe(`${quantityIsolate('4\u00a0m')} of ice`);
		// The front becomes a shield of its own at about 0.28 c.
		expect(shieldRows(shieldAt(0.27))).toHaveLength(1);
		expect(shieldRows(shieldAt(0.29)).map((row) => row.name)).toEqual([
			'Frontal shield',
			'Side shield'
		]);
	});

	it('isolates each figure of the shield rows in Arabic and Hebrew', () => {
		const cases = [
			{
				locale: 'ar',
				name: 'درع أمامي',
				figures: ['0.6\u00a0\u200emSv\u200e', '5.1\u00a0\u200em\u200e', '60\u00a0\u200ecm\u200e'],
				side: '3.3\u00a0\u200em\u200e'
			},
			{
				locale: 'he',
				name: 'מגן קדמי',
				figures: ['0.6\u00a0mSv', '5.1\u00a0מ׳', '60\u00a0ס״מ'],
				side: '3.3\u00a0מ׳'
			}
		] as const;
		for (const { locale, name, figures, side } of cases) {
			overwriteGetLocale(() => locale);
			const [front, sides] = shieldRows(shieldAt(0.95));
			expect(front.name).toBe(name);
			expect(isolates(front.detail)).toEqual(figures);
			expect(isolates(sides.value)).toEqual([side]);
			for (const text of [front.value, front.detail, sides.value, sides.detail]) {
				expect(text.replace(ISOLATE, '')).not.toMatch(/\d/);
			}
		}
	});
});

/** An LRI…PDI isolate and the text in it. */
const ISOLATE = /[\u2066\u2068]([^\u2066\u2068\u2069]*)\u2069/g;

/** The text in each isolate, in order. */
function isolates(text: string): string[] {
	return [...text.matchAll(ISOLATE)].map((match) => match[1]);
}
