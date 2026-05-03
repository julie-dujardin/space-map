import { describe, it, expect } from 'vitest';
import { parseElements, type KeplerianColumns, type ParabolicColumns } from './elements';
import {
	MAGIC,
	VERSION,
	HEADER_SIZE,
	FORMAT_KEPLERIAN,
	FORMAT_PARABOLIC,
	OrbitalSource
} from './constants';
import { ObjectType } from '$lib/types/objects';
import fixtures from '$lib/math/orbit/elements.fixtures.json';

function align8(n: number): number {
	return (n + 7) & ~7;
}

interface KeplerianRow {
	id: number;
	objectType: number;
	parentId: number;
	scale: number;
	epochJd: number;
	a: number;
	e: number;
	i: number;
	om: number;
	w: number;
	ma: number;
	n: number;
	radiusKm: number;
	omDot?: number;
	wDot?: number;
}

interface ParabolicRow {
	id: number;
	objectType: number;
	parentId: number;
	scale: number;
	epochJd: number;
	q: number;
	e: number;
	i: number;
	om: number;
	w: number;
	tp: number;
	radiusKm: number;
}

function writeHeader(view: DataView, formatType: number, rowCount: number): void {
	view.setUint32(0, MAGIC, true);
	view.setUint16(4, VERSION, true);
	view.setUint16(6, formatType, true);
	view.setFloat64(8, -Infinity, true); // validityStart
	view.setFloat64(16, Infinity, true); // validityEnd
	view.setUint32(24, rowCount, true);
	view.setUint8(28, OrbitalSource.UNKNOWN); // source
}

function writeSharedColumns(
	view: DataView,
	rows: { id: number; objectType: number; parentId: number; scale: number }[]
): number {
	const n = rows.length;
	let offset = HEADER_SIZE;

	for (let r = 0; r < n; r++) view.setInt32(offset + r * 4, rows[r].id, true);
	offset += align8(n * 4);

	for (let r = 0; r < n; r++) view.setUint8(offset + r, rows[r].objectType);
	offset += align8(n);

	for (let r = 0; r < n; r++) view.setInt32(offset + r * 4, rows[r].parentId, true);
	offset += align8(n * 4);

	for (let r = 0; r < n; r++) view.setUint8(offset + r, rows[r].scale);
	offset += align8(n);

	return offset;
}

function buildKeplerianBuffer(rows: KeplerianRow[]): ArrayBuffer {
	const n = rows.length;
	const size =
		HEADER_SIZE +
		align8(n * 4) + // id
		align8(n) + // objectType
		align8(n * 4) + // parentId
		align8(n) + // scale
		n * 8 + // epochJd (f64)
		align8(n * 4) * 7 + // a, e, i, om, w, ma, n
		align8(n * 4) + // radiusKm
		align8(n * 4) * 2; // omDot, wDot

	const buf = new ArrayBuffer(size);
	const view = new DataView(buf);
	writeHeader(view, FORMAT_KEPLERIAN, n);
	let offset = writeSharedColumns(view, rows);

	for (let r = 0; r < n; r++) view.setFloat64(offset + r * 8, rows[r].epochJd, true);
	offset += n * 8;

	const f32Cols: (keyof KeplerianRow)[] = [
		'a',
		'e',
		'i',
		'om',
		'w',
		'ma',
		'n',
		'radiusKm',
		'omDot',
		'wDot'
	];
	for (const col of f32Cols) {
		for (let r = 0; r < n; r++) {
			view.setFloat32(offset + r * 4, (rows[r][col] as number | undefined) ?? 0, true);
		}
		offset += align8(n * 4);
	}

	return buf;
}

function buildParabolicBuffer(rows: ParabolicRow[]): ArrayBuffer {
	const n = rows.length;
	const size =
		HEADER_SIZE +
		align8(n * 4) + // id
		align8(n) + // objectType
		align8(n * 4) + // parentId
		align8(n) + // scale
		n * 8 + // epochJd (f64)
		align8(n * 4) * 4 + // q, e, i, om (wait — 5: q, e, i, om, w)
		align8(n * 4) + // w
		n * 8 + // tp (f64)
		align8(n * 4); // radiusKm

	const buf = new ArrayBuffer(size);
	const view = new DataView(buf);
	writeHeader(view, FORMAT_PARABOLIC, n);
	let offset = writeSharedColumns(view, rows);

	for (let r = 0; r < n; r++) view.setFloat64(offset + r * 8, rows[r].epochJd, true);
	offset += n * 8;

	const f32Cols: (keyof ParabolicRow)[] = ['q', 'e', 'i', 'om', 'w'];
	for (const col of f32Cols) {
		for (let r = 0; r < n; r++) view.setFloat32(offset + r * 4, rows[r][col] as number, true);
		offset += align8(n * 4);
	}

	for (let r = 0; r < n; r++) view.setFloat64(offset + r * 8, rows[r].tp, true);
	offset += n * 8;

	for (let r = 0; r < n; r++) view.setFloat32(offset + r * 4, rows[r].radiusKm, true);

	return buf;
}

