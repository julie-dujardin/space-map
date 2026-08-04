/**
 * Label layout shared by the cross-section charts: sliding stacked labels
 * apart, and whether a label's name and its reading can share a line.
 */

/** The cross-section frame, sized to the drawer's content width so the label
 *  sizes in the charts render at the sizes they say — scaling a 320-wide chart
 *  into 264px shrank 10px text to 8. */
export const FRAME_W = 264;
export const FRAME_H = 190;

/** A label is two lines: the name, and the layer's extent under it. */
export const SECOND_LINE_DY = 11;

/** How far down a label's name can be pushed. The second line hangs below it,
 *  so a bound set off the frame alone clips that line out of the SVG. */
export const LABEL_MAX_Y = FRAME_H - SECOND_LINE_DY - 3;

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

/**
 * Wire a chart's measurement to everything that invalidates it, and return the
 * teardown. Call from an `$effect`, whose own dependency tracking covers the
 * data changing; this covers the page changing under it.
 *
 * Twice beyond the initial run: once the webfont resolves, because until then
 * the widths are the fallback family's, and whenever `el` is laid out. The
 * second is what catches a chart built inside a hidden tab panel — the drawer
 * mounts the Structure tab while the Overview is showing, and a text node in a
 * hidden subtree measures 0, so every label "fits" until the panel is revealed.
 */
export function remeasure(el: Element | undefined, measure: () => void): () => void {
	measure();
	let live = true;
	document.fonts.ready.then(() => live && measure());
	const observer = new ResizeObserver(() => measure());
	if (el) observer.observe(el);
	return () => {
		live = false;
		observer.disconnect();
	};
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
 *
 * Call this from an `$effect`, never a `$derived`, and wire it up with
 * `remeasure`. A derived is read while the `<text>` nodes still hold the empty
 * content they were cloned with — Svelte sets a row's `y` before it sets the
 * name's text — so every pair measures 0 and "fits", and nothing invalidates
 * the derived once the text lands. The Sun's "Transition region · 19,730 –
 * 999,700 °C" then printed over itself.
 *
 * The answer is only meaningful where the chart has a box; callers drop it
 * otherwise rather than committing a screenful of zeroes.
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
