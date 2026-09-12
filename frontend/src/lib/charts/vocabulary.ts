/**
 * The one shape every chart label lookup has: a key the pipeline emits, a
 * vocabulary the frontend keeps, and a warning where the two have drifted.
 *
 * A missing key is a curation gap, not a failure — the chart still draws, so
 * each site picks what it prints instead.
 */

import * as m from '$lib/paraglide/messages.js';

/**
 * `fallback` fixes the return type per site: the key itself, an empty string,
 * or `null` where the caller has something better to show than a slug.
 */
export function named<T extends string | null>(
	table: Record<string, () => string>,
	key: string,
	what: string,
	fallback: T
): string | T;
/** Colours live in CSS, so the vocabulary is a set of keys and `value` the
 *  variable built from one that is in it. */
export function named<T extends string | null>(
	known: ReadonlySet<string>,
	key: string,
	what: string,
	fallback: T,
	value: string
): string | T;
export function named<T extends string | null>(
	source: Record<string, () => string> | ReadonlySet<string>,
	key: string,
	what: string,
	fallback: T,
	value = ''
): string | T {
	if (source instanceof Set) {
		if (source.has(key)) return value;
	} else {
		const fn = (source as Record<string, () => string>)[key];
		if (fn) return fn();
	}
	console.warn(`Missing ${what}: ${key}`);
	return fallback;
}

/**
 * The same, where the datum is the key: a formula or symbol names its own
 * message, so the message catalogue is the table.
 */
export function namedByKey(prefix: string, raw: string, what: string, fallback: string): string {
	const key = `${prefix}${raw.toLowerCase().replace('-', '_')}`;
	const fn = (m as unknown as Record<string, (() => string) | undefined>)[key];
	if (!fn) {
		console.warn(`Missing ${what}: ${key}`);
		return fallback;
	}
	return fn();
}
