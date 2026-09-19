/**
 * How the row fits its bodies to the screen: the boxes it stands them in, the
 * strips it keeps for the bands on either side, and how many of a set stand on
 * one screen with their names before the rest turn the page. The compare page
 * cuts its pages with the same arithmetic the row lays them out with, so a
 * body it puts on a page always has room for its name.
 */

/** Equal margin above and below the largest body. */
export const VPAD = 10;
/** A page takes in more bodies by shrinking its largest, down to this share of
 *  the height: past it the row is small again, names or not. */
const LARGEST_MIN_SHARE = 0.5;
export const SIDE_PAD = 6;
/** Clear air between neighbouring boxes. */
export const BOX_GAP = 8;
/** A name is never wider than this, whatever room its body has. */
export const LABEL_MAX_WIDTH = 180;
/** Air on either side of a name, so names in neighbouring boxes read apart. */
const LABEL_PAD = 8;
/** The label font size, as the row's markup sets it. */
const LABEL_FONT_SIZE = '11px';

// Edge room for a neighbouring band: the band before it gets this share of
// the row, the same on every page so it reads as an edge rather than as a
// body of its own; the band after needs only its own width when it is a speck.
const LIMB_SHARE = 0.065;
const LIMB_MIN = 44;
const LIMB_MAX = 120;
/** The gutter a speck-sized body from the page after sits in. */
export const ASIDE_END_PAD = 44;

/** The strip at the start of the row given to the band before it. */
export const limbStrip = (width: number): number =>
	Math.max(LIMB_MIN, Math.min(LIMB_MAX, width * LIMB_SHARE));

/** The strip at the end of the row given to the body after it, drawn `pr` px
 *  in radius: a speck sits in its gutter; anything wider shows its limb at the
 *  edge, the way the band before does at the start. */
export function endStrip(pr: number, width: number): number {
	return 2 * pr <= ASIDE_END_PAD ? ASIDE_END_PAD : limbStrip(width);
}

/** One body as the fit sees it: its size, and the room its name needs. */
export interface FitBody {
	radiusKm: number;
	label: number;
}

let measure: CanvasRenderingContext2D | null | undefined;
const measured = new Map<string, number>();

/** Text width in the row's label font, cached once the web font is in. */
function textWidth(text: string, weight: number): number {
	if (measure === undefined) {
		measure =
			typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
	}
	if (!measure) return text.length * 6.5;
	const key = `${weight} ${text}`;
	const hit = measured.get(key);
	if (hit !== undefined) return hit;
	measure.font = `${weight} ${LABEL_FONT_SIZE} ${getComputedStyle(document.body).fontFamily}`;
	const width = measure.measureText(text).width;
	if (document.fonts.status === 'loaded') measured.set(key, width);
	return width;
}

/** The room a body's name and size need under it, in row pixels. */
export function labelWidth(name: string, size: string): number {
	return Math.min(
		LABEL_MAX_WIDTH,
		Math.max(textWidth(name, 500), textWidth(size, 400)) + LABEL_PAD
	);
}

/** The run `bodies` take standing in boxes at `k` px per km. */
function runOf(bodies: readonly FitBody[], k: number): number {
	return bodies.reduce(
		(sum, b) => sum + Math.max(2 * b.radiusKm * k, b.label),
		(bodies.length - 1) * BOX_GAP
	);
}

/** The widest scale, up to `maxK`, at which `bodies` stand in `run` px, each
 *  in a box as wide as itself or its name. */
export function fitScale(bodies: readonly FitBody[], run: number, maxK: number): number {
	if (runOf(bodies, maxK) <= run) return maxK;
	let lo = 0;
	let hi = maxK;
	for (let i = 0; i < 40; i++) {
		const mid = (lo + hi) / 2;
		if (runOf(bodies, mid) <= run) lo = mid;
		else hi = mid;
	}
	return lo;
}

/** The scale a row is drawn on when nothing else constrains it: its largest
 *  body fills the height. */
export const fullScale = (radiusKm: number, height: number): number =>
	(height - 2 * VPAD) / (2 * radiusKm);

/** The run a screen has for its boxes: the width less the strips for the page
 *  before (unless this is the `first`) and for `after`, the body that follows,
 *  as it would be drawn at `padScale`. */
function screenRun(
	after: FitBody | undefined,
	padScale: number,
	width: number,
	first: boolean
): number {
	const padStart = first ? 0 : limbStrip(width);
	const padEnd = after ? endStrip(after.radiusKm * padScale, width) : 0;
	return width - 2 * SIDE_PAD - padStart - padEnd;
}

/**
 * How many of `bodies`, largest first, stand on one screen at `k` px per km
 * with their names: the first so many, and always at least one. What follows
 * the last of them — the rest of `bodies`, else `after` — takes the strip at
 * the end, sized as the row will size it at `padScale`; the page before takes
 * the one at the start unless this is the `first` screen.
 */
export function screenCount(
	bodies: readonly FitBody[],
	after: FitBody | undefined,
	k: number,
	padScale: number,
	width: number,
	first: boolean
): number {
	let n = 1;
	while (n < bodies.length) {
		const run = screenRun(bodies[n + 1] ?? after, padScale, width, first);
		if (runOf(bodies.slice(0, n + 1), k) > run) break;
		n++;
	}
	return n;
}

/**
 * The first screen of a band, and with it the scale the whole band is drawn
 * on: as many of `bodies` as stand there with the largest at no less than half
 * the height, on the widest scale that holds them. The screens after it keep
 * that scale, so turning a page never changes what a pixel means until the
 * band does.
 */
export function bandScreen(
	bodies: readonly FitBody[],
	after: FitBody | undefined,
	width: number,
	height: number
): { count: number; scale: number } {
	const full = fullScale(bodies[0].radiusKm, height);
	const count = screenCount(bodies, after, full * LARGEST_MIN_SHARE, full, width, true);
	const run = screenRun(bodies[count] ?? after, full, width, true);
	return { count, scale: fitScale(bodies.slice(0, count), run, full) };
}