// --- Test data ---
// Orbital elements reused from the shared fixtures; binary-specific fields
// (numeric id, objectType ordinal, parentId, scale, radiusKm) added here.

function fixtureToKeplerian(
	f: (typeof fixtures)[keyof typeof fixtures],
	bin: { id: number; objectType: ObjectType; parentId: number; scale: number; radiusKm: number }
): KeplerianRow {
	return {
		...bin,
		epochJd: f.epoch,
		a: f.a,
		e: f.e,
		i: f.i,
		om: f.om,
		w: f.w,
		ma: f.ma,
		n: f.n
	};
}

const CERES_ROW = fixtureToKeplerian(fixtures.ceres, {
	id: 20000001,
	objectType: ObjectType.DWARF_PLANET,
	parentId: 0,
	scale: 1,
	radiusKm: 473.0
});

const HALLEY_ROW = fixtureToKeplerian(fixtures.halley, {
	id: 1000036,
	objectType: ObjectType.COMET,
	parentId: 0,
	scale: 1,
	radiusKm: 5.5
});

const PHOBOS_ROW = fixtureToKeplerian(fixtures.phobos, {
	id: 401,
	objectType: ObjectType.MOON,
	parentId: 4,
	scale: 0,
	radiusKm: 11.1
});

const PARABOLIC_COMET: ParabolicRow = {
	id: 1003671,
	objectType: ObjectType.COMET,
	parentId: 0,
	scale: 1,
	epochJd: fixtures.a2020h9.epoch,
	q: 1.568,
	e: 1.0,
	i: fixtures.a2020h9.i,
	om: fixtures.a2020h9.om,
	w: fixtures.a2020h9.w,
	tp: 2459050.123456789,
	radiusKm: 2.0
};

const HYPERBOLIC_COMET: ParabolicRow = {
	id: 1004258,
	objectType: ObjectType.COMET,
	parentId: 0,
	scale: 1,
	epochJd: fixtures.catalinaHyperbolic.epoch,
	q: 2.01,
	e: fixtures.catalinaHyperbolic.e,
	i: fixtures.catalinaHyperbolic.i,
	om: fixtures.catalinaHyperbolic.om,
	w: fixtures.catalinaHyperbolic.w,
	tp: 2458900.987654321,
	radiusKm: 0.5
};

// --- Tests ---

describe('parseElements — Keplerian', () => {
	it('parses a single row with correct values', () => {
		const buf = buildKeplerianBuffer([CERES_ROW]);
		const cols = parseElements(buf) as KeplerianColumns;

		expect(cols.kind).toBe('keplerian');
		expect(cols.rowCount).toBe(1);
		expect(cols.id[0]).toBe(CERES_ROW.id);
		expect(cols.objectType[0]).toBe(CERES_ROW.objectType);
		expect(cols.parentId[0]).toBe(CERES_ROW.parentId);
		expect(cols.scale[0]).toBe(CERES_ROW.scale);
		expect(cols.epochJd[0]).toBe(CERES_ROW.epochJd);
		expect(cols.a[0]).toBeCloseTo(CERES_ROW.a, 3);
		expect(cols.e[0]).toBeCloseTo(CERES_ROW.e, 4);
		expect(cols.i[0]).toBeCloseTo(CERES_ROW.i, 2);
		expect(cols.om[0]).toBeCloseTo(CERES_ROW.om, 1);
		expect(cols.w[0]).toBeCloseTo(CERES_ROW.w, 1);
		expect(cols.ma[0]).toBeCloseTo(CERES_ROW.ma, 1);
		expect(cols.n[0]).toBeCloseTo(CERES_ROW.n, 3);
		expect(cols.radiusKm[0]).toBeCloseTo(CERES_ROW.radiusKm, 0);
	});

	it('parses multiple rows with correct columnar indexing', () => {
		const rows = [CERES_ROW, HALLEY_ROW, PHOBOS_ROW];
		const buf = buildKeplerianBuffer(rows);
		const cols = parseElements(buf) as KeplerianColumns;

		expect(cols.rowCount).toBe(3);
		expect(cols.id.length).toBe(3);

		for (let idx = 0; idx < rows.length; idx++) {
			expect(cols.id[idx]).toBe(rows[idx].id);
			expect(cols.objectType[idx]).toBe(rows[idx].objectType);
			expect(cols.parentId[idx]).toBe(rows[idx].parentId);
			expect(cols.scale[idx]).toBe(rows[idx].scale);
			expect(cols.epochJd[idx]).toBe(rows[idx].epochJd);
			expect(cols.a[idx]).toBeCloseTo(rows[idx].a, 1);
			expect(cols.e[idx]).toBeCloseTo(rows[idx].e, 3);
			expect(cols.n[idx]).toBeCloseTo(rows[idx].n, 2);
			expect(cols.radiusKm[idx]).toBeCloseTo(rows[idx].radiusKm, 0);
		}
	});

	it('handles zero rows', () => {
		const buf = buildKeplerianBuffer([]);
		const cols = parseElements(buf) as KeplerianColumns;

		expect(cols.kind).toBe('keplerian');
		expect(cols.rowCount).toBe(0);
		expect(cols.id.length).toBe(0);
		expect(cols.a.length).toBe(0);
	});

	it('reads secular drift rates from columns 13 and 14', () => {
		const row: KeplerianRow = { ...PHOBOS_ROW, omDot: 0.4358, wDot: -0.4318 };
		const buf = buildKeplerianBuffer([row]);
		const cols = parseElements(buf) as KeplerianColumns;
		expect(cols.omDot[0]).toBeCloseTo(0.4358, 4);
		expect(cols.wDot[0]).toBeCloseTo(-0.4318, 4);
	});
});

