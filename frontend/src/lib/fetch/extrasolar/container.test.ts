/**
 * The container parser against files that the Python writer wrote
 * (`data/scripts/generate_extrasolar_container_fixtures.py`).
 */

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
	Container,
	ContainerFormatError,
	KIND_NODE,
	KIND_SPLIT,
	KIND_TILE,
	nodeInfo,
	tileInfo
} from './container';
import { gunzip } from '$lib/fetch/gz';
import expected from './__fixtures__/expected.json';

type Expected = { type: string; values: unknown[] };

async function load(name: string): Promise<Container> {
	const bytes = readFileSync(new URL(`./__fixtures__/${name}`, import.meta.url));
	// The same decode as the browser: the payload lands at offset 0 of its own buffer.
	const payload = await gunzip(new Response(bytes)).arrayBuffer();
	return new Container(payload);
}

/** Every value of a column as JSON would hold it: null where the row has none. */
function read(c: Container, name: string): unknown[] {
	const type = c.type(name);
	const out: unknown[] = [];
	for (let i = 0; i < c.rows; i++) {
		if (!c.isValid(name, i)) {
			out.push(null);
			continue;
		}
		switch (type) {
			case 'id':
				out.push(c.ids(name)[i]);
				break;
			case 'float64':
				out.push(c.float64(name)[i]);
				break;
			case 'float32':
				out.push(c.float32(name)[i]);
				break;
			case 'bool':
				out.push(c.bool(name)[i] === 1);
				break;
			case 'int8':
				out.push(c.int8(name)[i]);
				break;
			case 'int16':
				out.push(c.int16(name)[i]);
				break;
			case 'int32':
				out.push(c.int32(name)[i]);
				break;
			case 'uint8':
				out.push(c.uint8(name)[i]);
				break;
			case 'uint16':
				out.push(c.uint16(name)[i]);
				break;
			case 'uint32':
				out.push(c.uint32(name)[i]);
				break;
			case 'string':
				out.push(c.strings(name).get(i));
				break;
			case 'dict':
				out.push(c.dict(name).get(i));
				break;
			case 'uint64':
				// expected.json holds them as decimal strings.
				out.push(String(c.uint64(name)[i]));
				break;
			case 'float32_list':
				out.push(Array.from(c.float32List(name).get(i) ?? [], (x) => (Number.isNaN(x) ? null : x)));
				break;
			case 'cross_ids':
				out.push(
					c
						.crossIds(name)
						.get(i)
						?.map((x) => ({
							catalogue: x.catalogue,
							release: x.release,
							catalogue_id: x.catalogueId
						}))
				);
				break;
			default:
				throw new Error(`no reader for ${type}`);
		}
	}
	return out;
}

