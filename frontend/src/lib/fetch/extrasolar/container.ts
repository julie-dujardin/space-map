/**
 * Reader of the extrasolar container (`docs/export-format/extrasolar.md`).
 *
 * A payload is little-endian: a 32-byte header, an info block of its kind, a
 * column directory, then the buffers. Each buffer starts at a multiple of 8
 * bytes, so a column is a typed-array view on the payload and nothing is
 * copied. The payload must start its own `ArrayBuffer`.
 */

export const MAGIC = 'SMXS';
export const FORMAT_VERSION = 1;

export const KIND_TILE = 1;
export const KIND_SPLIT = 2;
export const KIND_NODE = 3;
export const KIND_IDS = 4;

const HEADER_SIZE = 32;
const TOKEN_AT = 8;
const TOKEN_SIZE = 16;
const HAS_VALIDITY = 1;
const NODE_INFO_SIZE = 80;
const TILE_INFO_SIZE = 8;

export type ColumnType =
	| 'bool'
	| 'int8'
	| 'int16'
	| 'int32'
	| 'uint8'
	| 'uint16'
	| 'uint32'
	| 'float32'
	| 'float64'
	| 'id'
	| 'string'
	| 'dict'
	| 'cross_ids'
	| 'bits'
	| 'uint64'
	| 'float32_list';

const TYPE_CODES: Record<number, ColumnType> = {
	1: 'bool',
	2: 'int8',
	3: 'int16',
	4: 'int32',
	5: 'uint8',
	6: 'uint16',
	7: 'uint32',
	8: 'float32',
	9: 'float64',
	10: 'id',
	11: 'string',
	12: 'dict',
	13: 'cross_ids',
	14: 'bits',
	15: 'uint64',
	16: 'float32_list'
};

export class ContainerFormatError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'ContainerFormatError';
	}
}

/** One buffer of a column: byte offset and byte length in the payload. */
interface Place {
	offset: number;
	length: number;
}

interface ColumnEntry {
	type: ColumnType;
	/** The validity bitmap, or null when every row has a value. */
	validity: Uint8Array | null;
	/** The buffers after the bitmap. */
	places: Place[];
}

/** One catalogue id of an object. */
export interface CrossId {
	catalogue: string;
	release: string;
	catalogueId: string;
}

const decoder = new TextDecoder();

function bitAt(bytes: Uint8Array, i: number): boolean {
	return ((bytes[i >> 3] >> (i & 7)) & 1) === 1;
}

/** Strings as offsets into UTF-8 bytes; decoded one row at a time. */
export class StringColumn {
	constructor(
		readonly offsets: Uint32Array,
		readonly bytes: Uint8Array,
		private readonly validity: Uint8Array | null
	) {}

	get length(): number {
		return this.offsets.length - 1;
	}

	get(i: number): string | null {
		if (this.validity && !bitAt(this.validity, i)) return null;
		return decoder.decode(this.bytes.subarray(this.offsets[i], this.offsets[i + 1]));
	}
}

/** Few distinct strings, as a code per row into a dictionary. */
export class DictColumn {
	constructor(
		readonly codes: Uint16Array,
		readonly values: readonly string[],
		private readonly validity: Uint8Array | null
	) {}

	get length(): number {
		return this.codes.length;
	}

	get(i: number): string | null {
		if (this.validity && !bitAt(this.validity, i)) return null;
		return this.values[this.codes[i]];
	}
}

/** The catalogue ids of each row. Catalogue and release pairs are shared
 *  through a code per entry. */
export class CrossIdsColumn {
	constructor(
		private readonly list: Uint32Array,
		private readonly codes: Uint16Array,
		private readonly ids: StringColumn,
		private readonly pairs: StringColumn,
		private readonly validity: Uint8Array | null
	) {}

	get length(): number {
		return this.list.length - 1;
	}

	get(i: number): CrossId[] | null {
		if (this.validity && !bitAt(this.validity, i)) return null;
		const out: CrossId[] = [];
		for (let j = this.list[i]; j < this.list[i + 1]; j++) {
			const code = this.codes[j];
			out.push({
				catalogue: this.pairs.get(2 * code) ?? '',
				release: this.pairs.get(2 * code + 1) ?? '',
				catalogueId: this.ids.get(j) ?? ''
			});
		}
		return out;
	}
}

/** A list of float32 values per row, as views on one buffer. */
export class Float32ListColumn {
	constructor(
		readonly offsets: Uint32Array,
		readonly values: Float32Array,
		private readonly validity: Uint8Array | null
	) {}

