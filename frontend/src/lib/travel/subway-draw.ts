/**
 * Pixels for the Δv map: the tree laid out as a subway diagram, in either
 * of the two orientations the page uses.
 *
 * Rows: one vertical trunk down the left, every destination a line off it to
 * the right, moons hanging under their planet. Fits a page column and reads
 * top to bottom.
 *
 * Strip: the same tree on its side for a phone — the trunk along the bottom,
 * destinations rising from it, meant to be scrolled sideways. It comes out as
 * two sheets, since the level names stay put while the map scrolls under them.
 *
 * Only geometry and text come out; the page decides fonts and theme colours,
 * so `currentColor` stands for "the trunk's colour" throughout.
 */

import type { StationKind } from '$lib/math/travel/subway';
import type { Reach } from './subway-reach';
import type { Tree, TreeLeg, TreeRow, TreeStop, TreeTotals } from './subway-tree';

/** Set on everything belonging to a stop a chosen craft cannot pay for. */
interface Dimmable {
	dim: boolean;
}

export interface DrawLine extends Dimmable {
	points: string;
	color: string;
	width: number;
	opacity: number;
}

export interface DrawStop extends Dimmable {
	x: number;
	y: number;
	r: number;
	color: string;
	filled: boolean;
	href: string | null;
	/** What the stop is, for the link's title. */
	label: string;
}

export interface DrawLabel extends Dimmable {
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

export interface DrawAero extends Dimmable {
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
	/** A leg figure, bare: the unit is said once, on the total it belongs to. */
	fmt: (kms: number) => string;
	/** A total, with its unit — the only place on the diagram the unit appears,
	 *  since neither layout has room to repeat it on every leg. */
	fmtTotal: (kms: number) => string;
	/** Where a stop links; null for no link. `targetId` is the row's body, the
	 *  origin itself on the trunk. */
	link: (stop: TreeStop, targetId: string) => string | null;
	/** What a chosen craft can reach; null where no craft is chosen, or where
	 *  the one chosen states no budget the map can weigh it by. */
	reach?: Reach | null;
}

/** Whether a stop is out of the chosen craft's reach. */
function dimmer(reach: Reach | null | undefined): (station: string) => boolean {
	if (!reach) return () => false;
	return (station) => !reach.stops.has(station);
}

/** The trunk stops in order with the rows that leave from each, and the y (or
 *  x) each one needs. The escape ladder makes this a list rather than the two
 *  fixed stops the map started with. */
function trunkGroups(tree: Tree): TreeRow[][] {
	return tree.trunk.map((_, i) => tree.rows.filter((r) => r.trunkIndex === i));
}

/** How much room a row and its moons take along the trunk. */
function rowSpan(row: TreeRow, pitch: number, moonPitch: number, gap: number): number {
	return pitch + row.moons.length * moonPitch + (row.bound ? 0 : gap);
}

/** A line while the sheet is still being moved about: points stay numbers
 *  until the drawing is handed over. */
interface PendingLine extends Omit<DrawLine, 'points'> {
	pts: [number, number][];
}

class Sheet {
	/** Stamped on everything pushed while it is set: the stops out of the
	 *  chosen craft's reach, and the lines and figures that belong to them. */
	dim = false;
	lines: PendingLine[] = [];
	/** Drawn after every other line: the trunk and the drops moons hang from,
	 *  so a branch never crosses over what it branches from. */
	over: PendingLine[] = [];
	stops: DrawStop[] = [];
	labels: DrawLabel[] = [];
	aeros: DrawAero[] = [];

	line(pts: [number, number][], color: string, width = 6, opacity = 1, over = false): void {
		(over ? this.over : this.lines).push({ pts, color, width, opacity, dim: this.dim });
	}

	drawing(width: number, height: number): Drawing {
		const serialise = (l: PendingLine): DrawLine => ({
			points: l.pts.map((p) => p.join(',')).join(' '),
			color: l.color,
			width: l.width,
			opacity: l.opacity,
			dim: l.dim
		});
		return {
			width,
			height,
			lines: [...this.lines, ...this.over].map(serialise),
			stops: this.stops,
			labels: this.labels,
			aeros: this.aeros
		};
	}

	/** How far the sheet could slide up and still begin `pad` above what is
	 *  drawn. The strip's levels are fixed, so the headroom over the tallest
	 *  column is dead space the reader would otherwise have to scroll past. */
	headroom(pad: number, height: number): number {
		const top = Math.min(
			height,
			...this.stops.map((s) => s.y - s.r),
			...this.labels.map((l) => labelTop(l))
		);
		return Math.max(0, Math.floor(top - pad));
	}

