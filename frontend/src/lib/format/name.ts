import { getLocale } from '$lib/host';

/** A record that the export names in every language: the global name, and the
 *  names in the languages where they differ from it. */
export interface Named<N extends string | null = string> {
	name: N;
	names?: Record<string, string>;
}

/** The name of `record` in `lang`. */
export function localName<N extends string | null>(
	record: Named<N>,
	lang: string = getLocale()
): string | N {
	return record.names?.[lang] ?? record.name;
}

/** `names` in the alphabetical order of `lang`, sorted in place. */
export function sortNames(names: string[], lang: string = getLocale()): string[] {
	return names.sort(new Intl.Collator(lang).compare);
}
