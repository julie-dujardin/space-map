import { describe, it, expect } from 'vitest';
import { scatterTooltipLeft, SCATTER_TOOLTIP_MAX_W } from './scatter-tooltip';

describe('scatterTooltipLeft', () => {
	it('sits beside the cursor with room to spare', () => {
		expect(scatterTooltipLeft(40, 600)).toBe(50);
	});

	// The bug this replaces: both charts clamped 60px short of their own
	// max-width, so a full-width tooltip hung over the chart's right edge.
	it('keeps the far edge inside the chart', () => {
		for (const width of [300, 480, 600]) {
			for (const x of [0, width / 2, width - 1, width]) {
				expect(scatterTooltipLeft(x, width) + SCATTER_TOOLTIP_MAX_W).toBeLessThanOrEqual(width);
			}
		}
	});

	it('stays on screen in a chart too narrow to hold it', () => {
		expect(scatterTooltipLeft(10, 200)).toBe(0);
	});
});
