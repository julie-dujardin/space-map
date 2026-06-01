/**
 * SMNF binary format reader — IAU planetary nomenclature features.
 *
 * Must stay in sync with `data/src/space_map_data/export/nomenclature/format.py`.
 *
 * File header (16 bytes):
 *   0   char[4]  magic = "SMNF"
 *   4   uint16   version = 1
 *   6   uint8    reserved
 *   7   uint8    reserved
 *   8   uint32   feature_count
 *   12  uint32   reserved
 *
 * Per-feature record (20 bytes):
 *   0   uint32   feature_id
 *   4   int32    center_lat_e7        (planetographic, ±90)
 *   8   uint32   center_lon_e7        (planetographic, east-positive 0..360)
 *   12  uint32   diameter_m
 *   16  char[2]  type_code (ASCII; trailing \0 trimmed)
 *   18  uint8    flags
 *   19  uint8    reserved
 */

export const MAGIC = 0x464e4d53; // "SMNF" as little-endian uint32
export const VERSION = 1;
export const HEADER_SIZE = 16;
export const RECORD_SIZE = 20;

export interface NomenclatureRecord {
	featureId: number;
	/** Planetographic latitude in degrees. */
	lat: number;
	/** Planetographic longitude in degrees, as given by the IAU KML. */
	lon: number;
	/** Feature diameter in metres; 0 when the IAU dataset omits it. */
	diameterM: number;
	/** IAU 2-letter type code (e.g. "AA", "MO", "LI"). */
	typeCode: string;
	flags: number;
}

export function parseNomenclature(buffer: ArrayBuffer): NomenclatureRecord[] {
	const view = new DataView(buffer);
	const magic = view.getUint32(0, true);
	if (magic !== MAGIC) {
		throw new Error(`Invalid nomenclature file: bad magic 0x${magic.toString(16)}`);
	}
	const version = view.getUint16(4, true);
	if (version !== VERSION) {
		throw new Error(`Unsupported nomenclature file version: ${version}`);
	}
	const count = view.getUint32(8, true);

	const records: NomenclatureRecord[] = new Array(count);
	for (let i = 0; i < count; i++) {
		const offset = HEADER_SIZE + i * RECORD_SIZE;
		const c0 = view.getUint8(offset + 16);
		const c1 = view.getUint8(offset + 17);
		const typeCode = c1 === 0 ? String.fromCharCode(c0) : String.fromCharCode(c0, c1);
		records[i] = {
			featureId: view.getUint32(offset, true),
			lat: view.getInt32(offset + 4, true) / 1e7,
			lon: view.getUint32(offset + 8, true) / 1e7,
			diameterM: view.getUint32(offset + 12, true),
			typeCode,
			flags: view.getUint8(offset + 18)
		};
	}
	return records;
}
