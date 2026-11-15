/**
 * Where the names of a chart go. Each name sits beside its star, on the side
 * with the least in its way. A name with no free side is left out.
 */

export interface LabelCandidate {
	/** The star, in CSS pixels. */
	x: number;
	y: number;
	/** The text box. */
	width: number;
	height: number;
}

export interface LabelBox {
	left: number;
	top: number;
	width: number;
	height: number;
}

export interface PlacedLabel extends LabelBox {
	/** Index of its candidate. */
	index: number;
}

export type Segment = readonly [x1: number, y1: number, x2: number, y2: number];

export interface LabelOptions {
	/** The frame, in CSS pixels. */
	width: number;
	height: number;
	/** From the star to the text. */
	gap: number;
	/** The most names to place. */
	limit: number;
	/** Lines that a name should stay off. */
	segments?: readonly Segment[];
	/** Stars that no name may cover. */
	points?: readonly (readonly [number, number])[];
	/** Boxes that are taken before the first name. */
	taken?: readonly LabelBox[];
}

/** Clear space between two names, and between a name and the edge. */
const PAD = 3;
/** A line under a name costs this much more than the worst side. */
const CROSSING_COST = 10;

/** The sides of a star, the best first: [x share, y share] of the box. */
const SIDES: readonly (readonly [number, number])[] = [
	[1, 0],
	[-1, 0],
	[1, -1],
	[1, 1],
	[-1, -1],
	[-1, 1],
	[0, -1],
	[0, 1]
];

function boxAt(candidate: LabelCandidate, [sx, sy]: readonly [number, number], gap: number) {
	const { x, y, width, height } = candidate;
	// A corner box moves in by a part of the gap, so it stays near the star.
	const reach = sx !== 0 && sy !== 0 ? gap * 0.6 : gap;
	const left = sx > 0 ? x + reach : sx < 0 ? x - reach - width : x - width / 2;
	const top = sy > 0 ? y + reach : sy < 0 ? y - reach - height : y - height / 2;
	return { left, top, width, height };
}

function boxesMeet(a: LabelBox, b: LabelBox): boolean {
	return (
		a.left < b.left + b.width + PAD &&
		a.left + a.width + PAD > b.left &&
		a.top < b.top + b.height + PAD &&
		a.top + a.height + PAD > b.top
	);
}

function holds(box: LabelBox, x: number, y: number): boolean {
	return (
		x > box.left - PAD &&
		x < box.left + box.width + PAD &&
		y > box.top - PAD &&
		y < box.top + box.height + PAD
	);
}

/** Whether a segment passes through a box (Liang-Barsky). */
export function segmentMeetsBox([x1, y1, x2, y2]: Segment, box: LabelBox): boolean {
	let from = 0;
	let to = 1;
	const dx = x2 - x1;
	const dy = y2 - y1;
	const edges = [
		[-dx, x1 - box.left],
		[dx, box.left + box.width - x1],
		[-dy, y1 - box.top],
		[dy, box.top + box.height - y1]
	];
	for (const [p, q] of edges) {
		if (p === 0) {
			if (q < 0) return false;
			continue;
		}
		const t = q / p;
		if (p < 0) from = Math.max(from, t);
		else to = Math.min(to, t);
		if (from > to) return false;
	}
	return true;
}

/**
 * Place the candidates in their order, so the first is the most important. A
 * name stays in the frame, off the names before it and off every other star.
 */
export function placeNames(
	candidates: readonly LabelCandidate[],
	options: LabelOptions
): PlacedLabel[] {
	const { width, height, gap, limit, segments = [], points = [] } = options;
	const taken: LabelBox[] = [...(options.taken ?? [])];
	const placed: PlacedLabel[] = [];
	for (let index = 0; index < candidates.length && placed.length < limit; index++) {
		const candidate = candidates[index];
		let best: LabelBox | null = null;
		let bestCost = Infinity;
		for (let side = 0; side < SIDES.length; side++) {
			const box = boxAt(candidate, SIDES[side], gap);
			if (
				box.left < PAD ||
				box.top < PAD ||
				box.left + box.width > width - PAD ||
				box.top + box.height > height - PAD
			)
				continue;
			if (taken.some((other) => boxesMeet(box, other))) continue;
			if (points.some(([x, y]) => (x !== candidate.x || y !== candidate.y) && holds(box, x, y)))
				continue;
			const crossings = segments.filter((segment) => segmentMeetsBox(segment, box)).length;
			const cost = side + crossings * CROSSING_COST;
			if (cost < bestCost) {
				best = box;
				bestCost = cost;
			}
		}
		if (!best) continue;
		taken.push(best);
		placed.push({ index, ...best });
	}
	return placed;
}
