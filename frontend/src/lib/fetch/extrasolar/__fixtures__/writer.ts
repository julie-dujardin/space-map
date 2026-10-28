/**
 * Test-only writer of the extrasolar container (`docs/export-format/extrasolar.md`),
 * for synthetic tiles and split tables. The real files come from the Python
 * writer; this one only has to agree with the reader.
 */

import { gzipSync } from 'node:zlib';
import type { CrossId } from '../container';

type Value = number | bigint | string | boolean | CrossId[] | number[] | null;

export interface ColumnSpec {
	name: string;
	type:
		| 'bool'
		| 'uint32'
		| 'float32'
		| 'float64'
		| 'id'
		| 'string'
		| 'dict'
		| 'cross_ids'
		| 'bits'
		| 'uint64'
		| 'float32_list'
		| 'list';
	/** For a `list`, the item count of each row; its item columns follow it. */
	values: Value[];
}

const CODES: Record<ColumnSpec['type'], number> = {
	bool: 1,
	uint32: 7,
	float32: 8,
	float64: 9,
	id: 10,
	string: 11,
	dict: 12,
	cross_ids: 13,
	bits: 14,
	uint64: 15,
	float32_list: 16,
	list: 17
};

const encoder = new TextEncoder();

function u32(values: number[]): Uint8Array {
	return new Uint8Array(Uint32Array.from(values).buffer);
}

function strings(values: (string | null)[]): Uint8Array[] {
	const offsets = [0];
	const parts: Uint8Array[] = [];
	let at = 0;
	for (const v of values) {
		const bytes = encoder.encode(v ?? '');
		parts.push(bytes);
		at += bytes.length;
		offsets.push(at);
	}
	const bytes = new Uint8Array(at);
	let k = 0;
	for (const p of parts) {
		bytes.set(p, k);
		k += p.length;
	}
	return [u32(offsets), bytes];
}

function bitmap(flags: boolean[]): Uint8Array {
	const out = new Uint8Array(Math.ceil(flags.length / 8));
	flags.forEach((on, i) => {
		if (on) out[i >> 3] |= 1 << (i & 7);
	});
	return out;
}

function buffers(spec: ColumnSpec): Uint8Array[] {
	const v = spec.values;
	switch (spec.type) {
		case 'bool':
			return [Uint8Array.from(v.map((x) => (x ? 1 : 0)))];
		case 'bits':
			return [bitmap(v.map(Boolean))];
		case 'uint32':
			return [u32(v.map((x) => (x as number | null) ?? 0))];
		case 'float32':
			return [new Uint8Array(Float32Array.from(v.map((x) => (x as number | null) ?? NaN)).buffer)];
		case 'float64':
			return [new Uint8Array(Float64Array.from(v.map((x) => (x as number | null) ?? NaN)).buffer)];
		case 'id':
			return [new Uint8Array(Float64Array.from(v.map((x) => (x as number | null) ?? 0)).buffer)];
		case 'uint64':
			return [new Uint8Array(BigUint64Array.from(v.map((x) => (x as bigint | null) ?? 0n)).buffer)];
		case 'float32_list': {
			const lists = v.map((x) => (x as number[] | null) ?? []);
			const offsets = [0];
			for (const list of lists) offsets.push(offsets[offsets.length - 1] + list.length);
			return [u32(offsets), new Uint8Array(Float32Array.from(lists.flat()).buffer)];
		}
		case 'list': {
			const offsets = [0];
			for (const count of v)
				offsets.push(offsets[offsets.length - 1] + ((count as number | null) ?? 0));
			return [u32(offsets)];
		}
		case 'string':
			return strings(v as (string | null)[]);
		case 'dict': {
			const dict = [...new Set(v.filter((x): x is string => typeof x === 'string'))];
			const codes = new Uint8Array(
				Uint16Array.from(v.map((x) => (typeof x === 'string' ? dict.indexOf(x) : 0))).buffer
			);
			return [codes, ...strings(dict)];
		}
		case 'cross_ids': {
			const pairs: string[] = [];
			const list = [0];
			const codes: number[] = [];
			const ids: string[] = [];
			for (const row of v as (CrossId[] | null)[]) {
				for (const x of row ?? []) {
					let code = pairs.findIndex(
						(_, i) => i % 2 === 0 && pairs[i] === x.catalogue && pairs[i + 1] === x.release
					);
					if (code < 0) {
						code = pairs.length;
						pairs.push(x.catalogue, x.release);
					}
					codes.push(code / 2);
					ids.push(x.catalogueId);
				}
				list.push(ids.length);
			}
			return [
				u32(list),
				new Uint8Array(Uint16Array.from(codes).buffer),
				...strings(ids),
				...strings(pairs)
			];
		}
	}
}

/** A decoded payload: the bytes the reader takes. */
export function encode(
	kind: number,
	token: string,
	rows: number,
	columns: ColumnSpec[],
	info: Uint8Array = new Uint8Array(0)
): Uint8Array {
	const pad = (n: number) => (8 - (n % 8)) % 8;
	const encoded = columns.map((c) => {
		const nulls = c.type !== 'bits' && c.values.some((x) => x === null);
		const bufs = buffers(c);
		return {
			c,
			flags: nulls ? 1 : 0,
			bufs: nulls ? [bitmap(c.values.map((x) => x !== null)), ...bufs] : bufs
		};
	});
	const names = columns.map((c) => encoder.encode(c.name));
	let at = 32 + info.length;
	for (let i = 0; i < encoded.length; i++) at += 4 + names[i].length + 8 * encoded[i].bufs.length;
	at += pad(at);
	const places = encoded.map(({ bufs }) =>
		bufs.map((b) => {
			const place = [at, b.length];
			at += b.length + pad(b.length);
			return place;
		})
	);
	const out = new Uint8Array(at);
	const view = new DataView(out.buffer);
	out.set(encoder.encode('SMXS'), 0);
	view.setUint16(4, 1, true);
	view.setUint8(6, kind);
	out.set(encoder.encode(token.padEnd(16, '0').slice(0, 16)), 8);
	view.setUint32(24, rows, true);
	view.setUint16(28, columns.length, true);
	view.setUint16(30, info.length, true);
	out.set(info, 32);
	let d = 32 + info.length;
	encoded.forEach(({ c, flags, bufs }, i) => {
		view.setUint8(d, CODES[c.type]);
		view.setUint8(d + 1, flags);
		view.setUint8(d + 2, bufs.length);
		view.setUint8(d + 3, names[i].length);
		out.set(names[i], d + 4);
		d += 4 + names[i].length;
		for (const [offset, length] of places[i]) {
			view.setUint32(d, offset, true);
			view.setUint32(d + 4, length, true);
			d += 8;
		}
	});
	encoded.forEach(({ bufs }, i) => bufs.forEach((b, j) => out.set(b, places[i][j][0])));
	return out;
}

/** A tile's info block: pixel, level, table. */
export function tileInfoBytes(pixel: number, level: number, table: number): Uint8Array {
	const info = new Uint8Array(8);
	const view = new DataView(info.buffer);
	view.setUint32(0, pixel, true);
	view.setUint8(4, level);
	view.setUint8(5, table);
	return info;
}

export function gzip(payload: Uint8Array): Uint8Array {
	return gzipSync(payload);
}
