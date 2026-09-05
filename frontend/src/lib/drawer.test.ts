import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { trackSheetCover } from './drawer';

describe('trackSheetCover', () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => vi.useRealTimers());

	function coveredSheet() {
		const onChange = vi.fn();
		const cover = trackSheetCover(onChange);
		cover.setAtTop(true);
		vi.runAllTimers();
		expect(onChange).toHaveBeenLastCalledWith(true);
		onChange.mockClear();
		return { cover, onChange };
	}

	it('covers once the sheet has slid onto its top snap', () => {
		const onChange = vi.fn();
		const cover = trackSheetCover(onChange);
		cover.setAtTop(true);
		expect(onChange).not.toHaveBeenCalled();
		vi.advanceTimersByTime(500);
		expect(onChange).toHaveBeenCalledTimes(1);
		expect(onChange).toHaveBeenCalledWith(true);
	});

	it('uncovers on the first pull and covers again after a release back at the top', () => {
		const { cover, onChange } = coveredSheet();
		cover.onDrag();
		expect(onChange).toHaveBeenCalledWith(false);
		cover.onDrag();
		cover.onRelease();
		expect(onChange).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(500);
		expect(onChange).toHaveBeenLastCalledWith(true);
	});

	it('stays uncovered when the release lands on a lower snap', () => {
		const { cover, onChange } = coveredSheet();
		cover.onDrag();
		cover.onRelease();
		cover.setAtTop(false);
		vi.runAllTimers();
		expect(onChange).toHaveBeenCalledTimes(1);
		expect(onChange).toHaveBeenCalledWith(false);
	});

	it('ignores a release that never pulled the sheet', () => {
		const { cover, onChange } = coveredSheet();
		cover.onRelease();
		vi.runAllTimers();
		expect(onChange).not.toHaveBeenCalled();
	});

	it('uncovers on dispose', () => {
		const { cover, onChange } = coveredSheet();
		cover.dispose();
		expect(onChange).toHaveBeenCalledWith(false);
	});
});