	get length(): number {
		return this.offsets.length - 1;
	}

	get(i: number): Float32Array | null {
		if (this.validity && !bitAt(this.validity, i)) return null;
		return this.values.subarray(this.offsets[i], this.offsets[i + 1]);
	}
}

/** One bit per row, in the bit order of the validity bitmaps. */
export class BitColumn {
	constructor(
		readonly bytes: Uint8Array,
		readonly length: number
	) {}

	get(i: number): boolean {
		return bitAt(this.bytes, i);
	}
}

/** Info block of a render node. */
export interface NodeInfo {
	/** Centre of the node's box, pc, ICRS axes from the barycentre. */
	centre: [number, number, number];
	/** Distance from the centre to each face, pc. */
	half: number;
	minRange: number;
	maxRange: number;
	/** Largest visibility range in the subtree of child octant k, 0 for no child. */
	childRange: Float32Array;
	depth: number;
	childMask: number;
}

/** Info block of a record tile. */
export interface TileInfo {
	pixel: number;
	level: number;
	/** Table number; 0 for Metadata. */
	table: number;
}

export class Container {
	readonly kind: number;
	readonly token: string;
	readonly rows: number;
	readonly info: DataView;
	private readonly columns = new Map<string, ColumnEntry>();

	constructor(readonly buffer: ArrayBuffer) {
		if (buffer.byteLength < HEADER_SIZE) throw new ContainerFormatError('payload too short');
		const view = new DataView(buffer);
		const magic = decoder.decode(new Uint8Array(buffer, 0, 4));
		if (magic !== MAGIC) throw new ContainerFormatError('not an extrasolar file');
		const version = view.getUint16(4, true);
		if (version !== FORMAT_VERSION) {
			throw new ContainerFormatError(
				`format version ${version}, this code reads ${FORMAT_VERSION}`
			);
		}
		this.kind = view.getUint8(6);
		this.token = decoder.decode(new Uint8Array(buffer, TOKEN_AT, TOKEN_SIZE));
		this.rows = view.getUint32(24, true);
		const count = view.getUint16(28, true);
		const infoSize = view.getUint16(30, true);
		this.info = new DataView(buffer, HEADER_SIZE, infoSize);
		let at = HEADER_SIZE + infoSize;
		for (let c = 0; c < count; c++) {
			const code = view.getUint8(at);
			const flags = view.getUint8(at + 1);
			const buffers = view.getUint8(at + 2);
			const nameSize = view.getUint8(at + 3);
			at += 4;
			const name = decoder.decode(new Uint8Array(buffer, at, nameSize));
			at += nameSize;
			const places: Place[] = [];
			for (let b = 0; b < buffers; b++) {
				const offset = view.getUint32(at, true);
				const length = view.getUint32(at + 4, true);
				if (offset % 8 !== 0 || offset + length > buffer.byteLength) {
					throw new ContainerFormatError(`${name}: buffer ${b} out of place`);
				}
				places.push({ offset, length });
				at += 8;
			}
			const type = TYPE_CODES[code];
			if (!type) throw new ContainerFormatError(`${name}: unknown type ${code}`);
			const hasValidity = (flags & HAS_VALIDITY) !== 0;
			const first = hasValidity ? places.shift() : undefined;
			this.columns.set(name, {
				type,
				validity: first ? new Uint8Array(buffer, first.offset, first.length) : null,
				places
			});
		}
	}

	/** Column names in file order. */
	names(): string[] {
		return [...this.columns.keys()];
	}

	has(name: string): boolean {
		return this.columns.has(name);
	}

	type(name: string): ColumnType {
		return this.entry(name).type;
	}

	/** False for a null row. A float with no value also reads as NaN, an
	 *  integer as 0. */
	isValid(name: string, row: number): boolean {
		const { validity } = this.entry(name);
		return validity === null || bitAt(validity, row);
	}

	bool(name: string): Uint8Array {
		return this.numbers(name, 'bool', Uint8Array);
	}

	int8(name: string): Int8Array {
		return this.numbers(name, 'int8', Int8Array);
	}

	int16(name: string): Int16Array {
		return this.numbers(name, 'int16', Int16Array);
	}

	int32(name: string): Int32Array {
		return this.numbers(name, 'int32', Int32Array);
	}

	uint8(name: string): Uint8Array {
		return this.numbers(name, 'uint8', Uint8Array);
	}

	uint16(name: string): Uint16Array {
		return this.numbers(name, 'uint16', Uint16Array);
	}

