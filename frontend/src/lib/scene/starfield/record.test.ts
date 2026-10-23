import { describe, expect, it } from 'vitest';
import { nodeInfo, type Container, type NodeInfo } from '$lib/fetch/extrasolar/container';
import { ExtrasolarLookup, homeRow } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource, readExportFile } from '$lib/fetch/extrasolar/__fixtures__/export';
import { absoluteG, colourBpRp, gEstimate, propagate, starPlace } from './record';
import { findStarRow } from './starfield';
import type { Vec3 } from './tree';

describe('propagate', () => {
	it('moves nothing over no time, and stays on the sphere', () => {
		expect(propagate(101.28, -16.71, -546, -1223, 0)).toEqual([
			expect.closeTo(101.28, 12),
			expect.closeTo(-16.71, 12)
		]);
		const [ra, dec] = propagate(359.9999, 89.99, 1e6, 0, 100);
		expect(ra).toBeGreaterThanOrEqual(0);
		expect(ra).toBeLessThan(360);
		expect(dec).toBeLessThanOrEqual(90);
	});

	it('moves a star east by its proper motion on ra·cos dec', () => {
		// 3,600,000 mas/yr for one year is one degree of arc along the equator.
		const [ra, dec] = propagate(10, 0, 3.6e6, 0, 1);
		expect(ra).toBeCloseTo(11, 3);
		expect(dec).toBeCloseTo(0, 9);
	});
});

describe('gEstimate', () => {
	it('takes V and B − V first, then Hp', () => {
		expect(gEstimate(-1.44, 0.009, -1.0876)).toBeCloseTo(-1.44 - 0.02907 - 0.02385 * 0.009, 4);
		expect(gEstimate(null, null, 9)).toBeCloseTo(8.72, 6);
		expect(gEstimate(5, null, null)).toBeNull();
	});
});

/** The node and row of an ID in the render tree, walking down to the octant
 *  of its place, by the node's ID file. */
function findRender(
	id: number,
	place: Vec3
): { name: string; row: number; node: { container: Container; info: NodeInfo } } | null {
	let name = 'r';
	for (;;) {
		const container = readExportFile(`mw/node/${name}.bin.gz`);
		const info = nodeInfo(container);
		const row = readExportFile(`mw/id/${name}.bin.gz`).ids('id').indexOf(id);
		if (row >= 0) return { name, row, node: { container, info } };
		let k = 0;
		for (let axis = 0; axis < 3; axis++) if (place[axis] >= info.centre[axis]) k |= 1 << axis;
		if (!((info.childMask >> k) & 1)) return null;
		name += k;
	}
}

describe.skipIf(!HAS_EXPORT)('a star from its record, against the render tree', () => {
	const lookup = new ExtrasolarLookup(diskSource());

	it.each([
		[22137869, 'Sirius (Hipparcos, moved from J1991.25)'],
		[27424668, 'Proxima Centauri'],
		[564339647, 'Toliman (Hipparcos)'],
		[7544072308, 'a faint Gaia star at 300 pc'],
		[27879543, 'a Gaia giant at 2.7 kpc']
	])('%i, %s: the place, magnitude and row the tree has', async (id) => {
		const result = await lookup.lookup(String(id));
		if (result.kind !== 'live') throw new Error(`${id} not found`);
		const row = homeRow(result.record)!;
		const place = starPlace(row)!;
		const absMag = absoluteG(row);
		const found = findRender(id, place.tree)!;
		expect(found).not.toBeNull();
		const { container, info } = found.node;
		// The tree's float32 offset is the record's place, rounded.
		for (const [axis, name] of ['x', 'y', 'z'].entries()) {
			const stored = container.float32(name)[found.row];
			const offset = place.tree[axis] - info.centre[axis];
			expect(Math.abs(stored - offset)).toBeLessThanOrEqual(Math.abs(offset) * 2 ** -22 + 1e-9);
		}
		expect(container.float32('mag')[found.row]).toBe(absMag);
		const colour = colourBpRp(row);
		if (colour !== null) expect(container.float32('colour')[found.row]).toBeCloseTo(colour, 2);
		// The position match finds the same row without the ID file.
		expect(findStarRow(found.node, { tree: place.tree, absMag })).toBe(found.row);
	});

	it('matches no row of a node that does not hold the star', async () => {
		const sirius = await lookup.lookup('22137869');
		const proxima = await lookup.lookup('27424668');
		if (sirius.kind !== 'live' || proxima.kind !== 'live') throw new Error('not found');
		const siriusRow = homeRow(sirius.record)!;
		const place = starPlace(homeRow(proxima.record)!)!;
		const node = findRender(27424668, place.tree)!.node;
		expect(
			findStarRow(node, { tree: starPlace(siriusRow)!.tree, absMag: absoluteG(siriusRow) })
		).toBe(-1);
		// Proxima's place with another magnitude is another star.
		expect(findStarRow(node, { tree: place.tree, absMag: 3 })).toBe(-1);
	});

	it('has no place for a Hipparcos star with a parallax under 5σ', async () => {
		const result = await lookup.lookup('16799379');
		if (result.kind !== 'live') throw new Error('not found');
		expect(starPlace(homeRow(result.record)!)).toBeNull();
		expect(absoluteG(homeRow(result.record)!)).toBeNull();
	});
});
