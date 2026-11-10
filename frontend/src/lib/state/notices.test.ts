/**
 * The out-of-range notice clears the arrival toast that says the focused object
 * has no place at this date, once the date gives it one.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { toast } = vi.hoisted(() => ({
	toast: { warning: vi.fn(), info: vi.fn(), dismiss: vi.fn() }
}));
vi.mock('svelte-sonner', () => ({ toast }));

import { UNPLACED_TOAST, dismissNotice, showNotice } from './notices';

const quiet = { topic: 'out-of-range', satellites: null, majorBodies: null } as const;

describe('unplaced arrival toast', () => {
	beforeEach(() => vi.clearAllMocks());

	it('stays while the focused object is out of range', () => {
		showNotice({ ...quiet, focusedOutOfRange: true });
		expect(toast.dismiss).not.toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('goes when only other groups are out of range', () => {
		showNotice({ ...quiet, focusedOutOfRange: false, majorBodies: { side: 'outside' } });
		expect(toast.dismiss).toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('goes when the out-of-range notice is dismissed', () => {
		dismissNotice('out-of-range');
		expect(toast.dismiss).toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('is left alone by the coverage pause', () => {
		dismissNotice('coverage-pause');
		expect(toast.dismiss).not.toHaveBeenCalledWith(UNPLACED_TOAST);
	});
});