	uint32(name: string): Uint32Array {
		return this.numbers(name, 'uint32', Uint32Array);
	}

	float32(name: string): Float32Array {
		return this.numbers(name, 'float32', Float32Array);
	}

	float64(name: string): Float64Array {
		return this.numbers(name, 'float64', Float64Array);
	}

	/** Integer IDs below 2^53 as exact numbers. A null reads as 0. */
	ids(name: string): Float64Array {
		return this.numbers(name, 'id', Float64Array);
	}

	/** Integers that can pass 2^53, such as bit fields. A null reads as 0. */
	uint64(name: string): BigUint64Array {
		return this.numbers(name, 'uint64', BigUint64Array);
	}

	float32List(name: string): Float32ListColumn {
		const { validity, places } = this.typed(name, 'float32_list');
		return new Float32ListColumn(
			this.view(places[0], Uint32Array),
			this.view(places[1], Float32Array),
			validity
		);
	}

	strings(name: string): StringColumn {
		const { validity, places } = this.typed(name, 'string');
		return this.stringList(places[0], places[1], validity);
	}

	dict(name: string): DictColumn {
		const { validity, places } = this.typed(name, 'dict');
		const values = this.stringList(places[1], places[2], null);
		const strings: string[] = [];
		for (let k = 0; k < values.length; k++) strings.push(values.get(k) ?? '');
		return new DictColumn(this.view(places[0], Uint16Array), strings, validity);
	}

	crossIds(name: string): CrossIdsColumn {
		const { validity, places } = this.typed(name, 'cross_ids');
		return new CrossIdsColumn(
			this.view(places[0], Uint32Array),
			this.view(places[1], Uint16Array),
			this.stringList(places[2], places[3], null),
			this.stringList(places[4], places[5], null),
			validity
		);
	}

	bits(name: string): BitColumn {
		const { places } = this.typed(name, 'bits');
		return new BitColumn(this.view(places[0], Uint8Array), this.rows);
	}

	private entry(name: string): ColumnEntry {
		const entry = this.columns.get(name);
		if (!entry) throw new ContainerFormatError(`no column ${name}`);
		return entry;
	}

	private typed(name: string, type: ColumnType): ColumnEntry {
		const entry = this.entry(name);
		if (entry.type !== type) {
			throw new ContainerFormatError(`${name} is ${entry.type}, not ${type}`);
		}
		return entry;
	}

	private numbers<T extends ArrayBufferView>(
		name: string,
		type: ColumnType,
		Kind: {
			new (buffer: ArrayBuffer, offset: number, length: number): T;
			BYTES_PER_ELEMENT: number;
		}
	): T {
		return this.view(this.typed(name, type).places[0], Kind);
	}

	private view<T>(
		place: Place,
		Kind: {
			new (buffer: ArrayBuffer, offset: number, length: number): T;
			BYTES_PER_ELEMENT: number;
		}
	): T {
		return new Kind(this.buffer, place.offset, place.length / Kind.BYTES_PER_ELEMENT);
	}

	private stringList(offsets: Place, bytes: Place, validity: Uint8Array | null): StringColumn {
		return new StringColumn(
			this.view(offsets, Uint32Array),
			new Uint8Array(this.buffer, bytes.offset, bytes.length),
			validity
		);
	}
}

/** The info block of a render node (kind 3). */
export function nodeInfo(container: Container): NodeInfo {
	const info = container.info;
	if (container.kind !== KIND_NODE || info.byteLength !== NODE_INFO_SIZE) {
		throw new ContainerFormatError('not a render node');
	}
	const childRange = new Float32Array(8);
	for (let k = 0; k < 8; k++) childRange[k] = info.getFloat32(40 + 4 * k, true);
	return {
		centre: [info.getFloat64(0, true), info.getFloat64(8, true), info.getFloat64(16, true)],
		half: info.getFloat64(24, true),
		minRange: info.getFloat32(32, true),
		maxRange: info.getFloat32(36, true),
		childRange,
		depth: info.getUint8(72),
		childMask: info.getUint8(73)
	};
}

/** The info block of a record tile (kind 1). */
export function tileInfo(container: Container): TileInfo {
	const info = container.info;
	if (container.kind !== KIND_TILE || info.byteLength !== TILE_INFO_SIZE) {
		throw new ContainerFormatError('not a record tile');
	}
	return { pixel: info.getUint32(0, true), level: info.getUint8(4), table: info.getUint8(5) };
}
