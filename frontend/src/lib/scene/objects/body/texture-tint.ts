import { Color, type Texture } from 'three';

/**
 * Base material colour that turns a *grayscale* surface map into local albedo
 * over the body's measured surface hue: a black-and-white asteroid/moon texture
 * carries the spatial detail, `data.color` (physically-derived, see
 * export/small_body_color.py) carries the hue. A raw multiply would double-count
 * brightness (the tint already bakes in albedo, so does the map's mean), so the
 * tint is reduced to pure chromaticity (luminance 1) — multiplying it preserves
 * each texel's brightness while colouring it. A neutral-grey tint (the Moon,
 * unclassified bodies) collapses to white, leaving the map untouched.
 *
 * Already-coloured maps (Mimas) and untinted bodies return white → plain map.
 * The result is memoised on the Texture so the sphere and shape-model paths,
 * which share one Texture object, analyse the pixels once.
 */
export function tintBaseColor(texture: Texture, tintHex?: string): Color {
	const cache = texture.userData as { tintBase?: Color; tintKey?: string };
	const key = tintHex ?? '';
	if (cache.tintBase && cache.tintKey === key) return cache.tintBase;
	const base = computeTintBase(texture, tintHex);
	cache.tintBase = base;
	cache.tintKey = key;
	return base;
}

/** Sample grid for the grayscale test — tiny; we only need mean chroma. */
const SAMPLE_W = 32;
const SAMPLE_H = 16;
/** Mean sRGB chroma (max−min channel) above which the map is treated as
 *  colour and left as-is. Measured: grayscale shape-model maps (Eros, Bennu,
 *  Phobos, …) read ≤0.0003; the faintest genuinely-coloured map (the Moon)
 *  reads ~0.033, icy moons ~0.05. This sits in the wide gap between them. */
const GRAY_CHROMA_THRESHOLD = 0.01;
/** Below this linear luminance the tint is effectively black; its chromaticity
 *  is numerically unstable, so leave the map untinted. */
const MIN_TINT_LUMINANCE = 0.001;

function computeTintBase(texture: Texture, tintHex?: string): Color {
	const white = new Color(0xffffff);
	if (!tintHex) return white;
	const chroma = meanChroma(texture);
	if (chroma === null || chroma > GRAY_CHROMA_THRESHOLD) return white;
	// Color(hex) reads sRGB and stores linear working-space components.
	const tint = new Color(tintHex);
	const lum = 0.2126 * tint.r + 0.7152 * tint.g + 0.0722 * tint.b;
	if (lum < MIN_TINT_LUMINANCE) return white;
	// Normalise to luminance 1: multiplying a grayscale texel keeps its
	// brightness and injects only the hue.
	return new Color().setRGB(tint.r / lum, tint.g / lum, tint.b / lum);
}

/** Mean per-pixel chroma (max−min of RGB, 0..1) of a downscaled copy of the
 *  texture, or null if the image can't be read (not decoded yet, or a tainted
 *  cross-origin canvas — then we conservatively skip tinting). */
function meanChroma(texture: Texture): number | null {
	const img = texture.image as CanvasImageSource & { width?: number; height?: number };
	if (!img || !img.width || !img.height) return null;
	const canvas = document.createElement('canvas');
	canvas.width = SAMPLE_W;
	canvas.height = SAMPLE_H;
	const g = canvas.getContext('2d', { willReadFrequently: true });
	if (!g) return null;
	g.drawImage(img, 0, 0, SAMPLE_W, SAMPLE_H);
	let data: Uint8ClampedArray;
	try {
		data = g.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data;
	} catch {
		return null; // tainted canvas
	}
	let sum = 0;
	const n = data.length / 4;
	for (let i = 0; i < data.length; i += 4) {
		const r = data[i] / 255;
		const gg = data[i + 1] / 255;
		const b = data[i + 2] / 255;
		sum += Math.max(r, gg, b) - Math.min(r, gg, b);
	}
	return sum / n;
}
