/**
 * Test-only access to the real extrasolar export beside the repo
 * (`space-map-extrasolar/v1/x/`). Tests on it skip where it is absent.
 */

import { existsSync, readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { Container } from '../container';
import { ExtrasolarStaleError, type ExtrasolarMetadata } from '../files';
import type { LookupSource } from '../lookup';

export const EXPORT = new URL('../../../../../../../space-map-extrasolar/v1/x/', import.meta.url);
export const HAS_EXPORT = existsSync(EXPORT);

/** A decoded payload in a buffer of its own, as the browser has it. */
export function own(bytes: Uint8Array): ArrayBuffer {
	return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

export function readExportFile(path: string): Container {
	return new Container(own(gunzipSync(readFileSync(new URL(path, EXPORT)))));
}

export function exportMetadata(): ExtrasolarMetadata {
	return JSON.parse(readFileSync(new URL('metadata.json', EXPORT), 'utf8')) as ExtrasolarMetadata;
}

/** The lookup's source over the files on disk, counting the files read. */
export function diskSource(
	allowed: (entry: { distribution?: string }) => boolean = () => true
): LookupSource & {
	reads: string[];
} {
	const reads: string[] = [];
	return {
		reads,
		metadata: async () => exportMetadata(),
		file: async (path, token) => {
			reads.push(path);
			const file = readExportFile(path);
			if (file.token !== token) throw new ExtrasolarStaleError(path, file.token, token);
			return file;
		},
		allowed
	};
}
