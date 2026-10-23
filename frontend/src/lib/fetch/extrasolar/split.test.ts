import { describe, expect, it } from 'vitest';
import { ContainerFormatError } from './container';
import { SplitTree, findId, type Bits } from './split';
import { HAS_EXPORT, exportMetadata, readExportFile } from './__fixtures__/export';

function bits(values: number[]): Bits {
	return { length: values.length, get: (i) => values[i] === 1 };
}

describe('SplitTree', () => {
	it('takes the 12 roots as leaves when nothing splits', () => {
		const tree = SplitTree.fromBits(bits(new Array(12).fill(0)));
		expect(tree.leaves).toBe(12);
		expect(tree.tileOf(0)).toEqual({ level: 0, pixel: 0 });
		expect(tree.tileOf(4 ** 10 - 1)).toEqual({ level: 0, pixel: 0 });
		expect(tree.tileOf(4 ** 10)).toEqual({ level: 0, pixel: 1 });
		expect(tree.tileOf(12 * 4 ** 10 - 1)).toEqual({ level: 0, pixel: 11 });
	});

	it('walks the bits in pre-order', () => {
		// Root 0 splits; its child 2 splits again; every other pixel is a leaf.
		const tree = SplitTree.fromBits(bits([1, 0, 0, 1, 0, 0, 0, 0, 0, ...new Array(11).fill(0)]));
		expect(tree.leaves).toBe(3 + 4 + 11);
		expect(tree.tileOf(0)).toEqual({ level: 1, pixel: 0 });
		expect(tree.tileOf(2 * 4 ** 9)).toEqual({ level: 2, pixel: 8 });
		expect(tree.tileOf(2 * 4 ** 9 + 3 * 4 ** 8 + 5)).toEqual({ level: 2, pixel: 11 });
		expect(tree.tileOf(3 * 4 ** 9)).toEqual({ level: 1, pixel: 3 });
		expect(tree.tileOf(4 ** 10)).toEqual({ level: 0, pixel: 1 });
	});

	it('refuses a short table, a long one and a cell that splits', () => {
		expect(() => SplitTree.fromBits(bits(new Array(11).fill(0)))).toThrow(ContainerFormatError);
		expect(() => SplitTree.fromBits(bits(new Array(13).fill(0)))).toThrow(ContainerFormatError);
		// Root 0 split ten times down to a level-10 pixel that splits again.
		const deep = [...new Array(11).fill(1)];
		expect(() => SplitTree.fromBits(bits(deep))).toThrow(ContainerFormatError);
	});
});

describe('findId', () => {
	it('finds an ID by binary search, or -1', () => {
		const ids = Float64Array.from([3, 22137869, 564339647, 2 ** 52 + 1]);
		expect(findId(ids, 22137869)).toBe(1);
		expect(findId(ids, 2 ** 52 + 1)).toBe(3);
		expect(findId(ids, 4)).toBe(-1);
		expect(findId(new Float64Array(0), 4)).toBe(-1);
	});
});

describe.skipIf(!HAS_EXPORT)('SplitTree on the real export', () => {
	const meta = HAS_EXPORT ? exportMetadata() : null!;

	it.each(['metadata', 'point-source'])('%s: one leaf per tile, in cell order', (slug) => {
		const table = meta.tables[slug];
		const tree = SplitTree.fromBits(readExportFile(table.split).bits('split'));
		expect(tree.leaves).toBe(table.tiles);
		for (let i = 1; i < tree.leaves; i++) expect(tree.first[i]).toBeGreaterThan(tree.first[i - 1]);
	});

	it("finds Sirius's tiles where the export put them", () => {
		const cell = 22137869 % 2 ** 24;
		const metadata = SplitTree.fromBits(readExportFile(meta.tables.metadata.split).bits('split'));
		const points = SplitTree.fromBits(
			readExportFile(meta.tables['point-source'].split).bits('split')
		);
		expect(metadata.tileOf(cell)).toEqual({ level: 6, pixel: 20940 });
		expect(points.tileOf(cell)).toEqual({ level: 8, pixel: 335040 });
	});
});
