/**
 * Where a mosaic's imagery lies on its sphere, read from the texture's alpha,
 * and the turn that faces it. The archive's label geometry is not enough: a
 * "full" sweep can still have a gap, a partial one is rarely a clean box, and
 * some stops carry no geometry at all. The alpha is what the reader sees.
 */

const DEG = Math.PI / 180;
/** Sample size; the aim only has to land within a degree or two. */
const WIDTH = 256;
const HEIGHT = 128;
/** A sweep whose mean direction is shorter than this goes nearly all round:
 *  there is no side to face, so the reader's heading stands. */
const MIN_ANISOTROPY = 0.05;
/** Rows thinner than this share of the fullest row are stray edge texels,
 *  not a band worth pitching to. */
const ROW_SHARE = 0.25;

export interface CoverageMask {
	width: number;
	height: number;
	/** One byte per texel, row-major from the top-left: 1 where imagery is. */
	covered: Uint8Array;
}

export interface Aim {
	/** Compass heading, degrees clockwise from north. */
	heading: number;
	/** Degrees above the horizon. */
	pitch: number;
}

export interface AimFrame {
	/** Image azimuth of north, degrees clockwise from the texture's left edge. */
	northOffsetDeg: number;
	/** The view's field, horizontal and vertical, degrees. */
	hfovDeg: number;
	vfovDeg: number;
}

/** The texture's alpha at sample size, or null where the pixels cannot be
 *  read (a canvas tainted by a texture served without CORS). */
export function coverageMask(image: CanvasImageSource): CoverageMask | null {
	try {
		const canvas = document.createElement('canvas');
		canvas.width = WIDTH;
		canvas.height = HEIGHT;
		const ctx = canvas.getContext('2d', { willReadFrequently: true });
		if (!ctx) return null;
		ctx.drawImage(image, 0, 0, WIDTH, HEIGHT);
		const { data } = ctx.getImageData(0, 0, WIDTH, HEIGHT);
		const covered = new Uint8Array(WIDTH * HEIGHT);
		for (let i = 0; i < covered.length; i++) covered[i] = data[i * 4 + 3] > 127 ? 1 : 0;
		return { width: WIDTH, height: HEIGHT, covered };
	} catch {
		return null;
	}
}

/** The view turned to face the imagery: a partial sweep's middle, weighted
 *  by where the imagery is; a sweep that goes all round keeps `view`'s
 *  heading. The pitch stays where it is unless that looks past the top or
 *  bottom of what lies ahead, and then comes just inside it. */
export function aimAtCoverage(mask: CoverageMask, view: Aim, frame: AimFrame): Aim {
	const { width, height, covered } = mask;
	const azimuth = new Float64Array(width);
	for (let x = 0; x < width; x++) azimuth[x] = ((x + 0.5) * 360) / width;
	const elevation = new Float64Array(height);
	for (let y = 0; y < height; y++) elevation[y] = 90 - ((y + 0.5) * 180) / height;

	// Mean direction of the imagery, each texel weighted by its solid angle.
	let sumX = 0;
	let sumZ = 0;
	let sumW = 0;
	for (let y = 0; y < height; y++) {
		const w = Math.cos(elevation[y] * DEG);
		for (let x = 0; x < width; x++) {
			if (!covered[y * width + x]) continue;
			sumX += w * Math.sin(azimuth[x] * DEG);
			sumZ += w * Math.cos(azimuth[x] * DEG);
			sumW += w;
		}
	}
	if (sumW === 0) return view;
	const anisotropy = Math.hypot(sumX, sumZ) / sumW;
	const heading =
		anisotropy < MIN_ANISOTROPY
			? view.heading
			: wrap(Math.atan2(sumX, sumZ) / DEG - frame.northOffsetDeg);

	// The band of imagery across the columns the view will show.
	const centre = wrap(heading + frame.northOffsetDeg);
	const halfWidth = Math.min(180, frame.hfovDeg / 2);
	const rowCounts = new Float64Array(height);
	let fullest = 0;
	for (let x = 0; x < width; x++) {
		const off = Math.abs(((azimuth[x] - centre + 540) % 360) - 180);
		if (off > halfWidth) continue;
		for (let y = 0; y < height; y++) {
			if (covered[y * width + x]) fullest = Math.max(fullest, ++rowCounts[y]);
		}
	}
	let top = -Infinity;
	let bottom = Infinity;
	for (let y = 0; y < height; y++) {
		if (rowCounts[y] < fullest * ROW_SHARE) continue;
		top = Math.max(top, elevation[y]);
		bottom = Math.min(bottom, elevation[y]);
	}
	if (top < bottom) return { heading, pitch: view.pitch };
	const margin = Math.min(frame.vfovDeg / 3, (top - bottom) / 2);
	const pitch = Math.max(bottom + margin, Math.min(top - margin, view.pitch));
	return { heading, pitch };
}

function wrap(deg: number): number {
	return ((deg % 360) + 360) % 360;
}
