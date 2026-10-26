/**
 * IDs of the extrasolar catalogue: `serial · 2^29 + table · 2^24 + cell`, as
 * a bare decimal in the URL (`/x/<id>/<name>`). The cell is a HEALPix level-10
 * nested pixel, ICRS. IDs stay JavaScript numbers: bit operators cut them to
 * 32 bits, so the fields come out by division.
 */

export const CELL_LEVEL = 10;
/** Cells at level 10: 12 · 4^10. */
export const CELL_COUNT = 12 * 4 ** CELL_LEVEL;
export const FIRST_TABLE = 1;
export const LAST_TABLE = 30;

const CELL_SPAN = 2 ** 24;
const TABLE_SPAN = 32;
const SERIAL_SPAN = 2 ** 29;

/** No leading zero, at most 16 digits; the size check is on the number. */
const ID_TEXT = /^[1-9][0-9]{0,15}$/;

/** Prefix of an extrasolar object in the scene's id space (`x-22137869`). */
export const EXTRASOLAR_PREFIX = 'x-';

export interface IdParts {
	serial: number;
	table: number;
	cell: number;
}

export function decodeId(id: number): IdParts {
	return {
		serial: Math.floor(id / SERIAL_SPAN),
		table: Math.floor(id / CELL_SPAN) % TABLE_SPAN,
		cell: id % CELL_SPAN
	};
}

export function cellOf(id: number): number {
	return id % CELL_SPAN;
}

export function tableOf(id: number): number {
	return Math.floor(id / CELL_SPAN) % TABLE_SPAN;
}

/**
 * The ID a URL segment names, or null for a 404. `tables` holds the table
 * numbers the export lists; without it, any number that can be given passes,
 * so the check runs before `metadata.json` is in.
 */
export function parseExtrasolarId(text: string, tables?: ReadonlySet<number>): number | null {
	if (!ID_TEXT.test(text)) return null;
	const id = Number(text);
	// Rounding is monotonic, so every value from 2^53 up reads as 2^53 or more.
	if (id > Number.MAX_SAFE_INTEGER) return null;
	const { table, cell } = decodeId(id);
	if (cell >= CELL_COUNT) return null;
	if (tables ? !tables.has(table) : table < FIRST_TABLE || table > LAST_TABLE) return null;
	return id;
}

/** An id of the extrasolar export's namespace: a star (`x-<id>`) or a
 *  planet (`x-<host>-b-<n>`). Neither has an object bundle. */
export function isExtrasolarObjectId(objectId: string): boolean {
	return objectId.startsWith(EXTRASOLAR_PREFIX);
}

/** An object of the extrasolar catalogue that is not a planet: the id its
 *  lookup reads. A malformed `x-` id counts, so that the lookup refuses it. */
export function isStarObjectId(objectId: string): boolean {
	return isExtrasolarObjectId(objectId) && planetOfObjectId(objectId) === null;
}

export function extrasolarObjectId(id: number): string {
	return `${EXTRASOLAR_PREFIX}${id}`;
}

/** The ID of a scene id such as `x-22137869`, or null when it names none. */
export function extrasolarIdOf(objectId: string): number | null {
	if (!isExtrasolarObjectId(objectId)) return null;
	return parseExtrasolarId(objectId.slice(EXTRASOLAR_PREFIX.length));
}

/** A planet's scene id, `x-<host>-b-<n>`, after its page `/x/<host>/b/<n>`. */
export function planetObjectId(host: number, n: number): string {
	return `${EXTRASOLAR_PREFIX}${host}-b-${n}`;
}

const PLANET_ID = /^x-([1-9][0-9]{0,15})-b-([1-9][0-9]{0,4})$/;

/** The host ID and number of a planet's scene id, or null when it names none. */
export function planetOfObjectId(objectId: string): { host: number; n: number } | null {
	const m = PLANET_ID.exec(objectId);
	if (!m) return null;
	const host = parseExtrasolarId(m[1]);
	return host === null ? null : { host, n: Number(m[2]) };
}
