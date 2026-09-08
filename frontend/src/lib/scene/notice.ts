/**
 * Conditions the scene reports while it runs: the clock has left the data, or
 * it stopped at a probe's data wall. Raw dates and ids, never sentences — the
 * page around the map words them and decides how they are shown.
 */

/** A coverage edge the clock has crossed, and where it lies. */
export interface CoverageEdge {
	side: 'before' | 'after';
	jd: number;
}

/** Which groups lack data at the current time. */
export interface OutOfRangeNotice {
	topic: 'out-of-range';
	focusedOutOfRange: boolean;
	/** Zone-level satellite coverage: past the archive, or inside a hole. */
	satellites: { side: 'after'; jd: number } | { side: 'gap' } | null;
	majorBodies: CoverageEdge | { side: 'outside' } | null;
}

/** The clock stopped at the focused probe's trajectory data wall. */
export interface CoveragePauseNotice {
	topic: 'coverage-pause';
	name: string;
	direction: 'forward' | 'backward';
	jd: number;
}

export type Notice = OutOfRangeNotice | CoveragePauseNotice;
export type NoticeTopic = Notice['topic'];

/** Where the scene sends them. One live notice per topic: a repeat replaces
 *  the previous one, and the topic is dismissed when the condition clears. */
export interface NoticeSink {
	notify(notice: Notice): void;
	dismiss(topic: NoticeTopic): void;
}
