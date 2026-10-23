/**
 * Files of the extrasolar export (`docs/export-format/extrasolar.md`), from
 * the host's own base URL. They are `metadata.json`, the record tiles, the
 * split tables, the render nodes and the ID files.
 *
 * Each file is fetched as `{base}/v1/x/{path}?v={token}`, and its header
 * repeats the token. A header token that is not the one in `metadata.json`
 * comes from another export. The fetch then fails, and the stale listeners
 * hear of it once, so the page can prompt a reload.
 */

import { host, textureAllowed } from '$lib/host';
import { gunzip } from '$lib/fetch/gz';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import { Container, type ColumnType } from './container';

export const EXTRASOLAR_FORMAT = 1;

export interface ExtrasolarColumn {
	name: string;
	type: ColumnType;
}

/** One record table. Its split table cuts it into HEALPix pixels. */
export interface ExtrasolarTable {
	/** Table number of the ID scheme; null for Metadata, which never mints. */
	number: number | null;
	token: string;
	/** Path of the split table. */
	split: string;
	/** Path pattern of a tile, with `{level}` and `{pixel}`. */
	tile: string;
	max_rows: number;
	rows: number;
	tiles: number;
	columns: ExtrasolarColumn[];
	distribution?: string;
}

/** One render tree, an octree of nodes cut by visibility range. */
export interface ExtrasolarTree {
	token: string;
	/** Path of the root node. */
	root: string;
	/** Path patterns of a node and of its ID file, with `{name}`. */
	node: string;
	ids: string;
	/** Centre and half size of the root box, in `units`. */
	centre: [number, number, number];
	half_size: number;
	/** Rows a full node holds. */
	node_rows: number;
	/** Apparent magnitude the stored visibility ranges are for. */
	range_limit_mag: number;
	units: string;
	frame: string;
	classes: Record<string, number>;
	nodes: number;
	depth: number;
	rows: number;
	columns: ExtrasolarColumn[];
	id_columns: ExtrasolarColumn[];
	distribution?: string;
}

export interface ExtrasolarCredit {
	name: string;
	organisation: string;
	source: string;
	license?: string;
	attribution?: string;
	citation?: string;
}

export interface ExtrasolarMetadata {
	format: number;
	exported: string;
	registry: { ingest: number; host: string };
	tables: Record<string, ExtrasolarTable>;
	trees: Record<string, ExtrasolarTree>;
	credits: ExtrasolarCredit[];
}

/** A file whose header token is not the one `metadata.json` lists. */
export class ExtrasolarStaleError extends Error {
	constructor(path: string, found: string, expected: string) {
		super(`${path}: token ${found}, expected ${expected}`);
		this.name = 'ExtrasolarStaleError';
	}
}

/** Root of the extrasolar export; empty where this host serves none. */
export function extrasolarBase(): string {
	return host().extrasolarUrl;
}

/** Whether this host may fetch the files of a table or tree with this
 *  `distribution` (the same ladder as surface maps). */
export function extrasolarAllowed(entry: { distribution?: string }): boolean {
	return textureAllowed(entry.distribution);
}

/** Fill a path pattern of `metadata.json`: `{name}`, `{level}`, `{pixel}`. */
export function extrasolarPath(pattern: string, fields: Record<string, string | number>): string {
	return pattern.replace(/\{(\w+)\}/g, (whole, key: string) => {
		const value = fields[key];
		if (value === undefined) throw new Error(`extrasolarPath: no ${key} for ${pattern}`);
		return String(value);
	});
}

export function extrasolarUrl(path: string, token: string): string {
	return `${extrasolarBase()}/v1/x/${path}?v=${token}`;
}

let metadataBase: string | null = null;
let metadataPending: Promise<ExtrasolarMetadata | null> | null = null;

/**
 * `metadata.json`, once per base URL, or null where the host has no
 * extrasolar URL. A failure is not kept, so the next call tries again.
 */
export function fetchExtrasolarMetadata(): Promise<ExtrasolarMetadata | null> {
	const base = extrasolarBase();
	if (metadataPending && metadataBase === base) return metadataPending;
	metadataBase = base;
	if (base === '') {
		metadataPending = Promise.resolve(null);
		return metadataPending;
	}
	const p = (async () => {
		// This file has no token. A stale copy would hold old tokens, and the
		// reload that each file prompts would read the same copy again.
		const res = await fetchWithTimeout(`${base}/v1/x/metadata.json`, { cache: 'no-cache' });
		if (!res.ok) throw new Error(`extrasolar metadata.json returned ${res.status}`);
		const meta = (await res.json()) as ExtrasolarMetadata;
		if (meta.format !== EXTRASOLAR_FORMAT) {
			throw new Error(`extrasolar format ${meta.format}, this code reads ${EXTRASOLAR_FORMAT}`);
		}
		return meta;
	})();
	metadataPending = p;
	p.catch(() => {
		if (metadataPending === p) metadataPending = null;
	});
	return p;
}

const staleListeners = new Set<() => void>();
let staleReported = false;

/** Hear once when a file is from another export than `metadata.json`.
 *  Returns an unsubscribe. */
export function onExtrasolarStale(listener: () => void): () => void {
	staleListeners.add(listener);
	return () => staleListeners.delete(listener);
}

function reportStale(): void {
	if (staleReported) return;
	staleReported = true;
	for (const listener of staleListeners) listener();
}

export interface ExtrasolarFetchOptions {
	signal?: AbortSignal;
	priority?: RequestPriority;
}

/**
 * Fetch one `.bin.gz` file, decode it and check its token. Rejects with
 * {@link ExtrasolarStaleError} on a token from another export.
 */
export async function fetchExtrasolarFile(
	path: string,
	token: string,
	options: ExtrasolarFetchOptions = {}
): Promise<Container> {
	const url = extrasolarUrl(path, token);
	const res = await fetchWithTimeout(url, { signal: options.signal, priority: options.priority });
	if (!res.ok) throw new Error(`${url} returned ${res.status}`);
	// The server sends no Content-Encoding. The payload is decoded here, into its own buffer.
	const container = new Container(await gunzip(res).arrayBuffer());
	if (container.token !== token) {
		reportStale();
		throw new ExtrasolarStaleError(path, container.token, token);
	}
	return container;
}
