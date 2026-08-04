import { describe, it, expect } from 'vitest';
import { layerSpans } from './layer-appearance';
import type { InteriorLayer } from '$lib/fetch/objects/object-data';

function layer(role: string, temperature?: Partial<InteriorLayer>): InteriorLayer {
	return { role, outer_radius_km: 1, composition: [], ...temperature };
}

describe('layerSpans', () => {
	it('runs a layer between its own two boundaries', () => {
		// Earth's outer core: the core-mantle boundary above it, the inner-core
		// boundary below.
		const spans = layerSpans(
			[
				layer('mantle'),
				layer('outer_core', { outer_temperature_range_k: [3400, 4200] }),
				layer('inner_core', { outer_temperature_k: 5500, outer_temperature_range_k: [5000, 6000] })
			],
			null,
			288
		);
		expect(spans[1]).toEqual({ lowK: 3400, highK: 6000 });
	});

	it('closes the outermost layer on the surface', () => {
		const spans = layerSpans([layer('crust'), layer('mantle')], null, 288);
		expect(spans[0]).toEqual({ lowK: 288, highK: 288 });
	});

	it('closes the innermost layer on the centre', () => {
		const spans = layerSpans(
			[layer('convective_zone'), layer('core', { outer_temperature_k: 7e6 })],
			{ lowK: 15.5e6, highK: 15.7e6 },
			5772
		);
		expect(spans[1]).toEqual({ lowK: 7e6, highK: 15.7e6 });
	});

	it('gives a diffuse core the centre alone', () => {
		// Jupiter: nothing has a radius to hang a boundary on, so the centre is
		// the only reading the stack has.
		const spans = layerSpans(
			[layer('envelope'), layer('core')],
			{ lowK: 15000, highK: 36000 },
			null
		);
		expect(spans[1]).toEqual({ lowK: 15000, highK: 36000 });
	});

	it('refuses to report a floor as a shell', () => {
		// Earth's mantle has no Moho reading, and the core-mantle boundary below
		// it describes where it ends rather than what it is.
		const spans = layerSpans(
			[layer('crust'), layer('mantle'), layer('core', { outer_temperature_range_k: [3400, 4200] })],
			null,
			288
		);
		expect(spans[1]).toBeNull();
	});

	it('leaves an unconstrained body blank throughout', () => {
		const spans = layerSpans([layer('ice_shell'), layer('core')], null, null);
		expect(spans).toEqual([null, null]);
	});
});
