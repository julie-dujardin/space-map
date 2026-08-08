/**
 * `Intl.DurationFormat` is in every browser we target but not yet in
 * TypeScript's lib. Only the surface the app calls is declared.
 */
declare namespace Intl {
	type DurationUnit =
		| 'years'
		| 'months'
		| 'weeks'
		| 'days'
		| 'hours'
		| 'minutes'
		| 'seconds'
		| 'milliseconds'
		| 'microseconds'
		| 'nanoseconds';

	type Duration = Partial<Record<DurationUnit, number>>;

	type DurationUnitDisplay = 'long' | 'short' | 'narrow';

	interface DurationFormatOptions {
		style?: 'long' | 'short' | 'narrow' | 'digital';
		years?: DurationUnitDisplay;
		yearsDisplay?: 'auto' | 'always';
		months?: DurationUnitDisplay;
		monthsDisplay?: 'auto' | 'always';
		days?: DurationUnitDisplay;
		daysDisplay?: 'auto' | 'always';
		hours?: DurationUnitDisplay | 'numeric' | '2-digit';
		hoursDisplay?: 'auto' | 'always';
		minutes?: DurationUnitDisplay | 'numeric' | '2-digit';
		minutesDisplay?: 'auto' | 'always';
		seconds?: DurationUnitDisplay | 'numeric' | '2-digit';
		secondsDisplay?: 'auto' | 'always';
	}

	class DurationFormat {
		constructor(locales?: string | string[], options?: DurationFormatOptions);
		format(duration: Duration): string;
	}
}
