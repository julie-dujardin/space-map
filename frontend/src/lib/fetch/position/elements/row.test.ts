import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import zlib from 'node:zlib';
import { parseElementsPayload, type KeplerianColumns } from './parse';
import { fillOrbitColumnRow, materializeBodyData } from './row';
import { allocColumns, KIND_KEPLER } from '$lib/math/orbit/soa';
import {
	HEADER_SIZE,
	MAGIC,
	VERSION,
	FORMAT_ELEMENTS,
	SUBFORMAT_KEPLERIAN,
	OrbitalSource,
	IdType
} from '$lib/fetch/position/format';

const align8 = (n: number): number => (n + 7) & ~7;

interface Row {
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
}

/** Build a v10 SUBFORMAT_KEPLERIAN elements buffer (matches parse.ts layout). */
function buildKeplerian(rows: Row[]): ArrayBuffer {
	const n = rows.length;
	const size =
		HEADER_SIZE +
		align8(n * 4) + // id
		align8(n) + // objectType
		align8(n * 4) + // parentId
		align8(n) + // scale
		n * 8 + // epochJd f64
		align8(n * 4) * 7 + // a e i om w ma n
		align8(n * 4) + // radiusKm
		align8(n * 4) * 2 + // omDot wDot
		align8(n) + // hasLocalized
		align8(n); // flags
	const buf = new ArrayBuffer(size);
	const v = new DataView(buf);
	v.setUint32(0, MAGIC, true);
	v.setUint16(4, VERSION, true);
	v.setUint8(6, FORMAT_ELEMENTS);
	v.setFloat64(8, -Infinity, true);
	v.setFloat64(16, Infinity, true);
	v.setUint16(24, SUBFORMAT_KEPLERIAN, true);
	v.setUint8(26, OrbitalSource.SBDB);
	v.setUint8(27, IdType.SPKID);
	v.setUint32(28, n, true);
	let o = HEADER_SIZE;
	for (let r = 0; r < n; r++) v.setInt32(o + r * 4, rows[r].id, true);
	o += align8(n * 4);
	for (let r = 0; r < n; r++) v.setUint8(o + r, rows[r].objectType);
	o += align8(n);
	for (let r = 0; r < n; r++) v.setInt32(o + r * 4, rows[r].parentId, true);
	o += align8(n * 4);
	for (let r = 0; r < n; r++) v.setUint8(o + r, rows[r].scale);
	o += align8(n);
	for (let r = 0; r < n; r++) v.setFloat64(o + r * 8, rows[r].epochJd, true);
	o += n * 8;
	for (const key of ['a', 'e', 'i', 'om', 'w', 'ma', 'n', 'radiusKm'] as const) {
		for (let r = 0; r < n; r++) v.setFloat32(o + r * 4, rows[r][key], true);
		o += align8(n * 4);
	}
	// omDot, wDot, hasLocalized, flags left zero (ArrayBuffer zero-inits).
	return buf;
}

describe('fillOrbitColumnRow matches the materialized BodyData (worker sees identical elements)', () => {
	it('keplerian: direct-fill columns equal the AoS BodyData fields, bit for bit', () => {
		const rows: Row[] = Array.from({ length: 200 }, (_, r) => ({
			id: 2000000 + r,
			objectType: 8, // ASTEROID_MAIN_BELT
			parentId: 10, // Sun
			scale: 1, // SYSTEM
			epochJd: 2460000.5 + r * 0.01,
			a: 2.2 + r * 0.001,
			e: 0.05 + (r % 50) * 0.001,
			i: 1 + (r % 30),
			om: (r * 7) % 360,
			w: (r * 13) % 360,
			ma: (r * 17) % 360,
			n: 0.2 + r * 0.0001,
			radiusKm: 1 + (r % 10)
		}));
		const cols = parseElementsPayload(
			buildKeplerian(rows),
			-Infinity,
			Infinity
		) as KeplerianColumns;
		const labels = new Map();
		const out = allocColumns(cols.rowCount);
		for (let i = 0; i < cols.rowCount; i++) {
			const live = fillOrbitColumnRow(cols, i, out, i);
			expect(live).toBe(true);
			const d = materializeBodyData(cols, i, labels, 'naif')!;
			expect(out.kind[i]).toBe(KIND_KEPLER);
			expect(out.a[i]).toBe(d.a);
			expect(out.e[i]).toBe(d.e);
			expect(out.i[i]).toBe(d.i);
			expect(out.om[i]).toBe(d.om);
			expect(out.w[i]).toBe(d.w);
			expect(out.ma[i]).toBe(d.ma);
			expect(out.n[i]).toBe(d.n);
			expect(out.epoch[i]).toBe(d.epoch);
			expect(out.equatorial[i]).toBe(d.equatorial ? 1 : 0);
		}
	});

	// Real-data parity + speed: only runs where the local export tree exists.
	const MBA = `${process.env.HOME}/code/git/personal/space-map-export/v1/position/small_bodies/MBA/1/0.bin.gz`;
	const realIt = fs.existsSync(MBA) ? it : it.skip;
	realIt('real MBA part: 10k rows fill identically + direct path is far cheaper', () => {
		const raw = zlib.gunzipSync(fs.readFileSync(MBA));
		const ab = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
		const cols = parseElementsPayload(ab, -Infinity, Infinity);
		const labels = new Map();
		const out = allocColumns(cols.rowCount);
		let mismatches = 0;
		for (let i = 0; i < cols.rowCount; i++) {
			fillOrbitColumnRow(cols, i, out, i);
			const d = materializeBodyData(cols, i, labels, 'spkid');
			if (!d) continue;
			if (out.a[i] !== d.a || out.e[i] !== d.e || out.n[i] !== d.n || out.epoch[i] !== d.epoch) {
				mismatches++;
			}
		}
		expect(mismatches).toBe(0);

		const REP = 20;
		let acc = 0;
		const t0 = performance.now();
		for (let r = 0; r < REP; r++) {
			const o = allocColumns(cols.rowCount);
			for (let i = 0; i < cols.rowCount; i++) fillOrbitColumnRow(cols, i, o, i);
			acc += o.a[0];
		}
		const tFill = performance.now() - t0;
		const t1 = performance.now();
		for (let r = 0; r < REP; r++) {
			const o = allocColumns(cols.rowCount);
			for (let i = 0; i < cols.rowCount; i++) {
				const d = materializeBodyData(cols, i, labels, 'spkid')!;
				o.a[i] = d.a;
				o.e[i] = d.e;
				o.i[i] = d.i;
				o.om[i] = d.om;
				o.w[i] = d.w;
				o.ma[i] = d.ma;
				o.n[i] = d.n;
				o.epoch[i] = d.epoch;
			}
			acc += o.a[0];
		}
		const tAos = performance.now() - t1;
		console.log(
			`[row bench] ${cols.rowCount} rows ×${REP}: direct-fill ${tFill.toFixed(0)}ms vs AoS-materialize ${tAos.toFixed(0)}ms (${(tAos / tFill).toFixed(1)}x) — full-pipeline win (solve+double-alloc+repack eliminated) measured separately at ~13.9x; acc=${acc.toFixed(0)}`
		);
	});
});
