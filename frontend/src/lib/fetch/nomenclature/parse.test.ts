import { describe, it, expect } from 'vitest';
import { HEADER_SIZE, RECORD_SIZE, parseNomenclature } from './parse';

function buildFixture(
	records: Array<{
		featureId: number;
		latE7: number;
		lonE7: number;
		diameterM: number;
		typeCode: string;
		flags?: number;
	}>
): ArrayBuffer {
	const buf = new ArrayBuffer(HEADER_SIZE + records.length * RECORD_SIZE);
	const view = new DataView(buf);
	// Header: "SMNF" magic, version 1, count
	view.setUint8(0, 0x53); // 'S'
	view.setUint8(1, 0x4d); // 'M'
	view.setUint8(2, 0x4e); // 'N'
	view.setUint8(3, 0x46); // 'F'
	view.setUint16(4, 1, true);
	view.setUint32(8, records.length, true);

	records.forEach((rec, i) => {
		const offset = HEADER_SIZE + i * RECORD_SIZE;
		view.setUint32(offset, rec.featureId, true);
		view.setInt32(offset + 4, rec.latE7, true);
		view.setUint32(offset + 8, rec.lonE7, true);
		view.setUint32(offset + 12, rec.diameterM, true);
		view.setUint8(offset + 16, rec.typeCode.charCodeAt(0));
		view.setUint8(offset + 17, rec.typeCode.length > 1 ? rec.typeCode.charCodeAt(1) : 0);
		view.setUint8(offset + 18, rec.flags ?? 0);
	});

	return buf;
}

describe('parseNomenclature', () => {
	it('reads a header and zero records', () => {
		const buf = buildFixture([]);
		expect(parseNomenclature(buf)).toEqual([]);
	});

	it('round-trips a single feature record', () => {
		const buf = buildFixture([
			{
				featureId: 15600,
				latE7: -203_000_000,
				lonE7: 105_000_000,
				diameterM: 92_000,
				typeCode: 'AA'
			}
		]);
		const out = parseNomenclature(buf);
		expect(out).toHaveLength(1);
		expect(out[0]).toEqual({
			featureId: 15600,
			lat: -20.3,
			lon: 10.5,
			diameterM: 92_000,
			typeCode: 'AA',
			flags: 0
		});
	});

	it('trims a single-char type code padded with \\0', () => {
		const buf = buildFixture([{ featureId: 1, latE7: 0, lonE7: 0, diameterM: 0, typeCode: 'X' }]);
		const out = parseNomenclature(buf);
		expect(out[0].typeCode).toBe('X');
	});

	it('preserves the flags byte', () => {
		const buf = buildFixture([
			{ featureId: 1, latE7: 0, lonE7: 0, diameterM: 0, typeCode: 'AA', flags: 1 }
		]);
		const out = parseNomenclature(buf);
		expect(out[0].flags).toBe(1);
	});

	it('throws on a bad magic', () => {
		const buf = new ArrayBuffer(HEADER_SIZE);
		new DataView(buf).setUint32(0, 0xdeadbeef, true);
		expect(() => parseNomenclature(buf)).toThrow(/bad magic/);
	});

	it('throws on an unsupported version', () => {
		const buf = buildFixture([]);
		new DataView(buf).setUint16(4, 99, true);
		expect(() => parseNomenclature(buf)).toThrow(/version/);
	});
});