describe('Container', () => {
	it('reads the header and the info block of a record tile', async () => {
		const tile = await load('tile.bin.gz');
		expect(tile.kind).toBe(KIND_TILE);
		expect(tile.token).toBe(expected.token);
		expect(tile.rows).toBe(3);
		expect(tileInfo(tile)).toEqual({
			pixel: expected.tile.pixel,
			level: expected.tile.level,
			table: expected.tile.table
		});
		expect(tile.names()).toEqual(Object.keys(expected.tile.columns));
	});

	it('reads every column type of a record tile, nulls included', async () => {
		const tile = await load('tile.bin.gz');
		for (const [name, column] of Object.entries(
			expected.tile.columns as Record<string, Expected>
		)) {
			expect(tile.type(name), name).toBe(column.type);
			expect(read(tile, name), name).toEqual(column.values);
		}
	});

	it('keeps IDs up to 2^53 exact and reads a null float as NaN', async () => {
		const tile = await load('tile.bin.gz');
		const ids = tile.ids('id');
		expect(ids).toBeInstanceOf(Float64Array);
		expect(ids[1]).toBe(2 ** 53 - 1);
		expect(Number.isNaN(tile.float64('ra')[1])).toBe(true);
		expect(tile.ids('alias_target')[0]).toBe(0);
	});

	it('keeps uint64 bits past 2^53 and float32 lists with their NaN entries', async () => {
		const tile = await load('tile.bin.gz');
		expect(tile.uint64('flags')[0]).toBe((1n << 57n) + 64n);
		expect(tile.uint64('flags')[2]).toBe(2n ** 64n - 1n);
		const lists = tile.float32List('corr_vec');
		expect(lists.get(0)?.buffer).toBe(tile.buffer);
		expect(Number.isNaN(lists.get(0)![1])).toBe(true);
		expect(lists.get(1)).toBeNull();
		expect(lists.get(2)?.length).toBe(0);
	});

	it('gives typed-array views on the payload, not copies', async () => {
		const tile = await load('tile.bin.gz');
		const mag = tile.float32('mag');
		expect(mag.buffer).toBe(tile.buffer);
		expect(mag.byteOffset % 8).toBe(0);
	});

	it('reads a render node and its info block', async () => {
		const node = await load('node.bin.gz');
		expect(node.kind).toBe(KIND_NODE);
		const info = nodeInfo(node);
		expect(info.centre).toEqual(expected.node.centre);
		expect(info.half).toBe(expected.node.half);
		expect(info.minRange).toBe(expected.node.min_range);
		expect(info.maxRange).toBe(expected.node.max_range);
		expect([...info.childRange]).toEqual(expected.node.child_range);
		expect(info.depth).toBe(expected.node.depth);
		expect(info.childMask).toBe(0b10010);
		for (const [name, column] of Object.entries(
			expected.node.columns as Record<string, Expected>
		)) {
			expect(read(node, name), name).toEqual(column.values);
		}
		expect(Number.isNaN(node.float32('colour')[3])).toBe(true);
	});

	it('reads a split table as bits', async () => {
		const split = await load('split.bin.gz');
		expect(split.kind).toBe(KIND_SPLIT);
		const bits = split.bits('split');
		expect(Array.from({ length: bits.length }, (_, i) => bits.get(i))).toEqual(expected.split);
	});

	it('reads a list of structs through its item columns', async () => {
		const tile = await load('lists.bin.gz');
		expect(tile.rows).toBe(3);
		expect(tile.names().map((name) => [name, tile.type(name)])).toEqual(expected.lists.columns);
		const members = tile.list('members');
		const ids = tile.ids('members.id');
		const kinds = tile.dict('members.kind');
		const separations = tile.float64('members.separation');
		const known = tile.list('members.known');
		const knownItems = tile.strings('members.known.item');
		const rows = Array.from({ length: tile.rows }, (_, i) => {
			const range = members.items(i);
			if (!range) return null;
			const out = [];
			for (let j = range[0]; j < range[1]; j++) {
				const words = known.items(j);
				out.push({
					id: tile.isValid('members.id', j) ? ids[j] : null,
					kind: kinds.get(j),
					separation: tile.isValid('members.separation', j) ? separations[j] : null,
					known: words
						? Array.from({ length: words[1] - words[0] }, (_, k) => knownItems.get(words[0] + k))
						: null
				});
			}
			return out;
		});
		expect(rows).toEqual(expected.lists.members);
		const sources = tile.list('sources');
		const names = tile.dict('sources.item');
		const lists = Array.from({ length: tile.rows }, (_, i) => {
			const range = sources.items(i);
			return (
				range && Array.from({ length: range[1] - range[0] }, (_, k) => names.get(range[0] + k))
			);
		});
		expect(lists).toEqual(expected.lists.sources);
	});

	it('refuses a column read as the wrong type, and a payload that is not a container', async () => {
		const tile = await load('tile.bin.gz');
		expect(() => tile.float64('mag')).toThrow(ContainerFormatError);
		expect(() => tile.float32('nothing')).toThrow(ContainerFormatError);
		expect(() => nodeInfo(tile)).toThrow(ContainerFormatError);
		expect(() => new Container(new ArrayBuffer(40))).toThrow(ContainerFormatError);
	});
});
