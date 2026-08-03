/**
 * Whether a chart label's name and its reading can share a line.
 *
 * Measured rather than assumed, because the answer is a translation away from
 * changing: "Core · 5,127–5,727 °C" fits the interior cross-section's gutter
 * with room to spare, and Polish's "Jądro wewnętrzne" does not.
 */

/** Breathing room between a left-aligned name and a right-aligned reading. */
const GAP = 4;

/** `rows` is what the labels were built from: passing it is what makes the
 *  measurement re-run when the chart's contents change, not just when its text
 *  elements are replaced. */
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
