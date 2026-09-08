import { unixMsToJD } from '$lib/time/jd';
import type { NoticeSink } from './notice';
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

type Side = 'after' | 'before' | 'outside' | 'gap' | null;

/** Sends the out-of-range notice for one map, and only when it changes: the
 *  state is recomputed every frame, so the last report is held as scalars and
 *  nothing is allocated while it is stable. */
export class OutOfRangeNotifier {
	private focused = false;
	private satSide: Side = null;
	private satJd = NaN;
	private majSide: Side = null;
	private majJd = NaN;

	constructor(private readonly notices: NoticeSink) {}

	update(state: OutOfRangeState): void {
		const { jd, majorBodies: group, satellites: cov } = state;
		let majSide: Side = null;
		let majJd = NaN;
		if (group.count > 0) {
			if (Number.isFinite(group.latestEnd) && jd > group.latestEnd) {
				majSide = 'after';
				majJd = group.latestEnd;
			} else if (Number.isFinite(group.earliestStart) && jd < group.earliestStart) {
				majSide = 'before';
				majJd = group.earliestStart;
			} else {
				majSide = 'outside';
			}
		}
		// Pre-space-age is folded into `covered`, so only `after`/`gap` warn.
		const satSide: Side = cov.kind === 'covered' ? null : cov.kind;
		const satJd = cov.kind === 'after' ? unixMsToJD(cov.lastMs) : NaN;
		const focused = state.focusedOutOfRange;
		if (
			focused === this.focused &&
			satSide === this.satSide &&
			Object.is(satJd, this.satJd) &&
			majSide === this.majSide &&
			Object.is(majJd, this.majJd)
		) {
			return;
		}
		Object.assign(this, { focused, satSide, satJd, majSide, majJd });

		if (!focused && satSide === null && majSide === null) {
			this.notices.dismiss('out-of-range');
			return;
		}
		this.notices.notify({
			topic: 'out-of-range',
			focusedOutOfRange: focused,
			satellites:
				satSide === 'after'
					? { side: 'after', jd: satJd }
					: satSide === 'gap'
						? { side: 'gap' }
						: null,
			majorBodies:
				majSide === 'after' || majSide === 'before'
					? { side: majSide, jd: majJd }
					: majSide === 'outside'
						? { side: 'outside' }
						: null
		});
	}
}
