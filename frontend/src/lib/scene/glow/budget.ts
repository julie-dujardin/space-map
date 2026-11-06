/** How much of a map one frame may march, from measured frame time. */

/** Frame time (ms) over which a frame does less. */
const SLOW_FRAME_MS = 20;
/** Frame time (ms) under which it does more. */
const FAST_FRAME_MS = 17.5;
const GROWTH = 1.25;
/** Each frame the ceiling rises by this, so a slow moment does not last. */
const CEILING_GROWTH = 1.02;
const LEAST_ROWS = 4;
/** Share of the rows of a slow frame that the budget may grow back to at once. */
const CEILING_SHARE = 0.75;

export class MarchBudget {
	/** Rows of a map for the next frame. */
	rows: number;
	/** Where frames went slow. Under it, a budget that grows does not go slow again. */
	private ceiling: number;

	constructor(private readonly most: number) {
		this.rows = Math.max(Math.floor(most / 8), LEAST_ROWS);
		this.ceiling = most;
	}

	/** Note the length of a frame that follows a march. */
	note(frameMs: number): void {
		if (frameMs <= 0) return;
		if (frameMs > SLOW_FRAME_MS) {
			this.ceiling = this.rows * CEILING_SHARE;
			this.rows = Math.max(Math.floor(this.rows / 2), LEAST_ROWS);
			return;
		}
		this.ceiling = Math.min(this.ceiling * CEILING_GROWTH, this.most);
		if (frameMs < FAST_FRAME_MS) {
			this.rows = Math.max(
				Math.min(Math.ceil(this.rows * GROWTH), Math.floor(this.ceiling)),
				LEAST_ROWS
			);
		}
	}
}
