/**
 * Star colour from Gaia BP−RP, as linear sRGB with its largest channel at 1.
 *
 * BP−RP gives an effective temperature by the dwarf sequence of Pecaut &
 * Mamajek (2013, ApJS 208, 9), table version 2022.04.16
 * (https://www.pas.rochester.edu/~emamajek/EEM_dwarf_UBVIJHK_colors_Teff.txt),
 * linear between its rows. The temperature gives a chromaticity on the
 * Planckian locus by the cubic fit of Kim et al. (Kang et al. 2002, J. Korean
 * Phys. Soc. 41, 865), valid 1667–25000 K. The table has BP−RP from B9V to
 * M9.5V; a colour outside it takes the temperature of the nearest end.
 * Giants and reddened stars get the temperature of a dwarf of their colour.
 */

/** (BP−RP, Teff in K), B9V to M8.5V. M9V and M9.5V are left out: their
 *  colours are bluer than M8.5V's, and the relation must be monotonic. */
const BP_RP_TEFF: readonly (readonly [number, number])[] = [
	[-0.12, 10700],
	[-0.087, 10400],
	[-0.037, 9700],
	[0.005, 9300],
	[0.068, 8800],
	[0.11, 8600],
	[0.166, 8250],
	[0.194, 8100],
	[0.222, 7910],
	[0.263, 7760],
	[0.32, 7590],
	[0.327, 7400],
	[0.377, 7220],
	[0.434, 7020],
	[0.49, 6820],
	[0.518, 6750],
	[0.546, 6670],
	[0.587, 6550],
	[0.64, 6350],
	[0.67, 6280],
	[0.694, 6180],
	[0.719, 6050],
	[0.767, 5990],
	[0.784, 5930],
	[0.803, 5860],
	[0.823, 5770],
	[0.832, 5720],
	[0.841, 5680],
	[0.85, 5660],
	[0.869, 5600],
	[0.88, 5550],
	[0.9, 5480],
	[0.95, 5380],
	[0.983, 5270],
	[1.01, 5170],
	[1.1, 5100],
	[1.21, 4830],
	[1.34, 4600],
	[1.43, 4440],
	[1.53, 4300],
	[1.7, 4100],
	[1.73, 3990],
	[1.79, 3930],
	[1.84, 3850],
	[1.97, 3770],
	[2.09, 3660],
	[2.13, 3620],
	[2.23, 3560],
	[2.39, 3470],
	[2.5, 3430],
	[2.78, 3270],
	[2.94, 3210],
	[3.16, 3110],
	[3.35, 3060],
	[3.71, 2930],
	[4.16, 2810],
	[4.5, 2740],
	[4.65, 2680],
	[4.72, 2630],
	[4.86, 2570],
	[5.1, 2420]
];

/** Effective temperature (K) of a dwarf of this BP−RP. */
export function teffFromBpRp(bpRp: number): number {
	const table = BP_RP_TEFF;
	if (bpRp <= table[0][0]) return table[0][1];
	const last = table[table.length - 1];
	if (bpRp >= last[0]) return last[1];
	let lo = 0;
	let hi = table.length - 1;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (table[mid][0] <= bpRp) lo = mid;
		else hi = mid;
	}
	const [c0, t0] = table[lo];
	const [c1, t1] = table[hi];
	return t0 + ((bpRp - c0) / (c1 - c0)) * (t1 - t0);
}

/** Linear sRGB of a black body at `teff` K, its largest channel at 1. */
export function planckianRgb(
	teff: number,
	out: [number, number, number]
): [number, number, number] {
	const t = Math.min(Math.max(teff, 1667), 25000);
	const t1 = 1e3 / t;
	const t2 = t1 * t1;
	const t3 = t2 * t1;
	const x =
		t <= 4000
			? -0.2661239 * t3 - 0.2343589 * t2 + 0.8776956 * t1 + 0.17991
			: -3.0258469 * t3 + 2.1070379 * t2 + 0.2226347 * t1 + 0.24039;
	const x2 = x * x;
	const x3 = x2 * x;
	let y: number;
	if (t <= 2222) y = -1.1063814 * x3 - 1.3481102 * x2 + 2.18555832 * x - 0.20219683;
	else if (t <= 4000) y = -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867;
	else y = 3.081758 * x3 - 5.8733867 * x2 + 3.75112997 * x - 0.37001483;
	// CIE XYZ at Y = 1, then the sRGB (D65) primaries.
	const X = x / y;
	const Z = (1 - x - y) / y;
	const r = Math.max(3.2404542 * X - 1.5371385 - 0.4985314 * Z, 0);
	const g = Math.max(-0.969266 * X + 1.8760108 + 0.041556 * Z, 0);
	const b = Math.max(0.0556434 * X - 0.2040259 + 1.0572252 * Z, 0);
	const peak = Math.max(r, g, b);
	out[0] = r / peak;
	out[1] = g / peak;
	out[2] = b / peak;
	return out;
}

const LUT_LO = BP_RP_TEFF[0][0];
const LUT_HI = BP_RP_TEFF[BP_RP_TEFF.length - 1][0];
const LUT_SIZE = 512;
/** RGB bytes by BP−RP over the table's span: one step is 0.01 mag. */
let lut: Uint8Array | null = null;

function buildLut(): Uint8Array {
	const bytes = new Uint8Array(LUT_SIZE * 3);
	const rgb: [number, number, number] = [0, 0, 0];
	for (let i = 0; i < LUT_SIZE; i++) {
		planckianRgb(teffFromBpRp(LUT_LO + ((LUT_HI - LUT_LO) * i) / (LUT_SIZE - 1)), rgb);
		bytes[3 * i] = Math.round(rgb[0] * 255);
		bytes[3 * i + 1] = Math.round(rgb[1] * 255);
		bytes[3 * i + 2] = Math.round(rgb[2] * 255);
	}
	return bytes;
}

/** RGB bytes for each BP−RP, written into `out` (3 per star). A star with no
 *  colour (NaN) is white. */
export function starColours(bpRp: Float32Array, out: Uint8Array): Uint8Array {
	const table = (lut ??= buildLut());
	const scale = (LUT_SIZE - 1) / (LUT_HI - LUT_LO);
	for (let i = 0; i < bpRp.length; i++) {
		const c = bpRp[i];
		if (Number.isNaN(c)) {
			out[3 * i] = 255;
			out[3 * i + 1] = 255;
			out[3 * i + 2] = 255;
			continue;
		}
		const at = 3 * Math.round(Math.min(Math.max((c - LUT_LO) * scale, 0), LUT_SIZE - 1));
		out[3 * i] = table[at];
		out[3 * i + 1] = table[at + 1];
		out[3 * i + 2] = table[at + 2];
	}
	return out;
}
