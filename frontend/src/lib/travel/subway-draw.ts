/**
 * Pixels for the Δv map: the tree laid out as a subway diagram, in either
 * of the two orientations the page uses.
 *
 * Rows: one vertical trunk down the left, every destination a line off it to
 * the right, moons hanging under their planet. Fits a page column and reads
 * top to bottom.
 *
 * Strip: the same tree on its side for a phone — the trunk along the bottom,
 * destinations rising from it, meant to be scrolled sideways.
 *
 * Only geometry and text come out; the page decides fonts and theme colours,
 * so `currentColor` stands for "the trunk's colour" throughout.
 */

import type { StationKind } from '$lib/math/travel/subway';
import type { Tree, TreeLeg, TreeRow, TreeStop } from './subway-tree';

export interface DrawLine {
	points: string;
	color: string;
	width: number;
	opacity: number;
}

export interface DrawStop {
	x: number;
	y: number;
	r: number;
	color: string;
	filled: boolean;
	href: string | null;
	/** What the stop is, for the link's title. */
	label: string;
}

export interface DrawLabel {
	x: number;
	y: number;
	text: string;
	size: number;
	weight: 400 | 500 | 600;
	muted: boolean;
	anchor: 'start' | 'middle' | 'end';
	rotate: number;
	href: string | null;
	/** Hover text, for the column headings that name a kind of stop. */
	title: string | null;
}

export interface DrawAero {
	x: number;
	y: number;
}

export interface Drawing {
	width: number;
	height: number;
	lines: DrawLine[];
	stops: DrawStop[];
	labels: DrawLabel[];
	aeros: DrawAero[];
}

/** What to call each kind of stop, and the two column headings that are not a
 *  stop. Passed in so this module carries no message import. */
export interface DrawText {
	stop: Record<StationKind, string>;
	/** What a column heading says on hover, where there is anything to say. */
	hint: Partial<Record<StationKind, string>>;
	/** The trunk's escape stop, which is not a capture. */
	escape: string;
	/** The origin's own transfer stop: the ellipse up to its stationary orbit. */
	gto: string;
	/** Heading over the totals column. */
	totals: string;
	/** The last stop off the trunk: out of the root's well. */
	rootEscape: string;
}

export interface DrawOptions {
	tree: Tree;
	text: DrawText;
	/** km/s as the page prints it. */
	fmt: (kms: number) => string;
	/** Where a stop links; null for no link. `targetId` is the row's body, the
	 *  origin itself on the trunk. */
	link: (stop: TreeStop, targetId: string) => string | null;
}

/** The trunk stops in order with the rows that leave from each, and the y (or
 *  x) each one needs. The escape ladder makes this a list rather than the two
 *  fixed stops the map started with. */
function trunkGroups(tree: Tree): TreeRow[][] {
	return tree.trunk.map((_, i) => [
		...tree.rows.filter((r) => r.trunkIndex === i && !r.escape),
		...tree.rows.filter((r) => r.trunkIndex === i && r.escape)
	]);
}

/** How much room a row and its moons take along the trunk. */
function rowSpan(row: TreeRow, pitch: number, moonPitch: number, gap: number): number {
	return pitch + row.moons.length * moonPitch + (row.bound ? 0 : gap);
}

class Sheet {
	lines: DrawLine[] = [];
	/** Drawn after every other line: the trunk and the drops moons hang from,
	 *  so a branch never crosses over what it branches from. */
	over: DrawLine[] = [];
	stops: DrawStop[] = [];
	labels: DrawLabel[] = [];
	aeros: DrawAero[] = [];

	line(points: [number, number][], color: string, width = 6, opacity = 1, over = false): void {
		(over ? this.over : this.lines).push({
			points: points.map((p) => p.join(',')).join(' '),
			color,
			width,
			opacity
		});
	}

