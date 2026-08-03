/**
 * Label layout shared by the cross-section charts: sliding stacked labels
 * apart, and whether a label's name and its reading can share a line.
 */

/**
 * Slide labels apart until none overlaps, keeping each as close to the point it
 * points at as it can.
 *
 * Two passes, down then up: the first opens every gap to `spacing`, the second
 * pulls the stack back inside `[min, max]` without reopening one. Bands are
 * nested, so a body with a 24 km ice shell over a 1,000 km mantle would
 * otherwise stack three labels on the same pixel.
 */
export function spreadLabels(
	anchors: number[],
	spacing: number,
	min: number,
	max: number
): number[] {
	const out = [...anchors];
	for (let i = 1; i < out.length; i++) {
		if (out[i] - out[i - 1] < spacing) out[i] = out[i - 1] + spacing;
	}
	const overflow = out.length ? out[out.length - 1] - max : 0;
	if (overflow > 0) {
		for (let i = 0; i < out.length; i++) out[i] -= overflow;
		for (let i = out.length - 2; i >= 0; i--) {
			if (out[i + 1] - out[i] < spacing) out[i] = out[i + 1] - spacing;
		}
	}
	const under = out.length ? min - out[0] : 0;
	if (under > 0) for (let i = 0; i < out.length; i++) out[i] += under;
	return out;
}

/** `spreadLabels` over rows: each entry keeps its fields and gains the `labelY`
 *  its anchor was slid to. Entries must already run top-to-bottom. */
export function spreadRows<T extends { anchorY: number }>(
	entries: T[],
	spacing: number,
	min: number,
	max: number
): (T & { labelY: number })[] {
	const ys = spreadLabels(
		entries.map((e) => e.anchorY),
		spacing,
		min,
		max
	);
	return entries.map((e, i) => ({ ...e, labelY: ys[i] }));
}

/** Breathing room between a left-aligned name and a right-aligned reading. */
const GAP = 4;

/**
 * Whether each row's name and reading need separate lines. Measured rather
 * than assumed, because the answer is a translation away from changing:
 * "Core · 5,127–5,727 °C" fits the interior cross-section's gutter with room
 * to spare, and Polish's "Jądro wewnętrzne" does not.
 *
 * `rows` is what the labels were built from: passing it is what makes the
 * measurement re-run when the chart's contents change, not just when its text
 * elements are replaced.
 */
export function stackedRows(
	rows: readonly unknown[],
	names: (SVGTextElement | undefined | null)[],
	values: (SVGTextElement | undefined | null)[],
	width: number
): boolean[] {
	return rows.map((_, i) => {
		const name = names[i];
		const value = values[i];
		if (!name || !value) return false;
		return name.getComputedTextLength() + GAP + value.getComputedTextLength() > width;
	});
}