	/** How far right anything on the sheet reaches, labels included: the strip
	 *  is scrolled to its own edge, so a name overhanging it would be clipped
	 *  with nothing left to scroll to. */
	rightEdge(): number {
		return Math.max(
			0,
			...this.stops.map((s) => s.x + s.r),
			...this.labels.map((l) => labelRight(l)),
			...this.aeros.map((a) => a.x + AERO_R)
		);
	}

	/** Slide everything up by `dy`. The strip's map and its level names are two
	 *  sheets side by side, so both take the map's headroom to stay level. */
	shift(dy: number): void {
		for (const l of [...this.lines, ...this.over]) {
			l.pts = l.pts.map(([x, y]) => [x, y - dy]);
		}
		for (const s of this.stops) s.y -= dy;
		for (const l of this.labels) l.y -= dy;
		for (const a of this.aeros) a.y -= dy;
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
		this.stops.push({ x, y, r, color, filled, href, label, dim: this.dim });
	}

	aero(x: number, y: number): void {
		this.aeros.push({ x, y, dim: this.dim });
	}

	text(
		x: number,
		y: number,
		text: string,
		o: Partial<Omit<DrawLabel, 'x' | 'y' | 'text'>> = {}
	): DrawLabel {
		// Nothing on the map smaller than 12 px: captions and headings included.
		const label: DrawLabel = {
			x,
			y,
			text,
			size: Math.max(o.size ?? 12, 12),
			weight: o.weight ?? 500,
			muted: o.muted ?? false,
			anchor: o.anchor ?? 'middle',
			rotate: o.rotate ?? 0,
			href: o.href ?? null,
			title: o.title ?? null,
			dim: this.dim
		};
		this.labels.push(label);
		return label;
	}
}

/** Rough width of a label. This module cannot measure a font, so the glyph
 *  count stands in; the figure only decides how much room to leave, and is
 *  deliberately generous. Nothing is drawn under 12 px, so neither is it
 *  measured under 12 px. */
function labelWidth(text: string, size: number): number {
	return text.length * Math.max(size, 12) * 0.62;
}

/** The aerobrake arc's own half-width, and the room it keeps off the figure it
 *  belongs to. */
const AERO_R = 6;
const AERO_GAP = 3;

/** Where the arc marking a braked leg goes: just past the figure, which is
 *  what it qualifies, so a long figure pushes it out rather than running
 *  under it. */
function aeroX(label: DrawLabel): number {
	return labelRight(label) + AERO_GAP + AERO_R;
}

/** How far a label reaches to the right of its anchor. Rotation is the rows'
 *  business and never the strip's, so it is ignored. */
function labelRight(l: DrawLabel): number {
	const w = labelWidth(l.text, l.size);
	if (l.anchor === 'end') return l.x;
	return l.x + (l.anchor === 'middle' ? w / 2 : w);
}

/** How far a label reaches above its anchor. */
function labelTop(l: DrawLabel): number {
	const half = l.size / 2;
	if (!l.rotate) return l.y - half;
	return l.y - half - labelWidth(l.text, l.size) * Math.sin((Math.abs(l.rotate) * Math.PI) / 180);
}

/** A total as the page prints it beside a row: what the row's last stop comes
 *  to, then braked where an atmosphere can pay for part of it. A row drawn
 *  through to the surface is totalled through its landing burn, so the legs
 *  printed along it sum to the total printed beside it. */
function totalText(totals: TreeTotals | null, o: DrawOptions): string {
	if (!totals) return '';
	const plain = totals.surfaceKms ?? totals.orbitKms;
	const aero = totals.surfaceKms === null ? totals.aeroOrbitKms : totals.aeroSurfaceKms;
	// The unit rides the last figure only: a braked pair is two readings of the
	// same quantity, and saying km/s twice costs more room than the column has.
	if (aero === null) return o.fmtTotal(plain);
	return `${o.fmt(plain)}  ·  ${o.fmtTotal(aero)}`;
}

/** The label under a stop that is not what its column says: the two stops of
 *  the stationary row, and the Sun's orbit. */
function stopCaption(row: TreeRow, stop: TreeStop, text: DrawText): string | null {
	if (row.stationary && stop.kind === 'transfer') return text.gto;
	return null;
}

// ---------------------------------------------------------------- rows

const ROWS_WIDTH = 900;
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
	const out = dimmer(o.reach);
	const S = new Sheet();
	// Nothing to hang the rows off: an origin the catalogue could not place.
	if (tree.trunk.length === 0) return S.drawing(ROWS_WIDTH, 0);
	const dv = (x1: number, x2: number, y: number, leg: TreeLeg, below = false) => {
		const ly = below ? y + 13 : y - 12;
		const figure = S.text((x1 + x2) / 2, ly, fmt(leg.dvKms), { weight: 600, size: 12 });
		if (leg.aero) S.aero(aeroX(figure), ly + 3);
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
	const lastTrunk = tree.trunk.length - 1;
	// The line stops where its last stop is, unless rows still hang under it.
	const yEnd = groups[lastTrunk].length > 0 ? y - 12 : trunkYs[lastTrunk];

	// The way out of the root's well ends the trunk and is named as such.
	const trunkLabel = (i: number) => {
		if (i === lastTrunk && tree.trunkEnd) return text.rootEscape;
		const kind = tree.trunk[i].kind;
		return kind === 'escape' ? text.escape : text.stop[kind];
	};
	// One segment per stop, in that stop's colour: out of a moon the trunk
	// turns the planet's colour where it leaves the moon's well.
	S.dim = out(tree.trunk[lastTrunk].station);
	S.line(
		[
			[BUS_X, trunkYs[lastTrunk]],
			[BUS_X, yEnd]
		],
		tree.trunk[lastTrunk].color,
		7,
		1,
		true
	);
	/** How far down the trunk the rows leaving stop `i` hang. The stretch below
	 *  a stop is the bus those rows branch from, so it is that stop's to grey
	 *  out, not the next one's: a reachable stop keeps a lit line under it even
	 *  where the climb past it is out of reach. */
	const branchEnd = (i: number): number => {
		const group = groups[i];
		const last = group[group.length - 1];
		if (!last) return trunkYs[i];
		return rowYs.get(last.moons[last.moons.length - 1] ?? last)!;
	};
	tree.trunk.forEach((stop, i) => {
		const from = i === 0 ? trunkYs[0] : trunkYs[i - 1];
		const split = i === 0 ? from : Math.min(trunkYs[i], branchEnd(i - 1));
		if (split > from) {
			S.dim = out(tree.trunk[i - 1].station);
			S.line(
				[
					[BUS_X, from],
					[BUS_X, split]
				],
				stop.color,
				7,
				1,
				true
			);
		}
		S.dim = out(stop.station);
		S.line(
			[
				[BUS_X, split],
				[BUS_X, trunkYs[i]]
			],
			stop.color,
			7,
			1,
			true
		);
		const end = i === lastTrunk && tree.trunkEnd !== null;
		S.stop(
			BUS_X,
			trunkYs[i],
			stop.color,
			8,
			end,
			end ? null : link(stop, tree.originId),
			trunkLabel(i)
		);
		S.text(
			BUS_X + 16,
			trunkYs[i],
			end ? trunkLabel(i) : `${stop.name} · ${trunkLabel(i)}`,
			end ? { size: 14, weight: 600, anchor: 'start' } : { size: 11, muted: true, anchor: 'start' }
		);
		if (end) {
			S.text(COL_TOTAL, trunkYs[i], totalText(tree.trunkEnd, o), {
				anchor: 'start',
				size: 12,
				muted: true
			});
		}
		if (i > 0) {
			S.text(BUS_X + 16, trunkYs[i] - 26, fmt(tree.trunkLegs[i - 1].dvKms), {
				weight: 600,
				size: 12,
				anchor: 'start'
			});
		}
	});

	// Column headings name the map rather than a stop, so a craft never dims them.
	S.dim = false;
	(['transfer', 'escape', 'orbit', 'surface'] as const).forEach((kind) =>
		S.text(COL[kind], 18, text.stop[kind], { size: 10.5, muted: true, title: text.hint[kind] })
	);
	S.text(COL_TOTAL, 18, text.totals, { size: 10.5, muted: true, anchor: 'start' });

	const drawStops = (row: TreeRow, rowY: number, from: number, small: boolean) => {
		const r = small ? 5 : 6;
		let x = from;
		row.stops.forEach((stop, i) => {
			S.dim = out(stop.station);
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
		S.dim = row.stops.length > 0 && out(row.stops[0].station);
		S.text(BUS_X + 14, rowY - 13, row.stationary ? text.stop.stationary : row.name, {
			anchor: 'start',
			weight: 600,
			size: 14,
			href: row.stops[0] ? link(row.stops[0], row.targetId) : null
		});
		drawStops(row, rowY, BUS_X, false);
		S.dim = out(row.stops[row.stops.length - 1].station);
		if (row.totals) {
			S.text(COL_TOTAL, rowY, totalText(row.totals, o), {
				anchor: 'start',
				size: 12,
				muted: true
			});
		}
		for (const moon of row.moons) {
			const my = rowYs.get(moon)!;
			S.dim = out(moon.stops[0].station);
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
			S.dim = out(moon.stops[moon.stops.length - 1].station);
			S.text(COL_TOTAL, my, totalText(moon.totals, o), {
				anchor: 'start',
				size: 12,
				muted: true
			});
		}
	}

	return S.drawing(ROWS_WIDTH, yEnd + 30);
}

// --------------------------------------------------------------- strip

const STRIP_HEIGHT = 646;
/** Where each kind of stop sits up the strip. A phone is short, so the rungs
 *  sit only as far apart as one Δv figure between two stops needs. */
const LEVEL: Record<StationKind, number> = {
	transfer: 534,
	escape: 460,
	orbit: 386,
	surface: 312,
	stationary: 460
};
const Y_TRUNK = 600;
/** Narrowest a column may be, before its labels ask for more. */
const ROW_PITCH = 70;
const MOON_PITCH = 54;
/** Where the trunk's own stops sit. */
const X_SURFACE = 40;
const X_LEO = 120;
const X_ESCAPE = 330;
/** Room before the level names, so they are not flush against the screen. */
const LEVELS_PAD = 5;
/** Room past the last thing drawn, so it is not flush against the scroll end. */
const TAIL_PAD = 24;
const LEVELS: readonly StationKind[] = ['transfer', 'escape', 'orbit', 'surface'];

/** The strip in two pieces: the map, which scrolls, and the level names, which
 *  do not, so a reader deep in the map still knows what the rungs are. */
export interface StripDrawing {
	map: Drawing;
	legend: Drawing;
}

export function drawStrip(o: DrawOptions): StripDrawing {
	const { tree, text, fmt, link } = o;
	const out = dimmer(o.reach);
	const S = new Sheet();
	const L = new Sheet();
	if (tree.trunk.length === 0) {
		return { map: S.drawing(0, STRIP_HEIGHT), legend: L.drawing(0, STRIP_HEIGHT) };
	}
	const dv = (x: number, y1: number, y2: number, leg: TreeLeg) => {
		const figure = S.text(x + 9, (y1 + y2) / 2, fmt(leg.dvKms), {
			weight: 600,
			size: 11.5,
			anchor: 'start'
		});
		if (leg.aero) S.aero(aeroX(figure), (y1 + y2) / 2 + 3);
	};

	const groups = trunkGroups(tree);
	const ground = tree.trunk[0]?.kind === 'surface';

	// Trunk stops along the bottom, each followed by the rows that rise from it.
	const orbitIndex = ground ? 1 : 0;
	const trunkXs: number[] = [];
	if (ground) trunkXs[0] = X_SURFACE;
	let x = X_LEO;
	const colXs = new Map<TreeRow, number>();
	// Names and totals sit level over their column, so the column has to be as
	// wide as the longer of the two.
	const colWidth = (row: TreeRow, small: boolean): number => {
		const name = row.stationary ? text.stop.stationary : row.name;
		return Math.round(
			Math.max(
				small ? MOON_PITCH : ROW_PITCH,
				labelWidth(name, small ? 12 : 14),
				labelWidth(totalText(row.totals, o), 12)
			) + 14
		);
	};
	for (let i = orbitIndex; i < tree.trunk.length; i++) {
		if (i > orbitIndex) x = Math.max(i === orbitIndex + 1 ? X_ESCAPE : 0, x + 10);
		trunkXs[i] = x;
		x += 24;
		for (const r of groups[i]) {
			const w = colWidth(r, false);
			colXs.set(r, x + w / 2);
			x += w;
			for (const moon of r.moons) {
				const mw = colWidth(moon, true);
				colXs.set(moon, x + mw / 2);
				x += mw;
			}
			x += 16;
		}
	}
	const lastTrunk = tree.trunk.length - 1;
	// The line stops where its last stop is, unless columns still rise past it.
	const xEnd = groups[lastTrunk].length > 0 ? x - 16 : trunkXs[lastTrunk];

	// The way out of the root's well ends the trunk and is named as such.
	const trunkLabel = (i: number) => {
		if (i === lastTrunk && tree.trunkEnd) return text.rootEscape;
		const kind = tree.trunk[i].kind;
		return kind === 'escape' ? text.escape : text.stop[kind];
	};
	S.dim = out(tree.trunk[lastTrunk].station);
	S.line(
		[
			[trunkXs[lastTrunk], Y_TRUNK],
			[xEnd, Y_TRUNK]
		],
		tree.trunk[lastTrunk].color,
		7,
		1,
		true
	);
	/** How far along the trunk the columns rising from stop `i` reach; see the
	 *  rows layout for why that stretch is the stop's own to grey out. */
	const branchEnd = (i: number): number => {
		const group = groups[i];
		const last = group[group.length - 1];
		if (!last) return trunkXs[i];
		return colXs.get(last.moons[last.moons.length - 1] ?? last)!;
	};
	tree.trunk.forEach((stop, i) => {
		const from = i === 0 ? trunkXs[0] : trunkXs[i - 1];
		const split = i === 0 ? from : Math.min(trunkXs[i], branchEnd(i - 1));
		// One segment per stop, in that stop's colour: out of a moon the trunk
		// turns the planet's colour where it leaves the moon's well.
		if (split > from) {
			S.dim = out(tree.trunk[i - 1].station);
			S.line(
				[
					[from, Y_TRUNK],
					[split, Y_TRUNK]
				],
				stop.color,
				7,
				1,
				true
			);
		}
		S.dim = out(stop.station);
		S.line(
			[
				[split, Y_TRUNK],
				[trunkXs[i], Y_TRUNK]
			],
			stop.color,
			7,
			1,
			true
		);
		const end = i === lastTrunk && tree.trunkEnd !== null;
		S.stop(
			trunkXs[i],
			Y_TRUNK,
			stop.color,
			8,
			end,
			end ? null : link(stop, tree.originId),
			trunkLabel(i)
		);
		// The strip has no room for a name on every stop, but a second escape
		// stop is another body's and has to say whose.
		S.text(
			trunkXs[i],
			Y_TRUNK + 22,
			end || stop.bodyId === tree.originId ? trunkLabel(i) : `${stop.name} · ${trunkLabel(i)}`,
			{ size: 10.5, muted: true, weight: end ? 600 : 500 }
		);
		if (end) {
			S.text(trunkXs[i], Y_TRUNK + 38, totalText(tree.trunkEnd, o), {
				size: 10,
				muted: true
			});
		}
		if (i > 0) {
			S.text(trunkXs[i] - 22, Y_TRUNK - 14, fmt(tree.trunkLegs[i - 1].dvKms), {
				weight: 600,
				size: 12
			});
		}
	});

	// Level names sit on their own sheet and name the map rather than a stop.
	S.dim = false;
	LEVELS.forEach((kind) => {
		L.text(LEVELS_PAD, LEVEL[kind], text.stop[kind], {
			size: 10.5,
			muted: true,
			title: text.hint[kind],
			anchor: 'start'
		});
	});

	const drawStops = (row: TreeRow, cx: number, fromY: number, small: boolean) => {
		const r = small ? 5 : 6;
		let y = fromY;
		row.stops.forEach((stop, i) => {
			S.dim = out(stop.station);
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
		const top = drawStops(row, cx, Y_TRUNK, false);
		S.dim = out(row.stops[0].station);
		S.text(cx, top - 44, row.stationary ? text.stop.stationary : row.name, {
			weight: 600,
			size: 14,
			href: row.stops[0] ? link(row.stops[0], row.targetId) : null
		});
		S.dim = out(row.stops[row.stops.length - 1].station);
		if (row.totals) S.text(cx, top - 26, totalText(row.totals, o), { size: 11, muted: true });
		for (const moon of row.moons) {
			const mx = colXs.get(moon)!;
			S.dim = out(moon.stops[0].station);
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
			S.dim = out(moon.stops[0].station);
			S.text(mx, mtop - 44, moon.name, {
				size: 12,
				href: moon.stops[0] ? link(moon.stops[0], moon.targetId) : null
			});
			S.dim = out(moon.stops[moon.stops.length - 1].station);
			S.text(mx, mtop - 26, totalText(moon.totals, o), { size: 10, muted: true });
		}
	}

	// Both sheets slide up by the map's headroom so the names stay level with
	// the rungs they name.
	const dy = S.headroom(10, STRIP_HEIGHT);
	S.shift(dy);
	L.shift(dy);
	const height = STRIP_HEIGHT - dy;
	// The names sit right up against the map: the width below is only an
	// estimate, and the slack it leaves is gap enough.
	const legendWidth = Math.round(L.rightEdge());
	const width = Math.round(Math.max(xEnd, S.rightEdge()) + TAIL_PAD);
	return { map: S.drawing(width, height), legend: L.drawing(legendWidth, height) };
}
