import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { dateToJD, formatJulianDate } from '$lib/format/date';
import type { DateCoverage } from '$lib/fetch/metadata';

/**
 * One group's out-of-range accumulation for a frame. `count === 0` means
 * every member has data at the current jd. `earliestStart`/`latestEnd` cover
 * out-of-range members only, so we can report which side the user crossed.
 */
export interface OutOfRangeGroup {
	count: number;
	earliestStart: number;
	latestEnd: number;
}

export interface OutOfRangeState {
	jd: number;
	/** Zone-level coverage, not a loaded chunk's window — see {@link DateCoverage}. */
	satellites: DateCoverage;
	majorBodies: OutOfRangeGroup;
	focusedOutOfRange: boolean;
}

export function emptyGroup(): OutOfRangeGroup {
	return { count: 0, earliestStart: Infinity, latestEnd: -Infinity };
}

const TOAST_ID = 'out-of-range-data';

let lastSignature: string | null = null;

type DirectionMsgs = {
	after: (date: string) => string;
	before: (date: string) => string;
	outside: () => string;
};

function lineFor(group: OutOfRangeGroup, jd: number, msgs: DirectionMsgs): string | null {
	if (group.count === 0) return null;
	if (Number.isFinite(group.latestEnd) && jd > group.latestEnd) {
		return msgs.after(formatJulianDate(group.latestEnd));
	}
	if (Number.isFinite(group.earliestStart) && jd < group.earliestStart) {
		return msgs.before(formatJulianDate(group.earliestStart));
	}
	return msgs.outside();
}

/** Pre-space-age is folded into `covered`, so only `after`/`gap` warn. */
function satelliteLine(cov: DateCoverage): string | null {
	switch (cov.kind) {
		case 'after':
			return m.out_of_range_satellites_after({
				date: formatJulianDate(dateToJD(new Date(cov.lastMs)))
			});
		case 'gap':
			return m.out_of_range_satellites_outside();
		case 'covered':
			return null;
	}
}

/** Sync a sticky toast to the out-of-range state each frame; cheap no-op when stable. */
export function updateOutOfRangeToast(state: OutOfRangeState): void {
	const lines: string[] = [];

	if (state.focusedOutOfRange) {
		lines.push(m.out_of_range_selected());
	}

	const satLine = satelliteLine(state.satellites);
	if (satLine) lines.push(satLine);

	const majLine = lineFor(state.majorBodies, state.jd, {
		after: (d) => m.out_of_range_major_bodies_after({ date: d }),
		before: (d) => m.out_of_range_major_bodies_before({ date: d }),
		outside: () => m.out_of_range_major_bodies_outside()
	});
	if (majLine) lines.push(majLine);

	const signature = lines.join('\n');
	if (signature === lastSignature) return;
	lastSignature = signature;

	if (lines.length === 0) {
		toast.dismiss(TOAST_ID);
		return;
	}

	toast.warning(m.out_of_range_title(), {
		id: TOAST_ID,
		description: lines.join('\n'),
		duration: Number.POSITIVE_INFINITY,
		closeButton: true
	});
}
