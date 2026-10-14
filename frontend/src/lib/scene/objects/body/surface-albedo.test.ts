import { describe, it, expect, vi } from 'vitest';
import { Color, Texture } from 'three';
import { lunarLambertGain } from '../surface/photometry';
import { planetshineFraction } from '../surface/planetshine';
import {
	discAlbedoPerColour,
	shinerAlbedo,
	surfaceAlbedoTarget,
	untexturedSurfaceColour
} from './surface-albedo';

vi.mock('$lib/fetch/atmospheres', () => ({
	getAtmosphereParams: (id: string) =>
		({ 'naif-499': {}, 'naif-606': { deepColumn: {} } })[id as 'naif-499' | 'naif-606']
}));

const MEAN = new Color(0.2, 0.1, 0.05);
vi.mock('./texture-tint', () => ({
	meanMapColor: (map: Texture) => (map.image ? MEAN : null)
}));

function luminance(c: Color): number {
	return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

/** Geometric albedo of a disc at phase 0 with material colour 1, from the
 *  law the shader applies: the mean over the disc of `mu0` times the gain. */
function discAlbedo(gain: (mu: number) => number): number {
	const n = 400;
	let sum = 0;
	let count = 0;
	for (let i = 0; i < n; i++) {
		for (let j = 0; j < n; j++) {
			const x = ((i + 0.5) / n) * 2 - 1;
			const y = ((j + 0.5) / n) * 2 - 1;
			const r2 = x * x + y * y;
			if (r2 >= 1) continue;
			const mu = Math.sqrt(1 - r2);
			sum += mu * gain(mu);
			count++;
		}
	}
	return sum / count;
}

describe('discAlbedoPerColour', () => {
	it('is 2/3 under the Lambert law', () => {
		expect(discAlbedoPerColour(false)).toBeCloseTo(
			discAlbedo(() => 1),
			3
		);
	});

	it('follows the lunar-Lambert law of the shader', () => {
		for (const scale of [undefined, 0.388, 0.716, 1.125]) {
			const law = discAlbedo((mu) => lunarLambertGain(0, mu, mu, scale ?? 1));
			expect(discAlbedoPerColour(true, scale)).toBeCloseTo(law, 3);
		}
	});
});

describe('surfaceAlbedoTarget', () => {
	it('is null with no measured colour', () => {
		expect(surfaceAlbedoTarget({ id: 'naif-301' })).toBeNull();
	});

	it('is the luminance of the colour on an airless body', () => {
		const target = surfaceAlbedoTarget({ id: 'naif-301', color: '#6f5e54' });
		expect(target).toBeCloseTo(luminance(new Color('#6f5e54')), 6);
	});

	it('takes the albedo over the hex where it is given', () => {
		expect(
			surfaceAlbedoTarget({ id: 'naif-602', color: '#ffffff', geometricAlbedo: 1.375 })
		).toBeCloseTo(1.375, 6);
	});

	it('is 3/2 of the albedo under the Lambert law', () => {
		expect(
			surfaceAlbedoTarget({ id: 'naif-499', color: '#808080', geometricAlbedo: 0.17 })
		).toBeCloseTo(0.255, 6);
	});

	it('is above the albedo where the lunar weight is below 1', () => {
		const target = surfaceAlbedoTarget({
			id: 'naif-602',
			color: '#ffffff',
			geometricAlbedo: 1.375,
			lunarWeightScale: 0.388
		});
		expect(target).toBeCloseTo(1.375 / ((2 + 0.388) / 3), 6);
	});
});

describe('untexturedSurfaceColour', () => {
	it('keeps the hue at the target', () => {
		const body = { id: 'naif-499', color: '#7d5040', geometricAlbedo: 0.17 };
		const colour = untexturedSurfaceColour(body);
		const hex = new Color(body.color);
		expect(luminance(colour)).toBeCloseTo(surfaceAlbedoTarget(body)!, 6);
		expect(colour.g / colour.r).toBeCloseTo(hex.g / hex.r, 6);
		expect(colour.b / colour.r).toBeCloseTo(hex.b / hex.r, 6);
	});

	it('is the stand-in with no measured colour', () => {
		expect(untexturedSurfaceColour({ id: 'spkid-1' }).getHexString()).toBe('6b6b6b');
	});
});

describe('shinerAlbedo', () => {
	const map = new Texture({ width: 2, height: 1 });

	it('gives a full disc of the geometric albedo under the planetshine model', () => {
		const albedo = shinerAlbedo({ id: 'naif-499', geometricAlbedo: 0.17 }, map, new Color())!;
		const k = 0.36;
		expect(planetshineFraction(k, 1, 0) * luminance(albedo)).toBeCloseTo(0.17 * k * k, 9);
	});

	it('takes the hue of the map where the body has no colour', () => {
		const albedo = shinerAlbedo({ id: 'naif-599', geometricAlbedo: 0.538 }, map, new Color())!;
		expect(luminance(albedo)).toBeCloseTo(1.5 * 0.538, 6);
		expect(albedo.g / albedo.r).toBeCloseTo(MEAN.g / MEAN.r, 6);
	});

	it('takes the hue and the albedo of the colour', () => {
		const albedo = shinerAlbedo({ id: 'naif-301', color: '#6f5e54' }, map, new Color())!;
		const hex = new Color('#6f5e54');
		expect(luminance(albedo)).toBeCloseTo(1.5 * luminance(hex), 6);
		expect(albedo.b / albedo.r).toBeCloseTo(hex.b / hex.r, 6);
	});

	it('is null for a body with no albedo', () => {
		expect(shinerAlbedo({ id: 'spkid-1' }, map, new Color())).toBeNull();
	});
});