describe('parseElements — Parabolic', () => {
	it('parses a single parabolic row', () => {
		const buf = buildParabolicBuffer([PARABOLIC_COMET]);
		const cols = parseElements(buf) as ParabolicColumns;

		expect(cols.kind).toBe('parabolic');
		expect(cols.rowCount).toBe(1);
		expect(cols.id[0]).toBe(PARABOLIC_COMET.id);
		expect(cols.objectType[0]).toBe(PARABOLIC_COMET.objectType);
		expect(cols.q[0]).toBeCloseTo(PARABOLIC_COMET.q, 3);
		expect(cols.e[0]).toBeCloseTo(PARABOLIC_COMET.e, 4);
		expect(cols.i[0]).toBeCloseTo(PARABOLIC_COMET.i, 1);
		expect(cols.om[0]).toBeCloseTo(PARABOLIC_COMET.om, 1);
		expect(cols.w[0]).toBeCloseTo(PARABOLIC_COMET.w, 1);
		expect(cols.radiusKm[0]).toBeCloseTo(PARABOLIC_COMET.radiusKm, 1);
	});

	it('preserves Float64 precision for tp', () => {
		const buf = buildParabolicBuffer([PARABOLIC_COMET]);
		const cols = parseElements(buf) as ParabolicColumns;

		// Float64 should preserve the full Julian Date value
		expect(cols.tp[0]).toBe(PARABOLIC_COMET.tp);
		expect(cols.epochJd[0]).toBe(PARABOLIC_COMET.epochJd);
	});

	it('parses multiple parabolic rows', () => {
		const rows = [PARABOLIC_COMET, HYPERBOLIC_COMET];
		const buf = buildParabolicBuffer(rows);
		const cols = parseElements(buf) as ParabolicColumns;

		expect(cols.rowCount).toBe(2);
		for (let idx = 0; idx < rows.length; idx++) {
			expect(cols.id[idx]).toBe(rows[idx].id);
			expect(cols.q[idx]).toBeCloseTo(rows[idx].q, 2);
			expect(cols.tp[idx]).toBe(rows[idx].tp);
		}
	});

	it('handles zero rows', () => {
		const buf = buildParabolicBuffer([]);
		const cols = parseElements(buf) as ParabolicColumns;

		expect(cols.kind).toBe('parabolic');
		expect(cols.rowCount).toBe(0);
	});
});

describe('parseElements — error cases', () => {
	it('throws on bad magic', () => {
		const buf = new ArrayBuffer(HEADER_SIZE);
		const view = new DataView(buf);
		view.setUint32(0, 0xdeadbeef, true);
		view.setUint16(4, VERSION, true);
		view.setUint16(6, FORMAT_KEPLERIAN, true);
		view.setUint32(8, 0, true);

		expect(() => parseElements(buf)).toThrow(/bad magic/);
	});

	it('throws on unsupported version', () => {
		const buf = new ArrayBuffer(HEADER_SIZE);
		const view = new DataView(buf);
		view.setUint32(0, MAGIC, true);
		view.setUint16(4, 99, true);
		view.setUint16(6, FORMAT_KEPLERIAN, true);
		view.setUint32(8, 0, true);

		expect(() => parseElements(buf)).toThrow(/Unsupported.*version/);
	});

	it('throws on unknown format type', () => {
		const buf = new ArrayBuffer(HEADER_SIZE);
		const view = new DataView(buf);
		view.setUint32(0, MAGIC, true);
		view.setUint16(4, VERSION, true);
		view.setUint16(6, 99, true);
		view.setUint32(8, 0, true);

		expect(() => parseElements(buf)).toThrow(/Unknown.*format type/);
	});
});