	drawing(width: number, height: number): Drawing {
		return {
			width,
			height,
			lines: [...this.lines, ...this.over],
			stops: this.stops,
			labels: this.labels,
			aeros: this.aeros
		};
	}

	stop(
		x: number,
		y: number,
		color: string,
		r: number,
		filled: boolean,
		href: string | null,
		label: string
	): void {
		this.stops.push({ x, y, r, color, filled, href, label });
	}

	text(
		x: number,
		y: number,
		text: string,
		o: Partial<Omit<DrawLabel, 'x' | 'y' | 'text'>> = {}
	): void {
		// Nothing on the map smaller than 12 px: captions and headings included.
		this.labels.push({
			x,
			y,
			text,
			size: Math.max(o.size ?? 12, 12),
			weight: o.weight ?? 500,
			muted: o.muted ?? false,
			anchor: o.anchor ?? 'middle',
			rotate: o.rotate ?? 0,
			href: o.href ?? null,
			title: o.title ?? null
		});
	}
}

/** A total as the page prints it beside a row: to orbit, then braked where an
 *  atmosphere can pay for part of it. */
function totalText(row: TreeRow, fmt: DrawOptions['fmt']): string {
	if (!row.totals) return '';
	const { orbitKms, aeroOrbitKms } = row.totals;
	return aeroOrbitKms === null ? fmt(orbitKms) : `${fmt(orbitKms)}  ·  ${fmt(aeroOrbitKms)}`;
}

/** The label under a stop that is not what its column says: the two stops of
 *  the stationary row, and the Sun's orbit. */
function stopCaption(row: TreeRow, stop: TreeStop, text: DrawText): string | null {
	if (row.stationary && stop.kind === 'transfer') return text.gto;
	return null;
}

// ---------------------------------------------------------------- rows

const ROWS_WIDTH = 848;
/** Where each kind of stop sits across the page. */
const COL: Record<StationKind, number> = {
	transfer: 330,
	escape: 460,
	orbit: 590,
	surface: 720,
	// The stationary orbit takes the capture column: the row has two stops.
	stationary: 460
};
const COL_TOTAL = 754;
const BUS_X = 60;

