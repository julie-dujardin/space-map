import { getLocale } from '$lib/paraglide/runtime.js';

/** YYYYMMDD int → calendar year (negative = BCE). */
export function inceptionYear(yyyymmdd: number): number {
	return Math.trunc(yyyymmdd / 10000);
}

/** DOM id for a result row, shared by the option elements and the combobox
 *  input's aria-activedescendant. */
export function optionDomId(hitId: string): string {
	return `search-option-${hitId}`;
}

/** Upper-case the first character only, for filter labels (the `type_*` keys are
 *  sentence-case for inline use — "moon of Saturn" — so we capitalize at display
 *  rather than mutate them). No-op on already-capitalized or non-Latin text. */
export function capitalize(s: string): string {
	return s ? s[0].toLocaleUpperCase(getLocale()) + s.slice(1) : s;
}
