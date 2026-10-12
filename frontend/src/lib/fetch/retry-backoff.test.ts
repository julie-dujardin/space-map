import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RetryBackoff } from '$lib/fetch/retry-backoff';

/** No jitter: `random` at its midpoint. */
const steady = (onDue?: (key: string) => void) => new RetryBackoff<string>(onDue, () => 0.5);

describe('RetryBackoff', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
	});

	it('lets a key load until it fails', () => {
		expect(steady().waiting('a')).toBe(false);
	});

	it('holds a failed key for the delay, and tells when it ends', () => {
		const due: string[] = [];
		const backoff = steady((key) => due.push(key));
		backoff.fail('a');
		expect(backoff.waiting('a')).toBe(true);
		// Another key is not held.
		expect(backoff.waiting('b')).toBe(false);
		vi.advanceTimersByTime(1999);
		expect(backoff.waiting('a')).toBe(true);
		expect(due).toEqual([]);
		vi.advanceTimersByTime(1);
		expect(backoff.waiting('a')).toBe(false);
		expect(due).toEqual(['a']);
	});

	it('doubles the delay with each failure in a row, up to a minute', () => {
		const backoff = steady();
		const delays: number[] = [];
		for (let i = 0; i < 8; i++) {
			backoff.fail('a');
			const from = Date.now();
			while (backoff.waiting('a')) vi.advanceTimersByTime(1000);
			delays.push(Date.now() - from);
		}
		expect(delays).toEqual([2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000]);
	});

	it('starts over after a success, and tells nothing for a key that loaded', () => {
		const due: string[] = [];
		const backoff = steady((key) => due.push(key));
		backoff.fail('a');
		vi.advanceTimersByTime(2000);
		backoff.fail('a');
		backoff.clear('a');
		expect(backoff.waiting('a')).toBe(false);
		vi.advanceTimersByTime(60_000);
		expect(due).toEqual(['a']);
		// The first delay again, not the third.
		backoff.fail('a');
		vi.advanceTimersByTime(2000);
		expect(backoff.waiting('a')).toBe(false);
	});

	it('spreads the delay by a quarter either way', () => {
		const early = new RetryBackoff<string>(undefined, () => 0);
		const late = new RetryBackoff<string>(undefined, () => 1);
		early.fail('a');
		late.fail('a');
		vi.advanceTimersByTime(1500);
		expect(early.waiting('a')).toBe(false);
		expect(late.waiting('a')).toBe(true);
		vi.advanceTimersByTime(1000);
		expect(late.waiting('a')).toBe(false);
	});
});