export function drawRows(o: DrawOptions): Drawing {
	const { tree, text, fmt, link } = o;
	const S = new Sheet();
	// Nothing to hang the rows off: an origin the catalogue could not place.
	if (tree.trunk.length === 0) return S.drawing(ROWS_WIDTH, 0);
	const dv = (x1: number, x2: number, y: number, leg: TreeLeg, below = false) => {
		const ly = below ? y + 13 : y - 12;
		S.text((x1 + x2) / 2, ly, fmt(leg.dvKms), { weight: 600, size: 12 });
		if (leg.aero) S.aeros.push({ x: (x1 + x2) / 2 + 26, y: ly + 3 });
	};

	const groups = trunkGroups(tree);
	const ground = tree.trunk[0]?.kind === 'surface';

	// Trunk stops down the left, each followed by the rows that leave from it.
	const yTop = 40;
	const orbitIndex = ground ? 1 : 0;
	const trunkYs: number[] = [];
	if (ground) trunkYs[0] = yTop;
	let y = ground ? 110 : yTop;
	const rowYs = new Map<TreeRow, number>();
	for (let i = orbitIndex; i < tree.trunk.length; i++) {
		if (i > orbitIndex) y += 14;
		trunkYs[i] = y;
		y += 44;
		for (const r of groups[i]) {
			rowYs.set(r, y);
			y += rowSpan(r, 42, 34, 12);
			for (const [k, mo] of r.moons.entries()) rowYs.set(mo, rowYs.get(r)! + 42 + k * 34);
		}
	}
	const yEnd = y - 12;

	const trunkLabel = (kind: StationKind) => (kind === 'escape' ? text.escape : text.stop[kind]);
	// One segment per stop, in that stop's colour: out of a moon the trunk
	// turns the planet's colour where it leaves the moon's well.
	const lastTrunk = tree.trunk.length - 1;
	// Past the last stop the trunk is already in the well above it, so the
	// tail takes that body's colour rather than the origin's.
	S.line(
		[
			[BUS_X, trunkYs[lastTrunk]],
			[BUS_X, yEnd]
		],
		tree.trunkTailColor,
		7,
		1,
		true
	);
	tree.trunk.forEach((stop, i) => {
		S.line(
			[
				[BUS_X, i === 0 ? trunkYs[0] : trunkYs[i - 1]],
				[BUS_X, trunkYs[i]]
			],
			stop.color,
			7,
			1,
			true
		);
		S.stop(
			BUS_X,
			trunkYs[i],
			stop.color,
			8,
			false,
			link(stop, tree.originId),
			trunkLabel(stop.kind)
		);
		S.text(BUS_X + 16, trunkYs[i], `${stop.name} · ${trunkLabel(stop.kind)}`, {
			size: 11,
			muted: true,
			anchor: 'start'
		});
		if (i > 0) {
			S.text(BUS_X + 16, trunkYs[i] - 26, fmt(tree.trunkLegs[i - 1].dvKms), {
				weight: 600,
				size: 12,
				anchor: 'start'
			});
		}
	});

	// Column headings.
	(['transfer', 'escape', 'orbit', 'surface'] as const).forEach((kind) =>
		S.text(COL[kind], 18, text.stop[kind], { size: 10.5, muted: true, title: text.hint[kind] })
	);
	S.text(COL_TOTAL, 18, text.totals, { size: 10.5, muted: true, anchor: 'start' });

	const drawStops = (row: TreeRow, rowY: number, from: number, small: boolean) => {
		const r = small ? 5 : 6;
		let x = from;
		row.stops.forEach((stop, i) => {
			const cx = COL[stop.kind];
			const legIn = i === 0 ? row.depart : row.legs[i - 1];
			const isEntry = i === 0;
			S.line(
				[
					[x, rowY],
					[cx, rowY]
				],
				row.color,
				small ? 4 : 6,
				small ? 0.85 : 1
			);
			// The entry figure sits under the line where the name sits over it.
			dv(x, cx, rowY, legIn, isEntry && !small);
			const last = i === row.stops.length - 1;
			const interchange = stop.kind === 'transfer' && row.moons.length > 0;
			S.stop(
				cx,
				rowY,
				row.color,
				interchange ? 8 : r,
				last && stop.kind !== 'transfer',
				link(stop, row.targetId),
				text.stop[stop.kind]
			);
			const caption = stopCaption(row, stop, text);
			if (caption) S.text(cx, rowY + 16, caption, { size: 10, muted: true });
			x = cx;
		});
	};

	for (const row of tree.rows) {
		const rowY = rowYs.get(row)!;
		if (row.escape) {
			S.line(
				[
					[BUS_X, rowY],
					[COL.transfer, rowY]
				],
				row.color,
				6
			);
			dv(BUS_X, COL.transfer, rowY, row.depart, true);
			S.text(BUS_X + 14, rowY - 13, text.rootEscape, { anchor: 'start', weight: 600, size: 14 });
			S.stop(COL.transfer, rowY, row.color, 6, true, null, text.rootEscape);
			if (row.totals)
				S.text(COL_TOTAL, rowY, totalText(row, fmt), { anchor: 'start', size: 12, muted: true });
			continue;
		}
		S.text(BUS_X + 14, rowY - 13, row.stationary ? text.stop.stationary : row.name, {
			anchor: 'start',
			weight: 600,
			size: 14,
			href: row.stops[0] ? link(row.stops[0], row.targetId) : null
		});
		drawStops(row, rowY, BUS_X, false);
		if (row.totals) {
			S.text(COL_TOTAL, rowY, totalText(row, fmt), { anchor: 'start', size: 12, muted: true });
		}
		for (const moon of row.moons) {
			const my = rowYs.get(moon)!;
			// Down from the shared intercept stop, then across.
			S.line(
				[
					[COL.transfer, rowY],
					[COL.transfer, my]
				],
				row.color,
				4,
				0.85,
				true
			);
			S.text(COL.transfer - 12, my, moon.name, {
				anchor: 'end',
				size: 11.5,
				href: moon.stops[0] ? link(moon.stops[0], moon.targetId) : null
			});
			drawStops(moon, my, COL.transfer, true);
			S.text(COL_TOTAL, my, totalText(moon, fmt), { anchor: 'start', size: 12, muted: true });
		}
	}

	return S.drawing(ROWS_WIDTH, yEnd + 30);
}

