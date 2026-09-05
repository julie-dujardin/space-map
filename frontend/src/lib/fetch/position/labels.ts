/**
 * Per-language promoted-set fetcher. The map's keys are the auto-promote
 * set; values carry the display name and per-body flags.
 *
 * Line format: `{id}\x1f{name}\x1f{flags}`. Flags is a single-character
 * set; `m` marks a body as *minor* (collapsed halo by default).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { labelsUrl } from '$lib/fetch/position/format';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';

/** ASCII Unit Separator — delimiter between fields in label files. */
const US = '\x1f';

export interface LabelEntry {
	name: string;
	/** True for designation-only moons — render as a collapsed halo by default. */
	isMinor: boolean;
}

export type LabelMap = ReadonlyMap<string, LabelEntry>;

export function parseLabels(text: string): Map<string, LabelEntry> {
	const out = new Map<string, LabelEntry>();
	if (!text) return out;
	for (const line of text.split('\n')) {
		const sep1 = line.indexOf(US);
		if (sep1 === -1) continue; // malformed/blank line
		const id = line.slice(0, sep1);
		const rest = line.slice(sep1 + 1);
		// Empty names (`{id}\x1f\x1f{flags}`) are kept on purpose: the exporter
		// emits them for curated promoted bodies that have no Wikidata or DB
		// name, and the renderer keys auto-promote on the map. Callers that
		// read `name` should coalesce `''` → fallback themselves.
		const sep2 = rest.indexOf(US);
		const name = sep2 === -1 ? rest : rest.slice(0, sep2);
		const flags = sep2 === -1 ? '' : rest.slice(sep2 + 1);
		out.set(id, { name, isMinor: flags.includes('m') });
	}
	return out;
}

/** Locale switching reloads the page (paraglide default), so a single
 *  in-memory promise per lang is enough — no LRU. */
const labelsByLang = new Map<string, Promise<LabelMap>>();

export async function fetchLabels(lang: string = getLocale()): Promise<LabelMap> {
	let p = labelsByLang.get(lang);
	if (!p) {
		p = (async () => {
			const url = labelsUrl(lang);
			// Phase 1 of boot waits on this small file; it must not queue behind
			// the chunk fetches in flight.
			const res = await fetchWithTimeout(url, { priority: 'high' });
			if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
			const ds = new DecompressionStream('gzip');
			const text = await new Response(res.body!.pipeThrough(ds)).text();
			return parseLabels(text);
		})();
		labelsByLang.set(lang, p);
		// Evict on rejection — labels are on the scene critical path; a poisoned
		// memo would block every later chunk's name/flag resolution.
		p.catch(() => {
			if (labelsByLang.get(lang) === p) labelsByLang.delete(lang);
		});
	}
	return p;
}
