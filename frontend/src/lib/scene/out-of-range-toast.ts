import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { formatJulianDate } from '$lib/format/date';

/**
 * One group's out-of-range accumulation for a single frame. `count === 0`
 * means every member of the group has data at the current jd.
 *
 * `earliestStart` / `latestEnd` are taken across out-of-range members only,
 * so after comparing against `jd` we can report the group's data boundary
 * on the side the user crossed.
 */
export interface OutOfRangeGroup {
	count: number;
	earliestStart: number;
	latestEnd: number;
}

export interface OutOfRangeState {
	jd: number;
	satellites: OutOfRangeGroup;
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

/**
 * Sync a single sticky toast to the current out-of-range state. Fires once on
 * transition, updates in place when the contents change, and dismisses when
 * everything is back in range. Called every frame; cheap no-op when stable.
 */
export function updateOutOfRangeToast(state: OutOfRangeState): void {
	const lines: string[] = [];

	if (state.focusedOutOfRange) {
		lines.push(m.out_of_range_selected());
	}

	const satLine = lineFor(state.satellites, state.jd, {
		after: (d) => m.out_of_range_satellites_after({ date: d }),
		before: (d) => m.out_of_range_satellites_before({ date: d }),
		outside: () => m.out_of_range_satellites_outside()
	});
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
		duration: Number.POSITIVE_INFINITY
	});
}

/** Reset module state — for tests and for scene teardown. */
export function resetOutOfRangeToast(): void {
	lastSignature = null;
	toast.dismiss(TOAST_ID);
}