// --------------------------------------------------------------- strip

const STRIP_HEIGHT = 660;
/** Where each kind of stop sits up the strip. */
const LEVEL: Record<StationKind, number> = {
	transfer: 516,
	escape: 418,
	orbit: 320,
	surface: 222,
	stationary: 418
};
const Y_TRUNK = 600;
const X_SURFACE = 40;
const X_LEO = 120;
const X_ESCAPE = 330;

export function drawStrip(o: DrawOptions): Drawing {
	const { tree, text, fmt, link } = o;
	const S = new Sheet();
	if (tree.trunk.length === 0) return S.drawing(0, STRIP_HEIGHT);
	const dv = (x: number, y1: number, y2: number, leg: TreeLeg) => {
		S.text(x + 9, (y1 + y2) / 2, fmt(leg.dvKms), { weight: 600, size: 11.5, anchor: 'start' });
		if (leg.aero) S.aeros.push({ x: x + 9 + 34, y: (y1 + y2) / 2 + 3 });
	};

	const groups = trunkGroups(tree);
	const ground = tree.trunk[0]?.kind === 'surface';

	// Trunk stops along the bottom, each followed by the rows that rise from it.
	const orbitIndex = ground ? 1 : 0;
	const trunkXs: number[] = [];
	if (ground) trunkXs[0] = X_SURFACE;
	let x = X_LEO;
	const colXs = new Map<TreeRow, number>();
	for (let i = orbitIndex; i < tree.trunk.length; i++) {
		// The first escape stop keeps its old place unless the bound rows push it on.
		if (i > orbitIndex) x = Math.max(i === orbitIndex + 1 ? X_ESCAPE : 0, x + 10);
		trunkXs[i] = x;
		x += 70;
		for (const r of groups[i]) {
			colXs.set(r, x);
			for (const [k, mo] of r.moons.entries()) colXs.set(mo, x + 70 + k * 54);
			x += rowSpan(r, 70, 54, 16);
		}
	}
	const xEnd = x - 16;

	const trunkLabel = (kind: StationKind) => (kind === 'escape' ? text.escape : text.stop[kind]);
	const lastTrunk = tree.trunk.length - 1;
	S.line(
		[
			[trunkXs[lastTrunk], Y_TRUNK],
			[xEnd, Y_TRUNK]
		],
		tree.trunkTailColor,
		7,
		1,
		true
	);
	tree.trunk.forEach((stop, i) => {
		// One segment per stop, in that stop's colour: out of a moon the trunk
		// turns the planet's colour where it leaves the moon's well.
		S.line(
			[
				[i === 0 ? trunkXs[0] : trunkXs[i - 1], Y_TRUNK],
				[trunkXs[i], Y_TRUNK]
			],
			stop.color,
			7,
			1,
			true
		);
		S.stop(
			trunkXs[i],
			Y_TRUNK,
			stop.color,
			8,
			false,
			link(stop, tree.originId),
			trunkLabel(stop.kind)
		);
		// The strip has no room for a name on every stop, but a second escape
		// stop is another body's and has to say whose.
		S.text(
			trunkXs[i],
			Y_TRUNK + 22,
			stop.bodyId === tree.originId
				? trunkLabel(stop.kind)
				: `${stop.name} · ${trunkLabel(stop.kind)}`,
			{ size: 10.5, muted: true }
		);
		if (i > 0) {
			S.text(trunkXs[i] - 22, Y_TRUNK - 14, fmt(tree.trunkLegs[i - 1].dvKms), {
				weight: 600,
				size: 12
			});
		}
	});

	// Level names at the far end.
	(['transfer', 'escape', 'orbit', 'surface'] as const).forEach((kind) =>
		S.text(xEnd + 30, LEVEL[kind], text.stop[kind], {
			size: 10.5,
			muted: true,
			anchor: 'start',
			title: text.hint[kind]
		})
	);

	const drawStops = (row: TreeRow, cx: number, fromY: number, small: boolean) => {
		const r = small ? 5 : 6;
		let y = fromY;
		row.stops.forEach((stop, i) => {
			const cy = LEVEL[stop.kind];
			const legIn = i === 0 ? row.depart : row.legs[i - 1];
			S.line(
				[
					[cx, y],
					[cx, cy]
				],
				row.color,
				small ? 4 : 6,
				small ? 0.85 : 1
			);
			dv(cx, y, cy, legIn);
			const last = i === row.stops.length - 1;
			const interchange = stop.kind === 'transfer' && row.moons.length > 0;
			S.stop(
				cx,
				cy,
				row.color,
				interchange ? 8 : r,
				last && stop.kind !== 'transfer',
				link(stop, row.targetId),
				text.stop[stop.kind]
			);
			const caption = stopCaption(row, stop, text);
			if (caption) S.text(cx - 12, cy + 12, caption, { size: 10, muted: true, anchor: 'end' });
			y = cy;
		});
		return y;
	};

	for (const row of tree.rows) {
		const cx = colXs.get(row)!;
		if (row.escape) {
			S.line(
				[
					[cx, Y_TRUNK],
					[cx, LEVEL.transfer]
				],
				row.color,
				6
			);
			dv(cx, Y_TRUNK, LEVEL.transfer, row.depart);
			S.stop(cx, LEVEL.transfer, row.color, 6, true, null, text.rootEscape);
			S.text(cx - 2, LEVEL.transfer - 20, text.rootEscape, {
				rotate: -55,
				anchor: 'start',
				weight: 600,
				size: 13
			});
			if (row.totals) {
				S.text(cx + 16, LEVEL.transfer - 20, totalText(row, fmt), {
					rotate: -55,
					anchor: 'start',
					size: 10,
					muted: true
				});
			}
			continue;
		}
		const top = drawStops(row, cx, Y_TRUNK, false);
		S.text(cx, top - 26, row.stationary ? text.stop.stationary : row.name, {
			weight: 600,
			size: 14,
			href: row.stops[0] ? link(row.stops[0], row.targetId) : null
		});
		if (row.totals) S.text(cx, top - 44, totalText(row, fmt), { size: 11, muted: true });
		for (const moon of row.moons) {
			const mx = colXs.get(moon)!;
			// Across from the shared intercept stop with a bend, then up.
			S.line(
				[
					[cx, LEVEL.transfer],
					[mx - 24, LEVEL.transfer],
					[mx, LEVEL.transfer - 24]
				],
				row.color,
				4,
				0.85,
				true
			);
			const mtop = drawStops(moon, mx, LEVEL.transfer - 24, true);
			S.text(mx - 2, mtop - 20, moon.name, {
				rotate: -55,
				anchor: 'start',
				size: 12,
				href: moon.stops[0] ? link(moon.stops[0], moon.targetId) : null
			});
			S.text(mx + 16, mtop - 20, totalText(moon, fmt), {
				rotate: -55,
				anchor: 'start',
				size: 10,
				muted: true
			});
		}
	}

	return S.drawing(xEnd + 130, STRIP_HEIGHT);
}
