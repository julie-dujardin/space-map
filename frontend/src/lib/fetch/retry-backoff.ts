/**
 * When a failed load may be tried again, per key.
 *
 * For a loader that something polls (the frame loop, a clock tick): a poll
 * has no memory, so a file that fails is asked for again on every one.
 */

const FIRST_DELAY_MS = 2_000;
const MAX_DELAY_MS = 60_000;
/** Share of the delay it is spread by, so the clients of one outage do not
 *  all come back in the same second. */
const JITTER = 0.25;

interface Failure {
	/** Failures in a row. */
	count: number;
	/** Runs while the key waits. */
	timer: ReturnType<typeof setTimeout> | undefined;
}

export class RetryBackoff<K> {
	private readonly failures = new Map<K, Failure>();

	/**
	 * `onDue` is told when the wait of a key ends. A poller that can stand
	 * still needs it: nothing else brings it back to the key.
	 */
	constructor(
		private readonly onDue: (key: K) => void = () => {},
		private readonly random: () => number = Math.random
	) {}

	/** True while `key` waits out its last failure. */
	waiting(key: K): boolean {
		return this.failures.get(key)?.timer !== undefined;
	}

	/** A load of `key` failed: the wait doubles with each failure in a row. */
	fail(key: K): void {
		const last = this.failures.get(key);
		clearTimeout(last?.timer);
		const failure: Failure = { count: (last?.count ?? 0) + 1, timer: undefined };
		const delay = Math.min(FIRST_DELAY_MS * 2 ** (failure.count - 1), MAX_DELAY_MS);
		const spread = 1 + JITTER * (2 * this.random() - 1);
		failure.timer = setTimeout(() => {
			failure.timer = undefined;
			this.onDue(key);
		}, delay * spread);
		this.failures.set(key, failure);
	}

	/** A load of `key` succeeded. */
	clear(key: K): void {
		clearTimeout(this.failures.get(key)?.timer);
		this.failures.delete(key);
	}
}
