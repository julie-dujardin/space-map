/**
 * How a hazard is written down.
 *
 * Shared by the row of trajectories, the detail below it and the chip on the
 * map, so the same hazard reads the same way wherever it turns up. Deliberately
 * separate from `hazards.ts`, which knows nothing about a locale — and it only
 * ever imports the hazard *types*, so the map can pull this in without dragging
 * the trajectory kernel onto the first frame.
 */

import * as m from '$lib/paraglide/messages.js';
import { ltrIsolate } from '$lib/format/bidi';
import { formatDurationNarrow, SECONDS_PER_DAY } from '$lib/format/duration';
import { formatKelvin } from '$lib/format/temperature';
import type { AdjustedHazard, Hazard, HazardKind } from './hazards';
import { equilibriumTempK } from './sunlight';
import { formatDv, formatDvBrief } from './format';

export function hazardName(kind: HazardKind): string {
	switch (kind) {
		case 'solar-heat':
			return m.travel_hazard_heat();
		case 'solar-power':
			return m.travel_hazard_power();
		case 'conjunction':
			return m.travel_hazard_conjunction();
		case 'signal-lag':
			return m.travel_hazard_lag();
		case 'aeroassist':
			return m.travel_hazard_aero();
	}
}

/** Two significant figures, which is more than any of these are known to. */
function significant(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/** Sunlight as a percentage: whole numbers where there are any, two figures
 *  where the whole number would be zero. */
function percent(fraction: number): string {
	const value = fraction * 100;
	return value >= 10 ? Math.round(value).toString() : significant(value);
}

/**
 * A lag rounded to the minute once it is minutes.
 *
 * The seconds are false precision — the geometry moves further than that in an
 * hour — and "49m 56s" reads as a measurement rather than as the scale of the
 * problem, which is the only thing being said.
 */
function lag(seconds: number): string {
	return formatDurationNarrow(roundLag(seconds) / SECONDS_PER_DAY);
}

function roundLag(seconds: number): number {
	return seconds >= 60 ? Math.round(seconds / 60) * 60 : seconds;
}

/**
 * The shortest form: what fits on a row of trajectories, and on a chip beside
 * the arc. A figure where the figure is the point, a phrase where it is not.
 */
export function hazardChip(hazard: Hazard): string {
	switch (hazard.kind) {
		case 'solar-heat':
			return m.travel_hazard_heat_chip({ value: significant(hazard.peak) });
		case 'solar-power':
			return m.travel_hazard_power_chip({ value: percent(hazard.peak) });
		case 'conjunction':
			return m.travel_hazard_conjunction_chip();
		case 'signal-lag':
			return m.travel_hazard_lag_chip({ value: lag(hazard.peak) });
		case 'aeroassist':
			return m.travel_hazard_aero_chip({ value: formatDvBrief(hazard.peak) });
	}
}

/** The figure that sits on the right of a detail row. */
export function hazardValue(hazard: Hazard): string {
	switch (hazard.kind) {
		case 'solar-heat':
			return m.travel_hazard_heat_value({ value: significant(hazard.peak) });
		case 'solar-power':
			return m.travel_hazard_power_value({ value: percent(hazard.peak) });
		case 'conjunction':
			return m.travel_hazard_conjunction_value({ value: hazard.peak.toFixed(1) });
		case 'signal-lag':
			return m.travel_hazard_lag_value({ value: lag(hazard.peak) });
		case 'aeroassist':
			return formatDv(hazard.peak);
	}
}

/**
 * What it means for the craft, in a sentence.
 *
 * `originName` is only read by the conjunction, which is the one hazard defined
 * against the place the trip left rather than against the trip itself.
 */
export function hazardDetail(hazard: Hazard, originName: string): string {
	switch (hazard.kind) {
		case 'solar-heat':
			return m.travel_hazard_heat_detail({
				au: ltrIsolate((hazard.auAtPeak ?? 0).toFixed(2)),
				temp: formatKelvin(equilibriumTempK(hazard.auAtPeak ?? 1))
			});
		case 'solar-power':
			return m.travel_hazard_power_detail({
				au: ltrIsolate((hazard.auAtPeak ?? 0).toFixed(1)),
				value: ltrIsolate(percent(hazard.peak))
			});
		case 'conjunction':
			return m.travel_hazard_conjunction_detail({ origin: originName });
		case 'signal-lag':
			// The round trip, not the one-way figure beside it: how long it takes to
			// hear back is the whole of what this row adds. Doubled *after* rounding,
			// so it cannot read as an odd multiple of the figure above it.
			return m.travel_hazard_lag_detail({
				value: ltrIsolate(formatDurationNarrow((roundLag(hazard.peak) * 2) / SECONDS_PER_DAY))
			});
		case 'aeroassist':
			return m.travel_hazard_aero_detail({ value: formatDv(hazard.peak) });
	}
}

/** The extra line a craft adds to a hazard, or null when it has nothing to say. */
export function hazardCraftNote(hazard: AdjustedHazard): string | null {
	const note = hazard.craftNote;
	if (!note) return null;
	return note.kind === 'nuclear-power'
		? m.travel_hazard_craft_nuclear()
		: m.travel_hazard_craft_entry({ value: formatDv(note.ratedKms) });
}

/** The months of passes an aerobraking arrival adds, when it has any. */
export function hazardCampaign(hazard: Hazard): string | null {
	if (hazard.kind !== 'aeroassist') return null;
	const days = hazard.endJd - hazard.startJd;
	if (!(days > 1)) return null;
	return m.travel_hazard_aero_campaign({ value: formatDurationNarrow(days) });
}
