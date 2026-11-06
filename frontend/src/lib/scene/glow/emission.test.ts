import { describe, expect, it } from 'vitest';
import { NestFormatError } from '$lib/scene/dust/nest';
import {
	ALL_PARTS,
	NO_PARTS,
	checkEmission,
	emissionGlsl,
	emissionSamplers,
	lineDepth,
	scatterColours,
	type GlowEmission
} from './emission';
import { glslFloat } from '$lib/scene/dust/glsl';

/** The emission block as the export writes it, with a small colour table. */
function block(): GlowEmission {
	const rgb = Array.from({ length: 3 }, (_, k) =>
		Array.from({ length: 4 }, (_, i) => [0.5 - 0.1 * i, 0.3, 0.2 + 0.1 * i + 0.01 * k])
	) as GlowEmission['scatter']['form']['colour']['rgb'];
	return {
		lines: { colour: [0.793347, 0.071671, 0.134982], k_rgb: [0.7954, 1.2237, 1.2237] },
		halpha: {
			model: true,
			half_extent_pc: [1250, 1250, 1250],
			tiers: {
				high: {
					size: [256, 256, 256],
					floor: 9.6e-10,
					top: 0.02295,
					path: 'high/halpha.bin.gz',
					bytes: 1
				},
				low: {
					size: [128, 128, 128],
					floor: 9.5e-10,
					top: 0.02264,
					path: 'low/halpha.bin.gz',
					bytes: 1
				}
			}
		},
		scatter: {
			model: true,
			albedo: [0.6757, 0.6774, 0.671],
			tau_per_mag: 0.9210340371976184,
			centre_pc: [8277, 0, -21],
			half_extent_pc: [24000, 24000, 3000],
			z_map: 'asinh',
			z_scale_pc: 150,
			form: {
				channels: 1,
				texture_scale: 512,
				shield: {
					log10_density_nodes: [-5, -4.5, -4, -3.5, -3, -2.5, -2, -1.5, -1, -0.5, 0],
					factor: [1, 1, 1, 0.999, 0.9844, 0.9247, 0.8228, 0.6693, 0.5672, 0.5672, 0.5672]
				},
				colour: { radii: 4, r_max_pc: 30000, distances: 3, d_scale_pc: 1000, d_max_pc: 40000, rgb }
			},
			tiers: {
				high: { size: [128, 128, 16], path: 'high/scatter.bin.gz', bytes: 1 },
				low: { size: [64, 64, 8], path: 'low/scatter.bin.gz', bytes: 1 }
			}
		},
		regions: { path: 'regions.bin.gz', bytes: 1, rows: 1401 }
	};
}

describe('the emission block', () => {
	it('passes as the export writes it', () => {
		expect(() => checkEmission(block())).not.toThrow();
	});

	it('is a format error where the march could not read it', () => {
		const cases: ((e: GlowEmission) => void)[] = [
			(e) => (e.scatter.form.channels = 3),
			(e) => (e.scatter.form.colour.rgb = e.scatter.form.colour.rgb.slice(1)),
			(e) => (e.scatter.form.colour.rgb[0] = e.scatter.form.colour.rgb[0].slice(1)),
			(e) => (e.scatter.form.shield.log10_density_nodes[3] = -3.4),
			(e) => (e.scatter.form.shield.factor = [1, 1]),
			(e) => (e.halpha.tiers.low.top = 0),
			(e) => (e.scatter.z_scale_pc = 0),
			(e) => (e.halpha.half_extent_pc = [1250, 0, 1250])
		];
		for (const change of cases) {
			const e = block();
			change(e);
			expect(() => checkEmission(e)).toThrow(NestFormatError);
		}
	});
});

describe('the scattered light’s colour table', () => {
	it('lies radius across and distance down, as a texture of radii by distances', () => {
		const e = block();
		const texels = scatterColours(e);
		expect(texels.length).toBe(4 * 3 * 4);
		const at = (i: number, k: number) =>
			Array.from(texels.slice(4 * (k * 4 + i), 4 * (k * 4 + i) + 4));
		expect(at(2, 1)).toEqual([...e.scatter.form.colour.rgb[1][2], 1].map((x) => Math.fround(x)));
		expect(at(0, 2)).toEqual([...e.scatter.form.colour.rgb[2][0], 1].map((x) => Math.fround(x)));
	});
});

describe('the march’s emission terms', () => {
	it('dim the lines at their own K, not the stars’', () => {
		const depth = lineDepth(block());
		expect(depth[0]).toBeCloseTo(0.4 * Math.LN10 * 0.7954, 6);
		expect(depth[1]).toBeCloseTo(0.4 * Math.LN10 * 1.2237, 6);
	});

	it('read H-alpha with the floor and top of the tier, and J only where there is dust', () => {
		const high = emissionGlsl(block(), ALL_PARTS, 'high', 128);
		const low = emissionGlsl(block(), ALL_PARTS, 'low', 128);
		expect(high).toContain('lineLight');
		expect(high).toContain('scatteredLight');
		expect(high).toContain('if (rho <= 0.0) return vec3(0.0);');
		expect(high).toContain(glslFloat(9.6e-10 * 128));
		expect(low).toContain(glslFloat(9.5e-10 * 128));
		expect(high).toContain(glslFloat(Math.log1p(0.02295 / 9.6e-10)));
	});

	it('keep the decode factor of H-alpha on a small grid scale', () => {
		const text = emissionGlsl(block(), ALL_PARTS, 'high', 1 / 16);
		const factor = /vec3 j = (\S+) \*/.exec(text)![1];
		expect(Number(factor)).toBeGreaterThan(0);
		expect(Math.fround(Number(factor))).toBe(Math.fround(9.6e-10 / 16));
	});

	it('keep every fetch inside an if, never in a ternary', () => {
		const text = emissionGlsl(block(), ALL_PARTS, 'high', 128);
		for (const line of text.split('\n').filter((l) => l.includes('texture'))) {
			expect(line).not.toContain('?');
		}
	});

	it('hold nothing, and read no texture, for parts that are off', () => {
		expect(emissionGlsl(block(), NO_PARTS, 'high', 128)).toBe('');
		expect(emissionSamplers(NO_PARTS)).toEqual([]);
		const halpha = { halpha: true, scatter: false, regions: true };
		expect(emissionGlsl(block(), halpha, 'high', 128)).not.toContain('uScatterJ');
		expect(emissionSamplers(halpha)).toEqual(['uHalpha']);
		expect(emissionSamplers(ALL_PARTS)).toEqual(['uHalpha', 'uScatterJ', 'uScatterColour']);
	});

	it('scale J by the albedo, the stars’ K and tau per mag, on the grid’s scale', () => {
		const e = block();
		const text = emissionGlsl(e, { halpha: false, scatter: true, regions: false }, 'high', 128);
		const k = e.scatter.albedo[0] * 0.863 * e.scatter.tau_per_mag * (128 / 512);
		expect(text).toContain(glslFloat(k));
	});
});
