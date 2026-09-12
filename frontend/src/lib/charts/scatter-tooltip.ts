/**
 * Where the orbit scatters put their hover tooltip. Shared so the clamp and the
 * width it clamps against cannot drift apart — each chart used to carry its own
 * pair, both clamping 60px short of their own maximum and so overflowing the
 * chart on the right.
 */

/** Widest the tooltip may render, px. */
export const SCATTER_TOOLTIP_MAX_W = 260;

/** Gap between the cursor and the tooltip, px. */
const CURSOR_GAP = 10;

/** Left edge for a tooltip at `mouseX` in a chart `width` px wide: beside the
 *  cursor, pulled back so the far edge stays inside, and never off the left. */
export function scatterTooltipLeft(mouseX: number, width: number): number {
	return Math.max(0, Math.min(mouseX + CURSOR_GAP, width - SCATTER_TOOLTIP_MAX_W));
}
