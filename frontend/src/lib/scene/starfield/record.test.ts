import { describe, expect, it } from 'vitest';
import { nodeInfo, type Container, type NodeInfo } from '$lib/fetch/extrasolar/container';
import { ExtrasolarLookup, astrometricOrbit, homeRow } from '$lib/fetch/extrasolar/lookup';
import {
	HAS_EXPORT,
	diskSource,
	readExportFile,
	readExportJson
} from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRow } from '$lib/fetch/extrasolar/__fixtures__/synthetic';
import type { PlanetHost, PlanetIndexFile, PlanetSystem } from '$lib/fetch/extrasolar/planets';
import { bpRpFromTeff } from './colour';
import {
	absoluteG,
	apparentG,
	colourBpRp,
	drawnAbsoluteG,
	gEstimate,
	propagate,
	starPlace,
	starRadiusKm,
	starTeff
} from './record';
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

describe('a star from SIMBAD at a group distance', () => {
	it('takes G from SIMBAD, else from its V and B − V', () => {
		expect(apparentG(pointSourceRow({ simbad_g_mag: 9, simbad_v_mag: 8 }))).toBe(9);
		const vb = { simbad_v_mag: 8, simbad_b_mag: 9 };
		expect(apparentG(pointSourceRow(vb))).toBeCloseTo(gEstimate(8, 1, null)!, 6);
		expect(apparentG(pointSourceRow({ simbad_v_mag: 8 }))).toBeNull();
	});

	it('is placed and has its absolute G at the group distance', () => {
		const row = pointSourceRow({
			ra: 80,
			dec: -69,
			parallax: 0.01,
			parallax_error: 0.05,
			distance: 50_000,
			distance_source: 'magellanic-clouds',
			simbad_g_mag: 12
		});
		expect(starPlace(row, null)?.distancePc).toBe(50_000);
		expect(absoluteG(row, null)).toBeCloseTo(12 - 5 * Math.log10(50_000) + 5, 3);
	});
});

describe('a planet host with no magnitude', () => {
	it("is drawn as the tree draws it: at its catalogue's distance, at absolute G 15", () => {
		const place = { ra: 80, dec: -69 };
		const row = pointSourceRow({ ...place, host_distance: 40, host_star_source: 'exoplanet-eu' });
		expect(starPlace(row, null)?.distancePc).toBe(40);
		expect(absoluteG(row, null)).toBeNull();
		expect(drawnAbsoluteG(row, null)).toBe(15);
		// A star with no magnitude that hosts no planet has no tree row.
		expect(drawnAbsoluteG(pointSourceRow({ ...place, distance: 40 }), null)).toBeNull();
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
		const orbit = astrometricOrbit(result.record);
		const place = starPlace(row, orbit)!;
		const absMag = absoluteG(row, orbit);
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
		const place = starPlace(homeRow(proxima.record)!, null)!;
		const node = findRender(27424668, place.tree)!.node;
		expect(
			findStarRow(node, {
				tree: starPlace(siriusRow, null)!.tree,
				absMag: absoluteG(siriusRow, null)
			})
		).toBe(-1);
		// Proxima's place with another magnitude is another star.
		expect(findStarRow(node, { tree: place.tree, absMag: 3 })).toBe(-1);
	});

	it('has no place for a Hipparcos star with a parallax under 5σ', async () => {
		const result = await lookup.lookup('16799379');
		if (result.kind !== 'live') throw new Error('not found');
		expect(starPlace(homeRow(result.record)!, null)).toBeNull();
		expect(absoluteG(homeRow(result.record)!, null)).toBeNull();
	});
});

describe('a planet host with no Gaia or Hipparcos colour', () => {
	it('takes the colour of a dwarf of its Teff, the catalogue Teff first', () => {
		expect(colourBpRp(pointSourceRow({ host_teff: 6395, teff_gspphot: 5000 }))).toBeCloseTo(
			bpRpFromTeff(6395),
			9
		);
		expect(colourBpRp(pointSourceRow({ teff_gspphot: 5000 }))).toBeCloseTo(bpRpFromTeff(5000), 9);
		expect(colourBpRp(pointSourceRow({}))).toBeNull();
	});
});

describe.skipIf(!HAS_EXPORT)('planet hosts from their records, against the planet files', () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const index = HAS_EXPORT ? readExportJson<PlanetIndexFile>('planets/index.json.gz') : null!;

	/** The first drawn host of the index that `wanted` takes, with its system's
	 *  record of it. */
	function firstHost(wanted: (host: PlanetHost) => boolean): PlanetHost {
		for (const entry of index.hosts) {
			if (entry.position === null) continue;
			const file = readExportJson<PlanetSystem>(`planets/${entry.system}.json.gz`);
			const host = file.hosts.find((h) => h.id === entry.id && wanted(h));
			if (host) return host;
		}
		throw new Error('no such host');
	}

	it.each<[string, (host: PlanetHost) => boolean]>([
		['Proxima Centauri, by its parallax', (h) => h.id === 27424668],
		[
			'at its catalogue distance, with a Teff',
			(h) => h.placement === 'catalogue distance' && h.teff !== null
		],
		['at a distance of its distance group', (h) => h.placement === 'bailer-jones-2021'],
		['by a SIMBAD parallax', (h) => h.placement === 'simbad-parallax']
	])('%s: the place of its system file and the row of the tree', async (_, wanted) => {
		const host = firstHost(wanted);
		const result = await lookup.lookup(String(host.id));
		if (result.kind !== 'live') throw new Error(`${host.id} not found`);
		const row = homeRow(result.record)!;
		const orbit = astrometricOrbit(result.record);
		const place = starPlace(row, orbit)!;
		for (let k = 0; k < 3; k++) {
			expect(Math.abs(place.tree[k] - host.position![k])).toBeLessThan(1e-9 * host.distance!);
		}
		// The file writes a float32 distance as its shortest decimal.
		expect(Math.abs(place.distancePc / host.distance! - 1)).toBeLessThan(1e-7);
		const absMag = drawnAbsoluteG(row, orbit);
		const found = findRender(host.id, place.tree)!;
		expect(found).not.toBeNull();
		expect(found.node.container.float32('mag')[found.row]).toBe(absMag);
		const colour = colourBpRp(row);
		const stored = found.node.container.float32('colour')[found.row];
		if (colour === null) expect(stored).toBeNaN();
		else expect(stored).toBeCloseTo(colour, 2);
		expect(findStarRow(found.node, { tree: place.tree, absMag })).toBe(found.row);
		// The disc takes the radius and Teff that the system file gives.
		if (host.teff === null) expect(starTeff(row)).toBeNull();
		else expect(starTeff(row)).toBeCloseTo(host.teff, 0);
		if (host.radius !== null && host.radius_source !== 'gaia-dr3') {
			expect(starRadiusKm(row)! / 695_700).toBeCloseTo(host.radius, 4);
		}
	});
});
