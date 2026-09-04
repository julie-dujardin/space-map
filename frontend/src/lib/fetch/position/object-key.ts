import { buildObjectId, idTypeForPrefix } from './format';

/**
 * A body id as the export carries it: the id-type byte and a signed 32-bit
 * number, packed into one integer as `value * 8 + type`. The bulk indexes
 * (element columns, asteroid buckets, pick ranges) key on this; the
 * `<prefix>-<number>` string is only built for a body that materialises.
 * Packing the type into the low bits keeps every catalogue id below 2^30, so
 * V8 hashes the keys as small integers.
 */
export type ObjectKey = number;

/** Sentinel for "no body" in key arrays (a skipped point-cloud row). */
export const NO_KEY: ObjectKey = -(2 ** 40);

const TYPE_BITS = 8;

export function objectKey(idType: number, value: number): ObjectKey {
	if (idType < 0 || idType >= TYPE_BITS) return NO_KEY;
	return value * TYPE_BITS + idType;
}

export function keyIdType(key: ObjectKey): number {
	return ((key % TYPE_BITS) + TYPE_BITS) % TYPE_BITS;
}

/** The signed 32-bit number of a key. */
export function keyValue(key: ObjectKey): number {
	return (key - keyIdType(key)) / TYPE_BITS;
}

export function keyToId(key: ObjectKey): string | null {
	if (key === NO_KEY) return null;
	return buildObjectId(keyIdType(key), keyValue(key));
}

/** Key of a `<prefix>-<number>` id, or null for a prefix the export never
 *  emits (wikidata-only placeholders) or a non-integer number. */
export function idToKey(id: string): ObjectKey | null {
	const dash = id.indexOf('-');
	if (dash <= 0) return null;
	const idType = idTypeForPrefix(id.slice(0, dash));
	if (idType === undefined) return null;
	const value = Number(id.slice(dash + 1));
	if (!Number.isInteger(value) || value > 2147483647 || value < -2147483648) return null;
	const key = objectKey(idType, value);
	return key === NO_KEY ? null : key;
}

/** Keys of every id in `ids` the export can carry. */
export function keySetOf(ids: Iterable<string>): Set<ObjectKey> {
	const keys = new Set<ObjectKey>();
	for (const id of ids) {
		const key = idToKey(id);
		if (key !== null) keys.add(key);
	}
	return keys;
}
