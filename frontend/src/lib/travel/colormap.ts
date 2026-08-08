/**
 * Viridis, the perceptually-uniform colormap matplotlib made the default.
 *
 * A porkchop is a continuous scalar field, which is the one case the app's
 * categorical and single-hue ramps are wrong for: equal steps in Δv have to
 * look like equal steps in colour, and a five-step ramp turns a smooth basin
 * into contour bands that aren't in the data. Viridis is monotonic in
 * lightness, so it also survives greyscale printing and every kind of colour
 * blindness — the property a rainbow famously lacks.
 *
 * Sixteen stops sampled off the reference 256-entry table; linear interpolation
 * between them is well under one JND, and the whole thing is 16 lines instead
 * of a 256-row data blob.
 */

type Rgb = readonly [number, number, number];

const VIRIDIS: readonly Rgb[] = [
	[68, 1, 84],
	[71, 24, 106],
	[72, 45, 117],
	[69, 63, 124],
	[64, 80, 127],
	[58, 96, 128],
	[52, 111, 128],
	[47, 125, 127],
	[42, 139, 124],
	[40, 152, 119],
	[45, 166, 111],
	[60, 179, 99],
	[85, 191, 83],
	[117, 202, 64],
	[153, 211, 44],
	[192, 218, 33]
];

/** Same treatment for plasma, which reads warmer against a dark surface. */
const PLASMA: readonly Rgb[] = [
	[13, 8, 135],
	[57, 4, 160],
	[92, 1, 166],
	[124, 3, 161],
	[153, 21, 147],
	[177, 42, 128],
	[198, 64, 110],
	[216, 87, 93],
	[231, 111, 76],
	[242, 136, 60],
	[249, 163, 44],
	[252, 191, 33],
	[248, 220, 37],
	[240, 249, 33],
	[240, 249, 33],
	[240, 249, 33]
];

export type ColormapName = 'viridis' | 'plasma';

const TABLES: Record<ColormapName, readonly Rgb[]> = { viridis: VIRIDIS, plasma: PLASMA };

/** Colour at position `t` in [0, 1], as a CSS `rgb()` string. */
export function sample(name: ColormapName, t: number): string {
	const table = TABLES[name];
	if (!Number.isFinite(t)) return 'transparent';
	const clamped = t < 0 ? 0 : t > 1 ? 1 : t;
	const x = clamped * (table.length - 1);
	const i = Math.min(table.length - 2, Math.floor(x));
	const f = x - i;
	const a = table[i];
	const b = table[i + 1];
	const mix = (lo: number, hi: number) => Math.round(lo + (hi - lo) * f);
	return `rgb(${mix(a[0], b[0])} ${mix(a[1], b[1])} ${mix(a[2], b[2])})`;
}

/** The whole ramp as a CSS gradient, for a legend bar. */
export function gradient(name: ColormapName, to = 'right'): string {
	const stops = TABLES[name]
		.map(
			(c, i) =>
				`rgb(${c[0]} ${c[1]} ${c[2]}) ${((i / (TABLES[name].length - 1)) * 100).toFixed(1)}%`
		)
		.join(', ');
	return `linear-gradient(to ${to}, ${stops})`;
}
