/**
 * A trajectory as the map draws it: its geometry, and what to write at each end.
 *
 * The two ends are the whole of what tells one trajectory from another on
 * screen — they all leave the same body for the same body and only the dates
 * differ, so where each arc starts and stops *is* the departure and arrival
 * date.
 */

import type { TrajectoryPath } from '$lib/math/travel/path';

/** One end of a trip, as a label: where, and when the craft is there. */
export interface PathEndLabel {
	name: string;
	when: string;
}

export interface LabelledPath {
	/** Which trajectory this is, for tying the arc on the map to its mark on the
	 *  launch-window field. The route profile, in practice. */
	id: string;
	path: TrajectoryPath;
	departure: PathEndLabel;
	arrival: PathEndLabel;
	/** Read this trajectory — what pressing either of its labels does. Absent on
	 *  the one already being read, whose labels are then only a caption. */
	onSelect?: () => void;
	/** The pointer entered or left one of its labels, so whatever else stands for
	 *  this trajectory can answer. */
	onHover?: (hovered: boolean) => void;
}
